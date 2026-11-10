"""P1 属性测试：判定恒等式与结算分解一致性（计划 §4.2「结算恒等式」、R-45/R-52）。

对 StakeContext 的全语义空间做穷举，断言：
1. ``judge`` 与 `count ≥ X` 恒等（R-45）；
2. ``settle_stake`` 的 multiplier = breakdown 因子之积、codes 与倍数恒等（投降按 R-52 减半/保底）；
3. 非法 StakeContext 组合一律 ValueError；
4. 陪饮映射符合 D-05 登记约定（计划 §8）。
"""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from itertools import product

from perudo.core.settlement import (
    decide_bid_stood,
    drink_along_pick,
    is_total_darkness,
    judge,
    settle_stake,
)
from perudo.core.types import (
    ALL_FACES,
    Bid,
    ChallengeKind,
    Direction,
    Face,
    Hand,
    LoserSide,
    RuleConfig,
    StakeContext,
)

BASES: tuple[Fraction, ...] = (Fraction(1), Fraction(2), Fraction(4), Fraction(8))
BID_COUNTS: tuple[int, ...] = (2, 4, 8)

FLAG_SETS: tuple[dict[str, bool], ...] = tuple(
    {
        "half_double": half,
        "jump_fail_double": jump,
        "leopard_double": leopard,
        "surrender_floor_one": floor_one,
    }
    for half, jump, leopard, floor_one in product((False, True), repeat=4)
)


def make_stake(
    side: LoserSide,
    chain: ChallengeKind,
    bid_stood: bool | None,
    base: Fraction,
    bid_count: int,
    count: int | None,
    holds_leopard: bool,
) -> StakeContext:
    return StakeContext(
        loser=0,
        side=side,
        chain=chain,
        base_multiplier=base,
        bid=Bid(bid_count, Face.THREE),
        bid_stood=bid_stood,
        count=count,
        loser_holds_leopard=holds_leopard,
    )


def _product_of_breakdown(entry: object) -> Fraction:
    factor = Fraction(1)
    for _, value in entry.breakdown:  # type: ignore[attr-defined]
        factor *= value
    return factor


def test_judge_is_count_ge_bid() -> None:
    """结算恒等式：胜负 ⇔ count ≥ X（R-45，计划 §4.2）。"""
    for x in range(1, 31):
        for count in range(0, 31):
            assert judge(count, Bid(x, Face.THREE)) == (count >= x)


def test_settle_stake_breakdown_product_equals_multiplier() -> None:
    """倍数明细恒等：multiplier = Π breakdown 因子；非投降 codes = int(multiplier)。"""
    for chain, base, bid_count, flags in product(
        (ChallengeKind.OPEN, ChallengeKind.JUMP), BASES, BID_COUNTS, FLAG_SETS
    ):
        cfg = replace(RuleConfig(), **flags)
        # 杀者输（成立）——R-55（开杀链）/ R-56（跳杀链）
        stake = make_stake(LoserSide.CHALLENGER, chain, True, base, bid_count, bid_count, False)
        entry = settle_stake(stake, cfg)
        assert _product_of_breakdown(entry) == entry.multiplier
        assert entry.codes == int(entry.multiplier)
        expected = base
        if chain is ChallengeKind.OPEN and flags["half_double"]:
            expected *= 2  # R-55 超半（修辞性加倍，不翻转判定 —— D-04）
        if chain is ChallengeKind.JUMP and flags["jump_fail_double"]:
            expected *= 2  # R-56 跳杀失败
        assert entry.multiplier == expected, (chain, base, flags, entry.multiplier, expected)

        # 被杀者输（不成立，开盅）——R-54（开杀链）/ R-53（两链通用）
        for count in (0, max(0, bid_count // 2 - 1), bid_count // 2, bid_count // 2 + 1):
            for holds in (False, True):
                stake = make_stake(
                    LoserSide.CHALLENGED, chain, False, base, bid_count, count, holds
                )
                entry = settle_stake(stake, cfg)
                assert _product_of_breakdown(entry) == entry.multiplier
                assert entry.codes == int(entry.multiplier)
                expected = base
                if chain is ChallengeKind.OPEN and flags["half_double"] and count * 2 < bid_count:
                    expected *= 2  # R-54 不够一半（严格小于；count 恰为 X/2 不加倍）
                if holds and flags["leopard_double"]:
                    expected *= 2  # R-53 豹子加倍（两链通用，D-04）
                assert entry.multiplier == expected, (chain, base, count, flags, entry.multiplier)


def test_settle_stake_surrender_halving_and_floor() -> None:
    """投降（R-52）：当前惩罚减半；保底 1 码按 §12 第 12 项开关；不吃进阶加倍（D-04 第 5 条）。"""
    for base, flags in product(BASES, FLAG_SETS):
        cfg = replace(RuleConfig(), **flags)
        stake = make_stake(LoserSide.CHALLENGED, ChallengeKind.OPEN, None, base, 4, None, False)
        entry = settle_stake(stake, cfg)
        assert entry.multiplier == base / 2  # 仅减半，无任何进阶因子
        halved_floor = (base / 2).numerator // (base / 2).denominator  # floor(½ × base)
        if flags["surrender_floor_one"]:
            assert entry.codes == max(1, halved_floor)
        else:
            assert entry.codes == halved_floor


def test_settle_stake_rejects_inconsistent_contexts() -> None:
    """非法 StakeContext 组合一律 ValueError（side/bid_stood/chain/count 一致性）。"""
    cfg = RuleConfig()
    bad_cases = (
        make_stake(LoserSide.CHALLENGER, ChallengeKind.OPEN, False, Fraction(1), 4, 1, False),
        make_stake(LoserSide.CHALLENGER, ChallengeKind.JUMP, None, Fraction(1), 4, None, False),
        make_stake(LoserSide.CHALLENGED, ChallengeKind.OPEN, True, Fraction(1), 4, 4, False),
        StakeContext(
            loser=0,
            side=LoserSide.CHALLENGER,
            chain=ChallengeKind.MULTI,  # 编排层组装时归 OPEN（D-04 裁决第 2 条）
            base_multiplier=Fraction(1),
            bid=Bid(4, Face.THREE),
            bid_stood=True,
            count=4,
        ),
        StakeContext(
            loser=0,
            side=LoserSide.CHALLENGER,
            chain=ChallengeKind.SWEEP,
            base_multiplier=Fraction(1),
            bid=Bid(4, Face.THREE),
            bid_stood=True,
            count=4,
        ),
        StakeContext(  # bid_stood=None 但 count 非 None
            loser=0,
            side=LoserSide.CHALLENGED,
            chain=ChallengeKind.OPEN,
            base_multiplier=Fraction(1),
            bid=Bid(4, Face.THREE),
            bid_stood=None,
            count=1,
        ),
    )
    for stake in bad_cases:
        try:
            settle_stake(stake, cfg)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝的 StakeContext 未拒绝：{stake}")


def test_drink_along_follows_registered_mapping() -> None:
    """陪饮映射（R-57 / 计划 §8 D-05 登记约定）：和 s → 沿方向第 ((s-1) mod N)+1 位。"""
    rolls: tuple[tuple[Face, ...], ...] = tuple((f,) for f in ALL_FACES) + tuple(
        (a, b) for a in ALL_FACES for b in ALL_FACES
    )
    cfg_clockwise = RuleConfig()
    cfg_counter = replace(RuleConfig(), direction=Direction.COUNTER_CLOCKWISE)
    for player_count in range(2, 13):
        for loser in range(player_count):
            for roll in rolls:
                s = sum(int(f) for f in roll)
                offset = (s - 1) % player_count
                clockwise = drink_along_pick(loser, roll, player_count, cfg_clockwise)
                assert clockwise.buddy == (loser + offset) % player_count
                assert clockwise.self_hit == (clockwise.buddy == loser)
                counter = drink_along_pick(loser, roll, player_count, cfg_counter)
                assert counter.buddy == (loser - offset) % player_count
                assert counter.self_hit == (counter.buddy == loser)


def test_drink_along_rejects_bad_rolls() -> None:
    """陪饮骰只能是 1 颗大骰或 2 颗标准骰（R-57），越界 ValueError。"""
    for bad in ((), (Face.ONE, Face.TWO, Face.THREE)):
        try:
            drink_along_pick(0, bad, 4, RuleConfig())
        except ValueError:
            continue
        raise AssertionError(f"应拒绝的陪饮骰组未拒绝：{bad}")


def test_darkness_override_only_when_no_literal_face() -> None:
    """天黑黑（R-63）：仅在全场无真 Y 骰时覆盖 R-45；有真 Y 时回归常规判定。"""
    hands_no_y = {
        0: Hand((Face.ONE,) * 5),
        1: Hand((Face.TWO, Face.TWO, Face.THREE, Face.ONE, Face.FIVE)),
    }
    hands_with_y = {0: Hand((Face.FOUR, Face.FOUR, Face.ONE, Face.ONE, Face.SIX))}
    bid = Bid(6, Face.FOUR)
    cfg_on = replace(RuleConfig(), darkness=True)
    cfg_off = RuleConfig()
    assert is_total_darkness(hands_no_y, Face.FOUR) is True
    assert is_total_darkness(hands_with_y, Face.FOUR) is False
    # 有 1 无 4：count(4) 按 FLY 口径为 3 < 6 —— 天黑黑把结果钉在成立方向（开骰者输）
    assert decide_bid_stood(bid, 3, hands_no_y, cfg_on) is True
    assert decide_bid_stood(bid, 3, hands_no_y, cfg_off) is False
    # 有真 4：天黑黑不改变方向
    assert decide_bid_stood(bid, 3, hands_with_y, cfg_on) is False
    assert decide_bid_stood(bid, 7, hands_with_y, cfg_on) is True
