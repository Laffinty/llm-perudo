"""GLM 适配器（03 §5.3，M4a 首批）。

针对性设计：Flash/FlashX 快轨（批量默认）、5.3 系 reasoning_effort（强制
思考，03 §5.7.1 核对）、full_presentation 全量呈现（1M 上下文放开）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from perudo.adapters.sdk.tuning import GLM_TUNING, ProviderTuning

if TYPE_CHECKING:
    from perudo.adapters.sdk.config import AdapterConfig
    from perudo.adapters.sdk.player import LLMPlayer
    from perudo.adapters.sdk.transport import Transport

__all__ = ["GLM_TUNING", "get_tuning", "make_player"]


def get_tuning() -> ProviderTuning:
    return GLM_TUNING


def make_player(
    config: AdapterConfig,
    transport: Transport | None = None,
    *,
    api_key: str | None = None,
    backoff_base: float = 0.5,
) -> LLMPlayer:
    """工厂：Tuning 绑定 + LLMPlayer 组装。"""
    from perudo.adapters.sdk.player import LLMPlayer

    return LLMPlayer(
        config,
        transport,
        GLM_TUNING,
        api_key=api_key,
        backoff_base=backoff_base,
    )
