"""minimax 适配器（03 §5 / 03 §5.7.1 核对口径，M4b）。

Minimax 针对性设计见设计稿 §5 对应小节；Tuning 在 `sdk.tuning`（B-03 差异点收口）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from perudo.adapters.sdk.tuning import get_tuning_by_provider

if TYPE_CHECKING:
    from perudo.adapters.sdk.config import AdapterConfig
    from perudo.adapters.sdk.player import LLMPlayer
    from perudo.adapters.sdk.transport import Transport

__all__ = ["make_player"]


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
        get_tuning_by_provider("minimax"),
        api_key=api_key,
        backoff_base=backoff_base,
    )
