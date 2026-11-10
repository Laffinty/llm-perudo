"""首叫玩家确定（L0，R-05 + 02 A-05）。

R-05：每局由上一局的输家先起叫；首局由房主指定或随机（随机在引擎层，
本模块保持零随机）。A-05（02 决策登记）：一局多输家时，下局由罚码最多者
起叫，并列按座位方向取先。
"""

from __future__ import annotations

from collections.abc import Mapping

from perudo.core.types import Direction, RuleConfig

__all__ = ["opening_caller"]


def opening_caller(loser_codes: Mapping[int, int], player_count: int, cfg: RuleConfig) -> int:
    """确定下一局的首叫玩家（R-05 + A-05）。

    ``loser_codes`` 为上一局各输家的 ``{座位: 码数}``，必须非空（R-05：上一局
    必有输家）。多输家取罚码最多者；并列时沿 ``cfg.direction`` 从座位 0 起环行，
    取最先遇到的并列者（A-05"顺时针取先"的方向感知实现约定）。
    """
    if not loser_codes:
        raise ValueError("上一局必有输家（R-05），loser_codes 不得为空")
    max_codes = max(loser_codes.values())
    tied = {seat for seat, codes in loser_codes.items() if codes == max_codes}
    seat = 0
    for _ in range(player_count):
        if seat in tied:
            return seat
        if cfg.direction is Direction.CLOCKWISE:
            seat = (seat + 1) % player_count
        else:
            seat = (seat - 1) % player_count
    raise AssertionError("并列输家必在座位环上（不可达）")
