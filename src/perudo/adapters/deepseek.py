"""DeepSeek 适配器（03 §5.1，M4a 首批）。

针对性设计：温度矩阵（仅非思考档生效，03 §5.7.1 核对）、思考分层直通
（thinking.type + reasoning_effort）、退役名守门（deepseek-chat/reasoner）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from perudo.adapters.sdk.tuning import DEEPSEEK_TUNING, ProviderTuning

if TYPE_CHECKING:
    from perudo.adapters.sdk.config import AdapterConfig
    from perudo.adapters.sdk.player import LLMPlayer
    from perudo.adapters.sdk.transport import Transport

__all__ = ["DEEPSEEK_TUNING", "get_tuning", "make_player"]


def get_tuning() -> ProviderTuning:
    return DEEPSEEK_TUNING


def make_player(
    config: AdapterConfig,
    transport: Transport | None = None,
    *,
    api_key: str | None = None,
    backoff_base: float = 0.5,
) -> LLMPlayer:
    """工厂：Tuning 绑定 + LLMPlayer 组装（型号 ID 全走配置，N3-04）。"""
    from perudo.adapters.sdk.player import LLMPlayer

    return LLMPlayer(
        config,
        transport,
        DEEPSEEK_TUNING,
        api_key=api_key,
        backoff_base=backoff_base,
    )
