"""各家 Tuning（03 B-03：差异点只允许出现在 Tuning 数据表 / Transport / 钩子）。

思考抽象档（off / low / mid / high / auto，03 §2）到各家载荷的映射，
以 2026-11-13 §5.7.1 核对结果为准（03 已回填）：

- DeepSeek：``thinking: {type}`` 开关（off→disabled）+ ``reasoning_effort``
  （low/high/max，默认 high）；思考模式下 temperature 被服务端忽略。
- GLM-5.3 系：**强制思考**（``thinking.type: disabled`` 报错）——统一走
  ``reasoning_effort``（low/high/max，默认 max）；"off" 降级为 low（已知）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from perudo.adapters.sdk.config import AdapterConfig

__all__ = ["ProviderTuning", "DEEPSEEK_TUNING", "GLM_TUNING", "get_tuning"]

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


def get_tuning(provider: str) -> ProviderTuning:
    """按 provider 取 Tuning（P3 落地 deepseek/glm；其余四家 M4b）。"""
    tunings = {"deepseek": DEEPSEEK_TUNING, "glm": GLM_TUNING}
    tuning = tunings.get(provider)
    if tuning is None:
        raise ValueError(f"provider {provider} 的适配器未实现（P3：deepseek/glm；M4b：其余四家）")
    return tuning
