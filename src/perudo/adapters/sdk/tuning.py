"""各家 Tuning（03 B-03：差异点只允许出现在 Tuning 数据表 / Transport / 钩子）。

思考抽象档（off / low / mid / high / auto，03 §2）到各家载荷的映射，
以 2026-11-13/14 §5.7.1 核对结果为准（03 已回填）：

- DeepSeek：``thinking: {type}`` 开关（off→disabled）+ ``reasoning_effort``
  （low/high/max，默认 high）；思考模式下 temperature 被服务端忽略。
- GLM-5.3 系：**强制思考**（``thinking.type: disabled`` 报错）——统一走
  ``reasoning_effort``（low/high/max，默认 max）；"off" 降级为 low（已知）。
- MiMo：独立 ``reasoning_content`` 返回；Anthropic 兼容端点为
  ``api.xiaomimimo.com/anthropic/v1/messages``（双协议，§5.7.1 核对）。
- Qwen：``enable_thinking`` + ``thinking_budget`` 走请求体顶层（非标准参数，
  官方口径）；思考 token 按输出计费——B-05 阶段化预算落定 1024/8192。
- 豆包：``thinking: {type: enabled/disabled/auto}``（auto=自适应思考）；
  ``model`` 接受型号名或 ``ep-`` 接入点 ID（双形态，§5.7.1 核对）。
- MiniMax：交错思考 ``<think>`` 块剥离 → reasoning_content 回传（官方口径，
  防破坏前缀缓存）；parsing.strip_think_blocks 已实现该剥离。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from perudo.adapters.sdk.config import AdapterConfig

__all__ = [
    "DEEPSEEK_TUNING",
    "DOUBAO_TUNING",
    "GLM_TUNING",
    "MIMO_TUNING",
    "MINIMAX_TUNING",
    "QWEN_TUNING",
    "ProviderTuning",
    "get_tuning",
    "get_tuning_by_provider",
]

_LEGACY_DEEPSEEK_NAMES = frozenset({"deepseek-chat", "deepseek-reasoner"})


@dataclass(frozen=True)
class ProviderTuning:
    """一家一份：默认值 + 校验钩子 + 思考档映射（SDK 对映射细节零感知）。"""

    provider: str
    default_temperature: float | None = None
    #: 校验配置（如 DeepSeek 退役名守门）；非法即 raise
    validate: Any = None
    #: 抽象思考档 → 请求体额外载荷（None = 不传任何思考参数，走服务端默认）
    thinking_payload: Any = None
    #: 呈现参数的家默认覆写（GLM full_presentation）
    presentation_defaults: dict[str, str] | None = None


def _deepseek_validate(config: AdapterConfig) -> None:
    if config.extra.get("reject_legacy_names", True) and config.model in _LEGACY_DEEPSEEK_NAMES:
        raise ValueError(
            f"型号 {config.model} 已于 2026-07-24 退役（03 §5.1）："
            "请改用 deepseek-v4-pro / deepseek-v4-flash"
        )


def _deepseek_thinking_payload(thinking: str) -> dict[str, Any] | None:
    if thinking == "off":
        return {"thinking": {"type": "disabled"}}
    if thinking == "low":
        return {"thinking": {"type": "enabled"}, "reasoning_effort": "low"}
    if thinking in ("mid", "high"):
        return {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}
    return None  # auto：走服务端默认（enabled + 默认 effort）


def _glm_validate(config: AdapterConfig) -> None:
    if config.model.startswith("glm-5.3") and config.extra.get("thinking_type") is not None:
        raise ValueError(
            "GLM-5.3 系不支持 thinking.type（disabled 会报错，03 §5.7.1）：请改用 reasoning_effort"
        )


def _glm_thinking_payload(thinking: str) -> dict[str, Any] | None:
    if thinking in ("off", "low"):
        # 5.3 系不可关思考：off 降级为 low（已知，03 §5.7.1）
        return {"reasoning_effort": "low"}
    if thinking in ("mid", "high"):
        return {"reasoning_effort": "high"}
    return None  # auto：不传，走服务端默认 max


GLM_PRESENTATION_DEFAULTS = {
    "context_presentation": "full",
    "legal_actions_presentation": "enumerate",
}


DEEPSEEK_TUNING = ProviderTuning(
    provider="deepseek",
    default_temperature=1.0,
    validate=_deepseek_validate,
    thinking_payload=_deepseek_thinking_payload,
)

GLM_TUNING = ProviderTuning(
    provider="glm",
    default_temperature=None,
    validate=_glm_validate,
    thinking_payload=_glm_thinking_payload,
    presentation_defaults=GLM_PRESENTATION_DEFAULTS,
)


def _qwen_thinking_payload(thinking: str) -> dict[str, Any] | None:
    """Qwen（N3-01 核对）：``enable_thinking`` + ``thinking_budget`` 请求体顶层。

    B-05 阶段化预算：low→1024、mid/high→8192；off 显式关闭；auto 显式开启
    （qwen-plus 融合模式逐调用生效，与回合制决策形态天然契合）。
    """
    if thinking == "off":
        return {"enable_thinking": False}
    if thinking == "low":
        return {"enable_thinking": True, "thinking_budget": 1024}
    if thinking in ("mid", "high"):
        return {"enable_thinking": True, "thinking_budget": 8192}
    return {"enable_thinking": True}  # auto：显式开启，预算走模型默认


def _doubao_validate(config: AdapterConfig) -> None:
    model = config.model
    if model.startswith("ep-"):
        return  # 方舟推理接入点 ID（双形态，§5.5）
    if not model.startswith("doubao-seed"):
        raise ValueError(f"豆包型号名应以 doubao-seed 开头或为 ep- 接入点 ID：{model}（§5.5）")


def _doubao_thinking_payload(thinking: str) -> dict[str, Any] | None:
    """豆包（N3-01 核对）：``thinking: {type: enabled/disabled/auto}`` 三档。

    Seed1.6 起 adaptive thinking；B-05 映射：off→disabled、low→auto（自适应，
    常规叫省）、mid/high→enabled；auto 抽象档 → 不传（模型自适应）。
    """
    if thinking == "off":
        return {"thinking": {"type": "disabled"}}
    if thinking == "low":
        return {"thinking": {"type": "auto"}}
    if thinking in ("mid", "high"):
        return {"thinking": {"type": "enabled"}}
    return None


MINIMAX_PRESENTATION_DEFAULTS = {
    "context_presentation": "full",  # 稳定前缀装配（§3 规范）+ 前缀缓存套利（§5.6）
    "legal_actions_presentation": "enumerate",
}


MIMO_TUNING = ProviderTuning(
    provider="mimo",
    default_temperature=None,
    thinking_payload=None,  # reasoning 参数细节留持键实测（03 §5.7.1 MiMo 行）
)

QWEN_TUNING = ProviderTuning(
    provider="qwen",
    default_temperature=0.7,
    thinking_payload=_qwen_thinking_payload,
)

DOUBAO_TUNING = ProviderTuning(
    provider="doubao",
    default_temperature=None,
    validate=_doubao_validate,
    thinking_payload=_doubao_thinking_payload,
)

MINIMAX_TUNING = ProviderTuning(
    provider="minimax",
    default_temperature=None,
    thinking_payload=None,  # 可调思考深度参数名未公开（03 §5.7.1 MiniMax 行）
    presentation_defaults=MINIMAX_PRESENTATION_DEFAULTS,
)


def get_tuning(provider: str) -> ProviderTuning:
    """按 provider 取 Tuning（P6 起六家全量；型号 ID 全走配置，N3-04）。"""
    tunings = {
        "deepseek": DEEPSEEK_TUNING,
        "glm": GLM_TUNING,
        "mimo": MIMO_TUNING,
        "qwen": QWEN_TUNING,
        "doubao": DOUBAO_TUNING,
        "minimax": MINIMAX_TUNING,
    }
    tuning = tunings.get(provider)
    if tuning is None:
        raise ValueError(f"未知 provider：{provider}（03 §3 初期六家）")
    return tuning


def get_tuning_by_provider(provider: str) -> ProviderTuning:
    """别名（各适配器工厂统一入口）。"""
    return get_tuning(provider)
