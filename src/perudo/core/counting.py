"""计数判定（L0，02 §3.1 三件套之一）。

覆盖规则：R-03、R-37 ~ R-44、R-62、R-66；口径红线：D-02 字面计数
（02 §3.2 红线三 —— 飞态下 count(1) = 骰面 1 的个数，不按"任意面值取最大"计数，
01 明确警告不得"顺手优化"）。

硬约束：纯函数、零 IO、零随机、零第三方依赖（02 A-19 / A-10 / A-14）。
"""

from __future__ import annotations

from collections.abc import Mapping

from perudo.core.types import (
    CallState,
    Face,
    Hand,
    RuleConfig,
    ScatteredPolicy,
    StraightPolicy,
    ZhaiState,
)

__all__ = ["count_table", "player_contribution", "total_count"]


def _is_straight(dice: tuple[Face, ...]) -> bool:
    """顺色：5 颗点数互不相同且连续，仅 12345 / 23456（R-60）。"""
    values = {int(f) for f in dice}
    return values == {1, 2, 3, 4, 5} or values == {2, 3, 4, 5, 6}


def player_contribution(hand: Hand, called: Face, state: CallState, cfg: RuleConfig) -> int:
    """单玩家对被叫面值 ``called`` 的贡献（R-37/R-38 基础口径 + R-39~R-44 加成）。

    判定顺序：顺色变体（R-61）→ 散骰变体（R-09①）→ 1 死状态（R-38）→
    飞状态（R-37 + 围骰/全骰 R-39~R-43、R-66）。
    """
    dice = hand.dice
    # 局前变体：顺色计 0（R-61①）/ 散骰计 0（R-09 变体①）
    if cfg.straight is StraightPolicy.COUNT_ZERO and _is_straight(dice):
        return 0
    if cfg.scattered is ScatteredPolicy.COUNT_ZERO and len(set(dice)) == 5:
        return 0
    # 1 死状态（斋 / 过 1）：一律按面值计，无任何加成（R-38、R-41）
    if state.zhai is ZhaiState.DEAD:
        return sum(1 for d in dice if d == called)
    # 飞状态（R-37）
    n_called = sum(1 for d in dice if d == called)
    n_ones = sum(1 for d in dice if d == Face.ONE)
    if called == Face.ONE:
        # D-02 字面计数红线：count(1) = 骰面 1 的个数（计划 §4.1 变异 V-3）
        if n_called == 5 and cfg.leopard_bonus:
            # 5 个 1 本来全同 → 全骰 7（R-40）；「全红」变体 → 8（R-62，仅飞态）
            return 8 if cfg.all_ones_eight else 7
        return n_called
    if n_called == 5:
        # 本来 5 颗同面值 → 全骰 7（R-40/R-66：真同 +2）
        return 7 if cfg.leopard_bonus else 5
    if n_ones == 5:
        # 5 个 1 在飞态对任意被叫面值贡献 7（R-43）
        return 7 if cfg.leopard_bonus else 5
    if n_called + n_ones >= 5:
        # 借 1 作癞子凑成同一面值（非本来全同）→ 围骰 6（R-39/R-66：凑成 +1）
        return 6 if cfg.leopard_bonus else n_called + n_ones
    return n_called + n_ones  # R-37 基础口径（癞子计入被叫面值）


def count_table(
    hands: Mapping[int, Hand], called: Face, state: CallState, cfg: RuleConfig
) -> dict[int, int]:
    """逐玩家贡献表（R-03：所有玩家的骰子都参与结算计数）。"""
    return {seat: player_contribution(hand, called, state, cfg) for seat, hand in hands.items()}


def total_count(hands: Mapping[int, Hand], called: Face, state: CallState, cfg: RuleConfig) -> int:
    """全场 ``count(Y)`` = Σ 逐玩家贡献（R-03）。"""
    return sum(count_table(hands, called, state, cfg).values())
