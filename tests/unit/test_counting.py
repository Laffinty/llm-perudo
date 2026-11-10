"""P1 单元测试：计数口径（域 counting，矩阵 §0.3）。

覆盖规则：R-37 ~ R-44、R-62、R-66；含 01 §8.4 计数示例逐行与 D-02 字面计数红线。
穷举不变式见 tests/properties/test_counting_properties.py。
"""

from __future__ import annotations

from dataclasses import replace

from perudo.core.counting import player_contribution, total_count
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

CFG = RuleConfig()
FLY = CallState(ZhaiState.FLY, False)
DEAD = CallState(ZhaiState.DEAD, False)


def H(*faces: int) -> Hand:
    return Hand(tuple(Face(f) for f in faces))


def test_r37_fly_count_includes_wilds() -> None:
    """R-37：飞态 called∈2..6 计入 1 作癞子；called=1 只计真 1（D-02 字面）。"""
    hand = H(4, 4, 4, 2, 1)
    assert player_contribution(hand, Face.FOUR, FLY, CFG) == 4  # 3 个 4 + 1 癞子
    hand_ones = H(1, 1, 1, 5, 5)
    assert player_contribution(hand_ones, Face.ONE, FLY, CFG) == 3  # D-02：只计真 1
    assert player_contribution(hand_ones, Face.FIVE, FLY, CFG) == 6  # 2 真 5 + 3 癞子 → 围骰


def test_r38_dead_count_literal_only() -> None:
    """R-38：1 死状态一律按面值计，对 called ∈ 1..6 一致。"""
    hand = H(1, 1, 3, 5, 6)
    for face in ALL_FACES:
        expected = hand.dice.count(face)
        assert player_contribution(hand, face, DEAD, CFG) == expected
    assert player_contribution(H(2, 2, 2, 2, 2), Face.TWO, DEAD, CFG) == 5  # R-41：只计 5


def test_r39_leopard_bonus_six() -> None:
    """R-39：借癞子凑成同一面值（非本来全同）→ 6。"""
    assert player_contribution(H(4, 4, 4, 4, 1), Face.FOUR, FLY, CFG) == 6  # 4Y + 1 癞子
    assert player_contribution(H(4, 4, 4, 1, 1), Face.FOUR, FLY, CFG) == 6  # 3Y + 2 癞子
    assert player_contribution(H(4, 1, 1, 1, 1), Face.FOUR, FLY, CFG) == 6  # 1Y + 4 癞子
    assert player_contribution(H(4, 4, 3, 2, 1), Face.FOUR, FLY, CFG) == 3  # 不成豹子：2Y+1 癞子


def test_r40_pure_leopard_bonus_seven() -> None:
    """R-40：本来 5 颗同面值 → 7；对其他面值只按癞子/面值计（R-42）。"""
    five_fours = H(4, 4, 4, 4, 4)
    assert player_contribution(five_fours, Face.FOUR, FLY, CFG) == 7
    assert player_contribution(five_fours, Face.FIVE, FLY, CFG) == 0  # 无癞子不跨面值


def test_r41_bonus_only_in_fly_state() -> None:
    """R-41：加成仅飞态生效；1 死状态 5 颗相同只按面值 5。"""
    assert player_contribution(H(5, 5, 5, 5, 5), Face.FIVE, DEAD, CFG) == 5
    assert player_contribution(H(1, 1, 1, 1, 1), Face.ONE, DEAD, CFG) == 5


def test_r42_bonus_only_for_called_face() -> None:
    """R-42：加成只作用于被叫面值（01 §8.4 示例行）。"""
    hand = H(4, 4, 4, 4, 1)
    assert player_contribution(hand, Face.FOUR, FLY, CFG) == 6  # 围骰
    assert player_contribution(hand, Face.SIX, FLY, CFG) == 1  # 那个 1 只是癞子
    assert player_contribution(hand, Face.ONE, FLY, CFG) == 1  # D-02 字面


def test_r43_five_ones_count_seven_for_any_face() -> None:
    """R-43：全骰的 5 个 1 在飞态对任意被叫面值贡献 7。"""
    hand = H(1, 1, 1, 1, 1)
    for face in ALL_FACES:
        assert player_contribution(hand, face, FLY, CFG) == 7


def test_r44_guard_baseline_and_switch_off() -> None:
    """R-44：A 类守护——基线默认下加成存在（变体「有骰计骰」不被触发）；
    开关层——leopard_bonus=False 时按无加成口径（§12 第 5 项）。"""
    leopard = H(4, 4, 4, 4, 1)
    pure = H(4, 4, 4, 4, 4)
    ones = H(1, 1, 1, 1, 1)
    # 守护：默认配置加成生效（若默认翻转或删加成，本断言红）
    assert player_contribution(leopard, Face.FOUR, FLY, RuleConfig()) == 6
    assert player_contribution(pure, Face.FOUR, FLY, RuleConfig()) == 7
    assert player_contribution(ones, Face.FOUR, FLY, RuleConfig()) == 7
    # 开关：R-44 变体口径
    off = replace(RuleConfig(), leopard_bonus=False)
    assert player_contribution(leopard, Face.FOUR, FLY, off) == 5
    assert player_contribution(pure, Face.FOUR, FLY, off) == 5
    assert player_contribution(ones, Face.FOUR, FLY, off) == 5


def test_r62_all_ones_eight_variant_fly_only() -> None:
    """R-62：「全红」8 个仅飞态；基线 7；1 死状态恒 5。"""
    ones = H(1, 1, 1, 1, 1)
    assert player_contribution(ones, Face.ONE, FLY, replace(CFG, all_ones_eight=True)) == 8
    assert player_contribution(ones, Face.ONE, FLY, CFG) == 7
    assert player_contribution(ones, Face.ONE, DEAD, replace(CFG, all_ones_eight=True)) == 5


def test_r66_true_same_vs_wild_assembled() -> None:
    """R-66：真同面值 +2（7）、靠癞子凑成 +1（6）——"斋的五个 2"指真同不靠癞子。"""
    assert player_contribution(H(2, 2, 2, 2, 1), Face.TWO, FLY, CFG) == 6  # 非斋（凑成）
    assert player_contribution(H(2, 2, 2, 2, 2), Face.TWO, FLY, CFG) == 7  # 斋的（真同）


def test_r61_and_r09_variant_count_zero_switches() -> None:
    """R-61/R-09①：「顺色计 0」「散骰计 0」开关两态——打开时贡献归 0，关闭时照常。"""
    straight = H(1, 2, 3, 4, 5)
    straight_zero = replace(CFG, straight=StraightPolicy.COUNT_ZERO)
    assert player_contribution(straight, Face.THREE, FLY, straight_zero) == 0
    assert (
        player_contribution(straight, Face.THREE, FLY, replace(CFG, straight=StraightPolicy.NORMAL))
        == 2
    )
    scattered = H(1, 3, 5, 2, 6)
    scattered_zero = replace(CFG, scattered=ScatteredPolicy.COUNT_ZERO)
    assert player_contribution(scattered, Face.THREE, FLY, scattered_zero) == 0
    assert (
        player_contribution(
            scattered, Face.THREE, FLY, replace(CFG, scattered=ScatteredPolicy.NORMAL)
        )
        == 2
    )


def test_8_4_counting_examples_reconciliation() -> None:
    """01 §8.4 计数示例五行逐行对账（飞状态，被叫点数 4）。"""
    assert player_contribution(H(4, 4, 4, 4, 1), Face.FOUR, FLY, CFG) == 6
    assert player_contribution(H(4, 4, 4, 4, 4), Face.FOUR, FLY, CFG) == 7
    assert player_contribution(H(1, 1, 1, 1, 1), Face.FOUR, FLY, CFG) == 7
    assert player_contribution(H(4, 4, 4, 2, 1), Face.FOUR, FLY, CFG) == 4
    assert player_contribution(H(2, 3, 5, 6, 1), Face.FOUR, FLY, CFG) == 1


def test_total_count_sums_all_players() -> None:
    """R-03 关联：全场 count = Σ 贡献（全员骰子参与结算计数）。"""
    hands = {0: H(4, 4, 4, 1, 2), 1: H(6, 6, 3, 5, 1), 2: H(5, 5, 5, 5, 1), 3: H(1, 1, 3, 5, 6)}
    assert total_count(hands, Face.FIVE, FLY, CFG) == 12  # 01 §13.1
