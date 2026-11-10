"""P1 属性测试：叫骰合法性的自洽与完备（计划 §4.2「合法性自洽」、02 §3.1）。

对全部合法状态 × 候选叫法 × 候选叫骰的组合做穷举，断言：
1. 每个非法判定 reason 非空（02 §3.1：原因同时是纠错依据）；
2. 合法性判定与独立规约式（R-17/R-18/R-20/R-21/R-23 + R-64）逐组合一致；
3. 合法动作应用后状态转移正确、``ones_called`` 不可逆（R-22）。
"""

from __future__ import annotations

from itertools import product

from perudo.core.legality import (
    apply_bid,
    bid_legal,
    face_beats,
    min_opening_bid,
    next_seat,
    opening_legal,
    previous_seat,
)
from perudo.core.types import (
    ALL_FACES,
    Bid,
    BidAction,
    BidKind,
    CallState,
    Face,
    LegalityVerdict,
    RuleConfig,
    ZhaiState,
)

STATES: tuple[CallState, ...] = (
    CallState(ZhaiState.FLY, False),
    CallState(ZhaiState.DEAD, False),
    CallState(ZhaiState.DEAD, True),
)

#: 现叫数量覆盖：起叫下限附近、中段、逼近 5N 上限（N=4 ⇒ 上限 20）
CURRENT_COUNTS: tuple[int, ...] = (2, 4, 6, 9, 18, 20)


#: 候选数量：现叫的 -1/0/+1、翻倍前后、上限附近
def candidate_counts(x0: int) -> tuple[int, ...]:
    return (
        max(1, x0 - 1),
        x0,
        x0 + 1,
        max(1, 2 * x0 - 1),
        2 * x0,
        2 * x0 + 1,
        19,
        20,
        21,
    )


def reference_normal_legal(x1: int, y1: int, x0: int, y0: int, state: CallState) -> bool:
    """常规接叫的独立规约式（R-17/R-18 + R-64，比较用生效前状态序）。"""
    if x1 > 20:
        return False
    if x1 > x0:
        return True
    return x1 == x0 and face_beats(y1, y0, state.zhai)


def reference_zhai_legal(x1: int, x0: int, state: CallState) -> bool:
    """转斋规约式（R-20 + R-64）：仅 FLY 态，X' ≥ X0，点数任意。"""
    return state.zhai is ZhaiState.FLY and x1 >= x0 and x1 <= 20


def reference_fei_legal(x1: int, x0: int, state: CallState) -> bool:
    """飞斋规约式（R-21/R-23 + R-64）：仅 DEAD 未过 1 态，X' ≥ 2×X0。"""
    return state.zhai is ZhaiState.DEAD and not state.ones_called and x1 >= 2 * x0 and x1 <= 20


def test_bid_legality_matches_independent_reference() -> None:
    """合法性自洽：五步短路结果 ≍ 独立规约式（逐组合穷举）。"""
    cfg = RuleConfig()
    kinds = (BidKind.NORMAL, BidKind.ZHAI, BidKind.FEI)
    for state, x0, y0 in product(STATES, CURRENT_COUNTS, ALL_FACES):
        current = Bid(x0, y0)
        for kind, x1, y1 in product(kinds, candidate_counts(x0), ALL_FACES):
            action = BidAction(kind, Bid(x1, y1))
            verdict = bid_legal(action, state, current, 4, cfg)
            if kind is BidKind.NORMAL:
                expected = reference_normal_legal(x1, y1, x0, y0, state)
            elif kind is BidKind.ZHAI:
                expected = reference_zhai_legal(x1, x0, state)
            else:
                expected = reference_fei_legal(x1, x0, state)
            assert verdict.legal == expected, (state, current, action, verdict, expected)
            if not verdict.legal:
                assert verdict.reason, (state, current, action)


def test_legal_bid_state_transitions_and_irreversibility() -> None:
    """合法动作可执行：转移正确、过 1 不可逆（R-19/R-22/R-28）。"""
    cfg = RuleConfig()
    kinds = (BidKind.NORMAL, BidKind.ZHAI, BidKind.FEI)
    for state, x0, y0 in product(STATES, CURRENT_COUNTS, ALL_FACES):
        current = Bid(x0, y0)
        for kind, x1, y1 in product(kinds, candidate_counts(x0), ALL_FACES):
            action = BidAction(kind, Bid(x1, y1))
            verdict = bid_legal(action, state, current, 4, cfg)
            if not verdict.legal:
                assert verdict.reason
                continue
            nxt = apply_bid(action, state)
            if kind is BidKind.ZHAI:
                assert nxt == CallState(ZhaiState.DEAD, state.ones_called)
            elif kind is BidKind.FEI:
                assert nxt == CallState(ZhaiState.FLY, False)
            elif y1 == 1:
                assert nxt == CallState(ZhaiState.DEAD, True)  # 过 1（R-28）
            else:
                assert nxt == state
            if state.ones_called:  # 过 1 不可逆（R-22）
                assert nxt.ones_called


def test_opening_floor_matches_reference() -> None:
    """首叫下限：非斋 = ⌈1.5N⌉、斋 = N（R-11/R-12/R-14），点数任意（R-13），飞首叫非法。"""
    cfg = RuleConfig()
    for player_count in range(2, 13):
        fly_floor = min_opening_bid(player_count, False)
        zhai_floor = min_opening_bid(player_count, True)
        assert fly_floor == -(-3 * player_count // 2)  # ⌈1.5N⌉ 的整数实现
        assert zhai_floor == player_count
        assert not opening_legal(
            BidAction(BidKind.FEI, Bid(fly_floor, Face.ONE)), player_count, cfg
        ).legal
        for y1 in ALL_FACES:
            assert opening_legal(
                BidAction(BidKind.NORMAL, Bid(fly_floor, y1)), player_count, cfg
            ).legal
            assert not opening_legal(
                BidAction(BidKind.NORMAL, Bid(fly_floor - 1, y1)), player_count, cfg
            ).legal
            assert opening_legal(
                BidAction(BidKind.ZHAI, Bid(zhai_floor, y1)), player_count, cfg
            ).legal
            assert not opening_legal(
                BidAction(BidKind.ZHAI, Bid(zhai_floor - 1, y1)), player_count, cfg
            ).legal


def test_seat_ring_roundtrip() -> None:
    """座位环几何（R-04）：上一家/下一家互逆。"""
    cfg = RuleConfig()
    for n in range(2, 7):
        for seat in range(n):
            assert previous_seat(next_seat(seat, n, cfg), n, cfg) == seat
            assert next_seat(previous_seat(seat, n, cfg), n, cfg) == seat


def test_verdict_reject_reason_always_nonempty() -> None:
    """每个非法判定的 reason 非空（LegalityVerdict.reject 强制 + 断言兜底）。"""
    state = CallState(ZhaiState.DEAD, True)
    verdict = bid_legal(
        BidAction(BidKind.FEI, Bid(18, Face.FIVE)), state, Bid(9, Face.THREE), 4, RuleConfig()
    )
    assert isinstance(verdict, LegalityVerdict)
    assert not verdict.legal and verdict.reason
