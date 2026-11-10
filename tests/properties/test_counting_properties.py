"""P1 属性测试：计数口径的穷举不变式（计划 §4.2 / P1 验收标准「计数单调」）。

穷举全部 252 种手牌多重集 × 全部面值 × 全部合法状态 × 关键配置组合。
"""

from __future__ import annotations

from dataclasses import replace
from itertools import combinations_with_replacement

from perudo.core.counting import count_table, player_contribution, total_count
from perudo.core.types import (
    ALL_FACES,
    CallState,
    Face,
    Hand,
    RuleConfig,
    ScatteredPolicy,
    StraightPolicy,
    ZhaiState,
)

#: 5 颗六面骰的全部多重集（C(6+5-1, 5) = 252）
HANDS: tuple[Hand, ...] = tuple(Hand(h) for h in combinations_with_replacement(ALL_FACES, 5))

#: 全部合法 CallState（2×2 中可达的三格；(FLY, True) 由构造器拒绝）
STATES: tuple[CallState, ...] = (
    CallState(ZhaiState.FLY, False),
    CallState(ZhaiState.DEAD, False),
    CallState(ZhaiState.DEAD, True),
)

#: 覆盖基线与各变体开关的配置组合
CONFIGS: tuple[RuleConfig, ...] = (
    RuleConfig(),
    replace(RuleConfig(), leopard_bonus=False),
    replace(RuleConfig(), all_ones_eight=True),
    replace(RuleConfig(), straight=StraightPolicy.COUNT_ZERO),
    replace(RuleConfig(), straight=StraightPolicy.NORMAL),
    replace(RuleConfig(), scattered=ScatteredPolicy.COUNT_ZERO),
    replace(RuleConfig(), scattered=ScatteredPolicy.NORMAL),
)

#: 单调性适用的配置：不含「计 0」变体 —— 顺色计 0（R-61①）会把凑成顺色的
#: 手牌贡献归零（如 1,3,3,4,5 → 换入 2 变成 12345），单调性在该变体下天然
#: 不成立，这是变体设计后果而非计数缺陷；「计 0」口径的正确性由 §13 对账
#: 与下方其余属性共同覆盖。
MONOTONE_CONFIGS: tuple[RuleConfig, ...] = (
    RuleConfig(),
    replace(RuleConfig(), leopard_bonus=False),
    replace(RuleConfig(), all_ones_eight=True),
    replace(RuleConfig(), straight=StraightPolicy.NORMAL),
    replace(RuleConfig(), scattered=ScatteredPolicy.NORMAL),
)


def supporting_faces(called: Face, state: CallState) -> frozenset[Face]:
    """当前状态下能支持被叫面值的骰面（R-37/R-38）。"""
    if state.zhai is ZhaiState.DEAD:
        return frozenset({called})
    if called is Face.ONE:
        return frozenset({Face.ONE})
    return frozenset({called, Face.ONE})


def test_count_monotone_under_supporting_replacement() -> None:
    """计数单调：把一颗不支持的骰子换成任一支持骰，贡献不减（计划 §4.2）。

    适用口径见 ``MONOTONE_CONFIGS`` 注释。
    """
    for cfg in MONOTONE_CONFIGS:
        for state in STATES:
            for called in ALL_FACES:
                supporting = supporting_faces(called, state)
                for hand in HANDS:
                    base = player_contribution(hand, called, state, cfg)
                    for i, face in enumerate(hand.dice):
                        if face in supporting:
                            continue
                        for s in supporting:
                            replaced = Hand((*hand.dice[:i], s, *hand.dice[i + 1 :]))
                            after = player_contribution(replaced, called, state, cfg)
                            assert after >= base, (cfg, state, called, hand.dice, i, s, base, after)


def test_fly_count_never_below_dead_count() -> None:
    """飞态计数 ≥ 1 死态计数（癞子只会加持、永不减损；D-02 字面口径下恒成立）。"""
    for cfg in CONFIGS:
        fly = CallState(ZhaiState.FLY, False)
        dead = CallState(ZhaiState.DEAD, False)
        for called in ALL_FACES:
            for hand in HANDS:
                assert player_contribution(hand, called, fly, cfg) >= player_contribution(
                    hand, called, dead, cfg
                )


def test_contribution_within_bounds() -> None:
    """贡献有界：基线 0..7（全骰封顶）；全红变体 0..8；无加成 0..5。"""
    for state in STATES:
        for called in ALL_FACES:
            for hand in HANDS:
                assert 0 <= player_contribution(hand, called, state, RuleConfig()) <= 7
                assert (
                    0
                    <= player_contribution(
                        hand, called, state, replace(RuleConfig(), all_ones_eight=True)
                    )
                    <= 8
                )
                assert (
                    0
                    <= player_contribution(
                        hand, called, state, replace(RuleConfig(), leopard_bonus=False)
                    )
                    <= 5
                )


def test_table_and_total_consistency() -> None:
    """全场 count = Σ逐玩家贡献，且逐玩家表键与手牌键一致（R-03：全员参与计数）。"""
    hands = {0: HANDS[0], 1: HANDS[100], 2: HANDS[251], 3: HANDS[7]}
    for cfg in CONFIGS:
        for state in STATES:
            for called in ALL_FACES:
                table = count_table(hands, called, state, cfg)
                assert set(table) == set(hands)
                for seat, hand in hands.items():
                    assert table[seat] == player_contribution(hand, called, state, cfg)
                assert total_count(hands, called, state, cfg) == sum(table.values())
