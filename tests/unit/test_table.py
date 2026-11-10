"""P1 单元测试：人数 / 道具 / 顺色 / 重摇（域 table，矩阵 §0.3）。

覆盖规则：R-01 ~ R-10、R-60、R-61、R-65。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from itertools import combinations_with_replacement

import pytest

from perudo.core.legality import needs_reshake, next_seat, previous_seat, reroll_verdict_failed
from perudo.core.types import (
    ALL_FACES,
    BidCapPolicy,
    Direction,
    Face,
    Hand,
    RerollReason,
    RuleConfig,
    ScatteredPolicy,
    StraightPolicy,
    total_dice,
    validate_player_count,
)

HANDS: tuple[Hand, ...] = tuple(Hand(h) for h in combinations_with_replacement(ALL_FACES, 5))


def test_r01_hand_is_exactly_five_dice() -> None:
    """R-01：一手恰为 5 颗六面骰；越界手牌在构造时被拒绝。"""
    hand = Hand((Face.ONE, Face.TWO, Face.THREE, Face.FOUR, Face.FIVE))
    assert len(hand.dice) == 5
    with pytest.raises(ValueError):
        Hand((Face.ONE, Face.TWO, Face.THREE, Face.FOUR))
    with pytest.raises(ValueError):
        Hand((Face.ONE,) * 6)


def test_r02_player_count_supported_range() -> None:
    """R-02：人数允许 2–12，基线上限 6（§12 第 16 项）；越界被拒。"""
    cfg = RuleConfig()
    for n in (2, 3, 4, 5, 6):
        validate_player_count(n, cfg)
    for n in (0, 1, 7, 13):
        with pytest.raises(ValueError):
            validate_player_count(n, cfg)
    wide = replace(cfg, player_cap=12)
    for n in (7, 12):
        validate_player_count(n, wide)
    with pytest.raises(ValueError):
        validate_player_count(13, wide)


def test_r03_total_dice_is_five_times_n() -> None:
    """R-03：全场总骰数 = 5N。"""
    assert total_dice(4) == 20
    for n in range(2, 13):
        assert total_dice(n) == 5 * n


def test_r04_clockwise_baseline_and_seat_geometry() -> None:
    """R-04：基线行动方向为顺时针；上/下家沿方向计算。"""
    cfg = RuleConfig()
    assert cfg.direction is Direction.CLOCKWISE
    assert previous_seat(0, 4, cfg) == 3
    assert next_seat(3, 4, cfg) == 0
    ccw = replace(cfg, direction=Direction.COUNTER_CLOCKWISE)
    assert previous_seat(0, 4, ccw) == 1
    assert next_seat(0, 4, ccw) == 3


def test_r06_rule_config_defaults_match_section12() -> None:
    """R-06：RuleConfig 默认值 = 01 §12 十八项的基线默认。"""
    cfg = RuleConfig()
    assert cfg.stake_label == "1 份"  # ①
    assert cfg.straight is StraightPolicy.RESHAKE  # ②③
    assert cfg.scattered is ScatteredPolicy.RESHAKE  # ④
    assert cfg.leopard_bonus is True  # ⑤
    assert cfg.all_ones_eight is False  # ⑥
    assert cfg.leopard_double is True  # ⑦
    assert cfg.half_double is True  # ⑧
    assert cfg.jump_fail_double is True  # ⑨
    assert cfg.counter_on_open is False  # ⑩
    assert cfg.multi_win_double_threshold == 3  # ⑪
    assert cfg.surrender_floor_one is True  # ⑫
    assert cfg.darkness is False  # ⑬
    assert cfg.drink_along is False  # ⑭
    assert cfg.direction is Direction.CLOCKWISE  # ⑮
    assert cfg.player_cap == 6  # ⑯
    assert cfg.bid_cap is BidCapPolicy.FIVE_N  # ⑰
    assert cfg.reroll_limit == 3  # ⑱


def test_r07_hand_frozen_and_private_by_contract() -> None:
    """R-07：手牌不可变；"只允许自己查看"由 P2 视图纪律落实（02 §2.1）。"""
    hand = Hand((Face.ONE,) * 4 + (Face.TWO,))
    with pytest.raises(FrozenInstanceError):
        hand.dice = (Face.ONE,) * 5  # type: ignore[misc]


def test_call_state_invariant_two_by_two() -> None:
    """02 §3.2 红线一：2×2 状态模型——(FLY, True) 非法组合在构造时被拒。"""
    from perudo.core.types import CallState
    from perudo.core.types import ZhaiState as ZS

    CallState(ZS.FLY, False)
    CallState(ZS.DEAD, False)
    CallState(ZS.DEAD, True)
    with pytest.raises(ValueError):
        CallState(ZS.FLY, True)


def test_r08_stacked_never_representable_in_digital_table() -> None:
    """R-08：叠骰在数字桌面不可表示，规则位保留（02 §2.4.1）——穷举守护。"""
    cfg = RuleConfig()
    for hand in HANDS:
        assert needs_reshake(hand, cfg) is not RerollReason.STACKED


def test_r09_scattered_must_reshake_with_variants() -> None:
    """R-09：基线散骰必重摇；「计 0 / 照常计」变体不触发重摇。"""
    cfg = RuleConfig()
    assert needs_reshake(Hand((Face.ONE, Face.TWO, Face.THREE, Face.FOUR, Face.SIX)), cfg) is (
        RerollReason.SCATTERED
    )
    assert needs_reshake(Hand((Face.ONE, Face.ONE, Face.TWO, Face.THREE, Face.FOUR)), cfg) is None
    zero = replace(cfg, scattered=ScatteredPolicy.COUNT_ZERO)
    normal = replace(cfg, scattered=ScatteredPolicy.NORMAL)
    scattered = Hand((Face.ONE, Face.TWO, Face.THREE, Face.FOUR, Face.SIX))
    assert needs_reshake(scattered, zero) is None
    assert needs_reshake(scattered, normal) is None


def test_r10_reshake_check_is_public_idempotent_verification() -> None:
    """R-10：验骰即自动校验（02 §2.4.1）——判定为公开幂等纯函数。"""
    cfg = RuleConfig()
    hand = Hand((Face.ONE, Face.TWO, Face.THREE, Face.FOUR, Face.SIX))
    assert needs_reshake(hand, cfg) == needs_reshake(hand, cfg)


def test_r60_straight_is_scattered_special_case() -> None:
    """R-60：顺色（12345/23456）是散骰特例，基线必重摇且优先报告顺色。"""
    cfg = RuleConfig()
    assert needs_reshake(Hand((Face.ONE, Face.TWO, Face.THREE, Face.FOUR, Face.FIVE)), cfg) is (
        RerollReason.STRAIGHT
    )
    assert needs_reshake(Hand((Face.TWO, Face.THREE, Face.FOUR, Face.FIVE, Face.SIX)), cfg) is (
        RerollReason.STRAIGHT
    )
    assert needs_reshake(Hand((Face.ONE, Face.TWO, Face.THREE, Face.FOUR, Face.SIX)), cfg) is (
        RerollReason.SCATTERED
    )


def test_r61_straight_policy_variants_do_not_reshake() -> None:
    """R-61：「顺色不重摇」两变体（计 0 / 照常计）下不触发重摇（计数见 test_counting）。

    散骰仍按基线必重摇时，顺色手牌（也是散骰，R-60）会被散骰口径拦下重摇——
    顺色豁免只在散骰同样不重摇的桌面上产生实效，两开关独立组合。
    """
    straight = Hand((Face.ONE, Face.TWO, Face.THREE, Face.FOUR, Face.FIVE))
    for policy in (StraightPolicy.COUNT_ZERO, StraightPolicy.NORMAL):
        for scattered in (ScatteredPolicy.COUNT_ZERO, ScatteredPolicy.NORMAL):
            cfg = replace(RuleConfig(), straight=policy, scattered=scattered)
            assert needs_reshake(straight, cfg) is None
    # 散骰基线必重摇时：顺色豁免不生效，按散骰拦截（顺色是散骰的一种，R-60）
    cfg = replace(RuleConfig(), straight=StraightPolicy.COUNT_ZERO)
    assert needs_reshake(straight, cfg) is RerollReason.SCATTERED


def test_r65_reroll_limit_variants() -> None:
    """R-65：重摇最多 3 次，第 4 次仍不合规判负；变体可放宽/收紧/关闭。"""
    cfg = RuleConfig()
    assert reroll_verdict_failed(3, cfg) is False
    assert reroll_verdict_failed(4, cfg) is True
    assert reroll_verdict_failed(99, replace(cfg, reroll_limit=None)) is False
    assert reroll_verdict_failed(2, replace(cfg, reroll_limit=1)) is True
