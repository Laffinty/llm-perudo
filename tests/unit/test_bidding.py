"""P1 单元测试：起叫 / 叫骰 / 点数序 / 斋飞 / 杀与应牌（域 bidding，矩阵 §0.3）。

覆盖规则：R-05、R-11 ~ R-36、R-64。属性级穷举见 tests/properties/。
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from perudo.core.legality import (
    apply_bid,
    bid_legal,
    challenge_legal,
    face_beats,
    min_opening_bid,
    opening_legal,
    recounter_target,
    response_options,
)
from perudo.core.opening import opening_caller
from perudo.core.types import (
    ALL_FACES,
    Bid,
    BidAction,
    BidCapPolicy,
    BidKind,
    CallState,
    ChallengeKind,
    Direction,
    Face,
    LegalityVerdict,
    ResponseKind,
    RuleConfig,
    ZhaiState,
)

CFG = RuleConfig()
FLY = CallState(ZhaiState.FLY, False)
DEAD = CallState(ZhaiState.DEAD, False)
DEAD_ONES = CallState(ZhaiState.DEAD, True)
N = 4


def test_r05_opening_caller_loser_first_with_a05_tiebreak() -> None:
    """R-05：上一局输家先起叫；A-05：多输家取罚码最多者，并列按座位方向取先。"""
    assert opening_caller({3: 1}, N, CFG) == 3
    assert opening_caller({1: 2, 2: 4}, N, CFG) == 2  # 罚码最多者
    assert opening_caller({1: 2, 3: 2}, N, CFG) == 1  # 并列 → 座位方向取先
    ccw = replace(CFG, direction=Direction.COUNTER_CLOCKWISE)
    assert opening_caller({1: 2, 3: 2}, N, ccw) == 3  # 逆时针从 0 环行先遇 3
    with pytest.raises(ValueError):
        opening_caller({}, N, CFG)


def test_r11_r12_r14_opening_floor_table() -> None:
    """R-11/R-12/R-14：01 §5.1 起叫下限表逐格（N=2..12，非斋 ⌈1.5N⌉、斋 N、N=5 取 8）。"""
    table = {2: 3, 3: 5, 4: 6, 5: 8, 6: 9, 7: 11, 8: 12, 9: 14, 10: 15, 11: 17, 12: 18}
    for n, floor in table.items():
        assert min_opening_bid(n, False) == floor
        assert min_opening_bid(n, True) == n
    assert min_opening_bid(5, False) == 8  # R-14：⌈7.5⌉ 取 8


def test_r13_opening_face_any() -> None:
    """R-13：首叫点数任意（1–6）。"""
    for face in ALL_FACES:
        assert opening_legal(BidAction(BidKind.NORMAL, Bid(6, face)), N, CFG).legal


def test_r15_r16_face_ranks_dual_track() -> None:
    """R-15/R-16：双轨点数序穷举（FLY：1>6>5>4>3>2；DEAD：1<2<…<6）。"""
    for a in ALL_FACES:
        for b in ALL_FACES:
            expected_fly = {
                Face.ONE: 6,
                Face.SIX: 5,
                Face.FIVE: 4,
                Face.FOUR: 3,
                Face.THREE: 2,
                Face.TWO: 1,
            }[a] > {
                Face.ONE: 6,
                Face.SIX: 5,
                Face.FIVE: 4,
                Face.FOUR: 3,
                Face.THREE: 2,
                Face.TWO: 1,
            }[b]
            assert face_beats(a, b, ZhaiState.FLY) == expected_fly
            assert face_beats(a, b, ZhaiState.DEAD) == (a > b)


def test_r17_r18_normal_rebid_three_regions() -> None:
    """R-17/R-18：数量更大点数任意；同数量比点数；更小非法。两种状态都验。"""
    for state, y_high, y_low in (
        (FLY, Face.ONE, Face.TWO),  # FLY 序：1 最强、2 最弱
        (DEAD, Face.SIX, Face.TWO),  # DEAD 序：6 最强、2 弱于现叫的 3
    ):
        current = Bid(6, Face.THREE)
        assert bid_legal(
            BidAction(BidKind.NORMAL, Bid(7, Face.TWO)), state, current, N, CFG
        ).legal  # R-18
        assert bid_legal(
            BidAction(BidKind.NORMAL, Bid(6, y_high)), state, current, N, CFG
        ).legal  # R-17
        verdict = bid_legal(BidAction(BidKind.NORMAL, Bid(6, y_low)), state, current, N, CFG)
        assert not verdict.legal and verdict.reason
        verdict = bid_legal(BidAction(BidKind.NORMAL, Bid(5, y_high)), state, current, N, CFG)
        assert not verdict.legal and verdict.reason


def test_r19_zhai_transition_disables_wild() -> None:
    """R-19：转斋后状态 DEAD，1 只按面值计（计数口径由 test_counting 验证）。"""
    assert apply_bid(BidAction(BidKind.ZHAI, Bid(6, Face.FOUR)), FLY) == DEAD


def test_r20_zhai_only_count_floor_any_face() -> None:
    """R-20：转斋只需 X' ≥ X0，点数任意（含更小/相同/更大），仅 FLY 态可转。"""
    current = Bid(6, Face.SIX)
    for face in ALL_FACES:
        assert bid_legal(BidAction(BidKind.ZHAI, Bid(6, face)), FLY, current, N, CFG).legal
    verdict = bid_legal(BidAction(BidKind.ZHAI, Bid(5, Face.ONE)), FLY, current, N, CFG)
    assert not verdict.legal and verdict.reason
    verdict = bid_legal(BidAction(BidKind.ZHAI, Bid(6, Face.ONE)), DEAD, current, N, CFG)
    assert not verdict.legal and verdict.reason


def test_r21_fei_requires_double_count() -> None:
    """R-21：飞斋需 X' ≥ 2×X0，点数任意；不足即非法。"""
    current = Bid(9, Face.THREE)
    assert bid_legal(BidAction(BidKind.FEI, Bid(18, Face.FIVE)), DEAD, current, N, CFG).legal
    verdict = bid_legal(BidAction(BidKind.FEI, Bid(17, Face.FIVE)), DEAD, current, N, CFG)
    assert not verdict.legal and verdict.reason


def test_r22_r23_ones_called_irreversible() -> None:
    """R-22/R-23：过 1 后 1 永久不作癞子，不可飞回。"""
    # FLY 下叫 1（满足常规比较）→ 触发过 1（§14.1 第 5 行）
    action = BidAction(BidKind.NORMAL, Bid(7, Face.ONE))
    assert bid_legal(action, FLY, Bid(6, Face.THREE), N, CFG).legal
    assert apply_bid(action, FLY) == DEAD_ONES
    verdict = bid_legal(
        BidAction(BidKind.FEI, Bid(38, Face.FIVE)), DEAD_ONES, Bid(19, Face.ONE), N, CFG
    )
    assert not verdict.legal and verdict.reason


def test_r24_to_r28_five_step_order_probes() -> None:
    """R-24~R-28：五步短路次序的探针用例（各步专属证据）。"""
    # 第 1 步：R-64 先于一切——超上限的转斋/飞斋/常规全部被 R-64 拒绝
    verdict = bid_legal(BidAction(BidKind.ZHAI, Bid(21, Face.ONE)), FLY, Bid(6, Face.ONE), N, CFG)
    assert not verdict.legal and "R-64" in verdict.reason
    # 第 2 步：转斋在 FLY 态豁免"同数量点数须更大"（点数相同也合法）
    assert bid_legal(
        BidAction(BidKind.ZHAI, Bid(6, Face.FOUR)), FLY, Bid(6, Face.FOUR), N, CFG
    ).legal
    # 第 3 步：飞斋只在 DEAD 且未过 1 时进入
    assert bid_legal(
        BidAction(BidKind.FEI, Bid(12, Face.FOUR)), DEAD, Bid(6, Face.FOUR), N, CFG
    ).legal
    # 第 4 步：常规比较用生效前状态序（DEAD 下 1 最小）
    verdict = bid_legal(BidAction(BidKind.NORMAL, Bid(6, Face.ONE)), DEAD, Bid(6, Face.TWO), N, CFG)
    assert not verdict.legal and verdict.reason
    # 第 5 步：合法叫 1 后 ones_called 置真（含 DEAD 态下叫 1）
    assert apply_bid(BidAction(BidKind.NORMAL, Bid(7, Face.ONE)), DEAD) == DEAD_ONES


def test_r64_bid_count_cap_policies() -> None:
    """R-64：叫骰数量上限 5N 为全局硬约束；变体 5N−1 / 不限。"""
    current = Bid(6, Face.ONE)
    assert bid_legal(BidAction(BidKind.NORMAL, Bid(20, Face.SIX)), FLY, current, N, CFG).legal
    verdict = bid_legal(BidAction(BidKind.NORMAL, Bid(21, Face.SIX)), FLY, current, N, CFG)
    assert not verdict.legal and "R-64" in verdict.reason
    minus_one = replace(CFG, bid_cap=BidCapPolicy.FIVE_N_MINUS_ONE)
    assert bid_legal(BidAction(BidKind.NORMAL, Bid(19, Face.SIX)), FLY, current, N, minus_one).legal
    assert not bid_legal(
        BidAction(BidKind.NORMAL, Bid(20, Face.SIX)), FLY, current, N, minus_one
    ).legal
    unlimited = replace(CFG, bid_cap=BidCapPolicy.UNLIMITED)
    assert bid_legal(BidAction(BidKind.NORMAL, Bid(99, Face.SIX)), FLY, current, N, unlimited).legal
    assert not opening_legal(BidAction(BidKind.FEI, Bid(6, Face.ONE)), N, CFG).legal  # 首叫不可飞


def test_r29_open_only_adjacent_predecessor() -> None:
    """R-29：开杀只能对相邻上家发起。"""
    assert challenge_legal(ChallengeKind.OPEN, 3, (2,), (0, 1, 2), N, CFG).legal
    verdict = challenge_legal(ChallengeKind.OPEN, 3, (1,), (0, 1, 2), N, CFG)
    assert not verdict.legal and verdict.reason  # 上家是 2，不是 1
    verdict = challenge_legal(ChallengeKind.OPEN, 3, (0,), (0, 1, 2), N, CFG)
    assert not verdict.legal and verdict.reason
    verdict = challenge_legal(ChallengeKind.OPEN, 0, (), (), N, CFG)
    assert not verdict.legal and verdict.reason  # 本局无叫骰


def test_challenge_target_discipline() -> None:
    """R-29~R-32 附带纪律：目标不得重复；跳杀只针对单一目标。"""
    verdict = challenge_legal(ChallengeKind.OPEN, 3, (2, 2), (0, 1, 2), N, CFG)
    assert not verdict.legal and verdict.reason  # 目标重复
    verdict = challenge_legal(ChallengeKind.JUMP, 3, (0, 1), (0, 1, 2), N, CFG)
    assert not verdict.legal and verdict.reason  # 跳杀多目标


def test_opening_r64_cap_applies_to_first_call() -> None:
    """R-64 对首叫同样生效：4 人局首叫最多 20 个。"""
    verdict = opening_legal(BidAction(BidKind.NORMAL, Bid(21, Face.ONE)), N, CFG)
    assert not verdict.legal and "R-64" in verdict.reason
    assert opening_legal(BidAction(BidKind.NORMAL, Bid(20, Face.ONE)), N, CFG).legal


def test_r30_jump_only_non_adjacent_caller() -> None:
    """R-30：跳杀只能对非相邻玩家发起，且目标必须叫过骰。"""
    assert challenge_legal(ChallengeKind.JUMP, 3, (1,), (0, 1, 2), N, CFG).legal
    verdict = challenge_legal(ChallengeKind.JUMP, 3, (2,), (0, 1, 2), N, CFG)
    assert not verdict.legal and verdict.reason  # 相邻上家应开杀
    verdict = challenge_legal(ChallengeKind.JUMP, 3, (0,), (1, 2), N, CFG)
    assert not verdict.legal and verdict.reason  # 目标本局未叫骰


def test_r31_multi_consecutive_callers() -> None:
    """R-31：连杀目标 = 叫骰流水末尾连续 ≥2 位叫骰者，不得包含自己。"""
    assert challenge_legal(ChallengeKind.MULTI, 3, (1, 2), (0, 1, 2), N, CFG).legal
    assert challenge_legal(ChallengeKind.MULTI, 3, (0, 1, 2), (0, 1, 2), N, CFG).legal
    verdict = challenge_legal(ChallengeKind.MULTI, 3, (2,), (0, 1, 2), N, CFG)
    assert not verdict.legal and verdict.reason  # 至少 2 人
    verdict = challenge_legal(ChallengeKind.MULTI, 3, (0, 2), (0, 1, 2), N, CFG)
    assert not verdict.legal and verdict.reason  # 非连续后缀
    verdict = challenge_legal(ChallengeKind.MULTI, 3, (0, 3), (0, 1, 3), N, CFG)
    assert not verdict.legal and verdict.reason  # 含自己


def test_r32_sweep_all_other_participants() -> None:
    """R-32：通杀点名除自己外的全部参加者。"""
    assert challenge_legal(ChallengeKind.SWEEP, 0, (1, 2, 3), (1, 2, 3), N, CFG).legal
    verdict = challenge_legal(ChallengeKind.SWEEP, 0, (1, 2), (1, 2, 3), N, CFG)
    assert not verdict.legal and verdict.reason  # 缺人
    verdict = challenge_legal(ChallengeKind.SWEEP, 0, (1, 2, 3), (), N, CFG)
    assert not verdict.legal and verdict.reason  # 无叫骰无判定对象


def test_r33_r34_response_options_by_chain_kind() -> None:
    """R-33/R-34：应牌三选一；反杀仅被跳杀者（变体 counter_on_open 两态）。"""
    assert response_options(ChallengeKind.JUMP, CFG) == frozenset(
        {ResponseKind.REVEAL, ResponseKind.COUNTER, ResponseKind.SURRENDER}
    )
    assert response_options(ChallengeKind.OPEN, CFG) == frozenset(
        {ResponseKind.REVEAL, ResponseKind.SURRENDER}
    )
    open_counter = replace(CFG, counter_on_open=True)
    assert ResponseKind.COUNTER in response_options(ChallengeKind.OPEN, open_counter)


def test_r35_surrender_always_available() -> None:
    """R-35：投降始终在应牌选项中（不开盅接受减半，结算见 test_settling）。"""
    for kind in ChallengeKind:
        assert ResponseKind.SURRENDER in response_options(kind, CFG)


def test_r36_recounter_next_caller_once() -> None:
    """R-36：反杀后原杀者可对下一位叫骰者再反杀一次（§13.3：D 再反劈 A）。"""
    assert recounter_target(3, (0, 1, 2), N, CFG) == 0
    assert recounter_target(1, (0, 1, 2, 3, 1), N, CFG) == 2  # 下一位叫骰者
    assert recounter_target(0, (), N, CFG) is None  # 无人叫骰


def test_verdict_reason_discipline() -> None:
    """02 §3.1：非法判定必须带非空人类可读原因。"""
    verdict = LegalityVerdict.reject("测试原因")
    assert verdict.reason == "测试原因"
    with pytest.raises(ValueError):
        LegalityVerdict.reject("")
