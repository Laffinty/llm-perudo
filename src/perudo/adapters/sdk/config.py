"""适配器配置与装载（03 §2 参数骨架 + §7 TOML 规范）。

红线：API Key 以 ``env:VAR`` 环境变量引用，永不落盘（03 §0.2 / B-08）；
装载时校验 ``api_key_ref`` 形态，密钥本体只在运行时从环境解析。
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

__all__ = [
    "PersonaConfig",
    "PhaseOverride",
    "QuoteConfig",
    "AdapterConfig",
    "load_player_config",
    "resolve_api_key",
]

_THINKING_LEVELS = frozenset({"off", "low", "mid", "high", "auto"})


@dataclass(frozen=True)
class PersonaConfig:
    """台词人格包（B-06，与模型无关）：不含任何规则文本。"""

    name: str
    style: str = ""
    trash_talk: int = 0  # 0–3 攻击等级

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("persona.name 不得为空（02 §4 署名）")
        if not 0 <= self.trash_talk <= 3:
            raise ValueError("trash_talk 攻击等级 0–3")


@dataclass(frozen=True)
class QuoteConfig:
    """台词开关与风格（03 §2 人格类）。"""

    enabled: bool = True
    language: str = "粤语"
    trash_talk: int = 1
    style_template: str = ""


@dataclass(frozen=True)
class PhaseOverride:
    """单阶段可覆盖的生成/思考/呈现参数（B-05）。"""

    temperature: float | None = None
    thinking: str | None = None
    max_tokens: int | None = None


@dataclass(frozen=True)
class AdapterConfig:
    """适配器统一调优参数骨架（03 §2）。

    ``extra`` 承载各家特有参数（DeepSeek 退役名守门、GLM use_flashx 等），
    由各 provider 的 Tuning 消费——SDK 对其内容零感知（B-03 差异点收口）。
    """

    provider: str
    model: str
    api_key_ref: str  # 形态 "env:VAR_NAME"
    base_url: str
    timeout_ms: int = 30_000
    net_retries: int = 3
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int = 1024
    thinking: str = "auto"  # off / low / mid / high / auto（03 §2 抽象档）
    output_mode: str = "json_mode"
    self_check_retries: int = 2
    context_presentation: str = "summary"  # full / summary
    legal_actions_presentation: str = "constraints"  # enumerate / constraints
    history_depth: int = 10
    persona: PersonaConfig = field(default_factory=lambda: PersonaConfig(name="玩家"))
    quote: QuoteConfig = field(default_factory=QuoteConfig)
    phase_overrides: dict[str, PhaseOverride] = field(default_factory=dict)
    match_token_budget: int | None = None  # B-07，默认关
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider or not self.model:
            raise ValueError("provider / model 不得为空（03 §2）")
        if not self.api_key_ref.startswith("env:"):
            raise ValueError("api_key_ref 必须为 env:VAR 形态（密钥永不落盘，B-08）")
        if not self.api_key_ref.startswith("env:") or len(self.api_key_ref) <= 4:
            raise ValueError("api_key_ref 必须为 env:VAR 形态（B-08）")
        if self.thinking not in _THINKING_LEVELS:
            raise ValueError(f"thinking 取值须为 {sorted(_THINKING_LEVELS)}（03 §2）")
        if self.timeout_ms <= 0 or self.net_retries < 0:
            raise ValueError("timeout_ms / net_retries 非法（03 §2）")
        if self.max_tokens < 1 or self.self_check_retries < 0:
            raise ValueError("max_tokens / self_check_retries 非法（03 §2）")
        if self.output_mode not in {"json_mode", "tool_call", "prompt_json"}:
            raise ValueError("output_mode 非法（03 §2）")
        if self.context_presentation not in {"full", "summary"}:
            raise ValueError("context_presentation 非法（03 §2）")
        if self.legal_actions_presentation not in {"enumerate", "constraints"}:
            raise ValueError("legal_actions_presentation 非法（03 §2）")
        if self.history_depth < 0:
            raise ValueError("history_depth 非法（03 §2）")
        for phase, override in self.phase_overrides.items():
            if phase not in {"opening", "bidding", "respond", "challenge"}:
                raise ValueError(f"phase_overrides 阶段非法：{phase}（03 §2）")
            if override.thinking is not None and override.thinking not in _THINKING_LEVELS:
                raise ValueError(f"阶段 {phase} 的 thinking 档非法")

    def effective(self, phase: str) -> AdapterConfig:
        """合成阶段覆盖后的生效配置（B-05：opening/bidding/respond/challenge）。"""
        override = self.phase_overrides.get(phase)
        if override is None:
            return self
        return replace(
            self,
            temperature=(
                override.temperature if override.temperature is not None else self.temperature
            ),
            thinking=override.thinking if override.thinking is not None else self.thinking,
            max_tokens=override.max_tokens if override.max_tokens is not None else self.max_tokens,
        )


def resolve_api_key(api_key_ref: str) -> str:
    """运行时从环境解析密钥；缺失即报错（密钥永不落盘，B-08）。"""
    if not api_key_ref.startswith("env:"):
        raise ValueError("api_key_ref 必须为 env:VAR 形态（B-08）")
    var = api_key_ref[4:]
    value = os.environ.get(var)
    if not value:
        raise RuntimeError(f"环境变量 {var} 未设置（api_key_ref={api_key_ref}，B-08）")
    return value


def load_player_config(path: Path) -> AdapterConfig:
    """装载一份玩家 TOML 配置（03 §7：每玩家一份，同名服务商可例化多玩家）。"""
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    player = raw.get("player", {})
    if not player:
        raise ValueError(f"{path}: 缺少 [player] 段（03 §7）")
    provider = str(player.get("provider", ""))
    model = str(player.get("model", ""))
    api_key_ref = str(player.get("api_key_ref", ""))
    base_url = str(player.get("base_url", "")) or default_base_url(provider)

    persona_raw = dict(raw.get("persona", {}))
    # 署名降级：persona.name 缺省取 [player].name，再缺省取配置文件名（03 §2 人格为可选维度）
    fallback_name = str(player.get("name", "")).strip() or path.stem
    persona = PersonaConfig(
        name=str(persona_raw.get("name", "")) or fallback_name,
        style=str(persona_raw.get("style", "")),
        trash_talk=int(persona_raw.get("trash_talk", 0)),
    )
    quote_raw = dict(raw.get("quote", {}))
    quote = QuoteConfig(
        enabled=bool(quote_raw.get("enabled", True)),
        language=str(quote_raw.get("language", "粤语")),
        trash_talk=int(quote_raw.get("trash_talk", 1)),
        style_template=str(quote_raw.get("style_template", "")),
    )
    overrides: dict[str, PhaseOverride] = {}
    for phase, values in dict(raw.get("phases", {})).items():
        values = dict(values)
        overrides[str(phase)] = PhaseOverride(
            temperature=_opt_float(values.get("temperature")),
            thinking=_opt_str(values.get("thinking")),
            max_tokens=_opt_int(values.get("max_tokens")),
        )
    known = {"provider", "model", "api_key_ref", "base_url"}
    extra = {k: v for k, v in player.items() if k not in known}
    return AdapterConfig(
        provider=provider,
        model=model,
        api_key_ref=api_key_ref,
        base_url=base_url,
        timeout_ms=int(player.get("timeout_ms", 30_000)),
        net_retries=int(player.get("net_retries", 3)),
        temperature=_opt_float(player.get("temperature")),
        top_p=_opt_float(player.get("top_p")),
        max_tokens=int(player.get("max_tokens", 1024)),
        thinking=str(player.get("thinking", "auto")),
        output_mode=str(player.get("output_mode", "json_mode")),
        self_check_retries=int(player.get("self_check_retries", 2)),
        context_presentation=str(player.get("context_presentation", "summary")),
        legal_actions_presentation=str(player.get("legal_actions_presentation", "constraints")),
        history_depth=int(player.get("history_depth", 10)),
        persona=persona,
        quote=quote,
        phase_overrides=overrides,
        match_token_budget=_opt_int(player.get("match_token_budget")),
        extra=extra,
    )


def default_base_url(provider: str) -> str:
    """各家官方 OpenAI 兼容端点默认值（型号 ID 走配置，端点亦可覆写）。"""
    defaults = {
        "deepseek": "https://api.deepseek.com",
        "glm": "https://open.bigmodel.cn/api/paas/v4",
        "mimo": "https://api.mimo.mi.com/v1",
        "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "doubao": "https://ark.cn-beijing.volces.com/api/v3",
        "minimax": "https://api.minimax.io/v1",
    }
    url = defaults.get(provider)
    if url is None:
        raise ValueError(f"未知 provider：{provider}（03 §3 初期六家）")
    return url


def _opt_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _opt_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)
