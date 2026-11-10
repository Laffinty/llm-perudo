"""P1 集成验收：01 §13 三例完整对账逐项对账（计划 §3 P1 验收标准第一条）。

三例均按 4 人局、基线默认、1 码 = 1 份、进阶规则（§9.2）关闭（01 §13 开头约定）；
另以「进阶全开」变体断言 D-04 裁决口径（计划 §8）在完整对账下的端到端结果。

座位约定：A=0、B=1、C=2、D=3，顺时针（R-04 基线）。
"""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

from perudo.core.counting import player_contribution, total_count
from perudo.core.legality import (
    apply_bid,
    bid_legal,
    challenge_legal,
    opening_legal,
    recounter_target,
    response_options,
)
from perudo.core.opening import opening_caller
from perudo.core.settlement import judge, settle_stake
from perudo.core.types import (
    Bid,
    BidAction,
    BidKind,
    CallState,
    ChallengeKind,
    Face,
    Hand,
    LoserSide,
    ResponseKind,
    RuleConfig,
    StakeContext,
    ZhaiState,
)

_A, _B, _C, _D = 0, 1, 2, 3
_PLAYERS = 4


def H(*faces: int) -> Hand:
    """按整数骰面快速构造手牌。"""
    return Hand(tuple(Face(f) for f in faces))


def baseline_cfg() -> RuleConfig:
    """§13 三例的桌面配置：基线默认 + 进阶（§9.2）关闭。"""
    return replace(RuleConfig(), half_double=False, jump_fail_double=False, leopard_double=False)


def advanced_cfg() -> RuleConfig:
    """进阶（§9.2）全开的配置（§12 第 7/8/9 项默认值）。"""
    return RuleConfig()


# ---------------------------------------------------------------------------
# 13.1 例一：普通开杀 + 围骰计数
# ---------------------------------------------------------------------------


def test_example1_full_reconciliation() -> None:
    cfg = baseline_cfg()
    hands = {_A: H(4, 4, 4, 1, 2), _B: H(6, 6, 3, 5, 1), _C: H(5, 5, 5, 5, 1), _D: H(1, 1, 3, 5, 6)}
    state = CallState.initial()

    # 叫骰（01 §13.1）
    a_open = BidAction(BidKind.NORMAL, Bid(6, Face.FOUR))
    assert opening_legal(a_open, _PLAYERS, cfg).legal  # ⌈1.5×4⌉ = 6，6 ≥ 6 ✓
    state = apply_bid(a_open, state)

    b_bid = BidAction(BidKind.NORMAL, Bid(6, Face.FIVE))
    assert bid_legal(b_bid, state, a_open.bid, _PLAYERS, cfg).legal  # 同数量，飞序 5 > 4 ✓
    state = apply_bid(b_bid, state)

    c_bid = BidAction(BidKind.NORMAL, Bid(7, Face.FIVE))
    assert bid_legal(c_bid, state, b_bid.bid, _PLAYERS, cfg).legal  # 7 > 6 ✓
    state = apply_bid(c_bid, state)

    # D 开杀相邻上家 C（R-29）
    assert challenge_legal(ChallengeKind.OPEN, _D, (_C,), (_A, _B, _C), _PLAYERS, cfg).legal

    # 开盅计数（被叫点数 5，飞状态，1 作癞子；§13.1 贡献表）
    expected = {_A: 1, _B: 2, _C: 6, _D: 3}
    for seat, hand in hands.items():
        assert player_contribution(hand, Face.FIVE, state, cfg) == expected[seat]
    count = total_count(hands, Face.FIVE, state, cfg)
    assert count == 12

    # 判定与结算：12 ≥ 7 ⇒ 成立 ⇒ 开骰者 D 输，付 1 码
    assert judge(count, Bid(7, Face.FIVE)) is True
    entry = settle_stake(
        StakeContext(
            loser=_D,
            side=LoserSide.CHALLENGER,
            chain=ChallengeKind.OPEN,
            base_multiplier=Fraction(1),
            bid=Bid(7, Face.FIVE),
            bid_stood=True,
            count=count,
        ),
        cfg,
    )
    assert entry.player == _D and entry.codes == 1

    # R-05：下一局由输家 D 起叫
    assert opening_caller({_D: 1}, _PLAYERS, cfg) == _D


def test_example1_with_leopard_bonus_off_variants() -> None:
    """01 §13.1 注：改用「有骰计骰」（R-44），C 只记 5 个，count = 11，结论不变。"""
    cfg = replace(baseline_cfg(), leopard_bonus=False)
    hands = {_A: H(4, 4, 4, 1, 2), _B: H(6, 6, 3, 5, 1), _C: H(5, 5, 5, 5, 1), _D: H(1, 1, 3, 5, 6)}
    state = CallState(ZhaiState.FLY, False)
    assert player_contribution(hands[_C], Face.FIVE, state, cfg) == 5
    assert total_count(hands, Face.FIVE, state, cfg) == 11
    assert judge(11, Bid(7, Face.FIVE)) is True  # 11 ≥ 7，结论不变


def test_example1_advanced_on_r55() -> None:
    """D-04 裁决：进阶全开时，开杀者输吃 R-55「超半」×2（判定不翻转）。"""
    entry = settle_stake(
        StakeContext(
            loser=_D,
            side=LoserSide.CHALLENGER,
            chain=ChallengeKind.OPEN,
            base_multiplier=Fraction(1),
            bid=Bid(7, Face.FIVE),
            bid_stood=True,
            count=12,
        ),
        advanced_cfg(),
    )
    assert entry.codes == 2


# ---------------------------------------------------------------------------
# 13.2 例二：转斋 → 飞斋 → 过 1 不可逆
# ---------------------------------------------------------------------------


def test_example2_full_reconciliation() -> None:
    cfg = baseline_cfg()
    hands = {_A: H(1, 1, 1, 2, 3), _B: H(4, 5, 6, 6, 6), _C: H(2, 2, 3, 4, 5), _D: H(1, 2, 3, 4, 5)}
    state = CallState.initial()

    # 1. A 起叫 "6 个 4"（WILD）✓
    s1 = BidAction(BidKind.NORMAL, Bid(6, Face.FOUR))
    assert opening_legal(s1, _PLAYERS, cfg).legal
    state = apply_bid(s1, state)

    # 2. B 转斋 "6 个 4 斋"：转斋只需 X' ≥ 6，点数相同也合法（R-20）⇒ DEAD
    s2 = BidAction(BidKind.ZHAI, Bid(6, Face.FOUR))
    assert bid_legal(s2, state, s1.bid, _PLAYERS, cfg).legal
    state = apply_bid(s2, state)
    assert state == CallState(ZhaiState.DEAD, False)

    # 3. C 接叫 "7 个 5"（7 > 6）✓；4. D 接叫 "7 个 6"（DEAD 序 6 > 5）✓
    s3 = BidAction(BidKind.NORMAL, Bid(7, Face.FIVE))
    s4 = BidAction(BidKind.NORMAL, Bid(7, Face.SIX))
    assert bid_legal(s3, state, s2.bid, _PLAYERS, cfg).legal
    state = apply_bid(s3, state)
    assert bid_legal(s4, state, s3.bid, _PLAYERS, cfg).legal
    state = apply_bid(s4, state)

    # 5. A 接叫 "8 个 6"（8 > 7）✓；6. B 接叫 "8 个 6" —— DEAD 序中 6 > 6 ✗ 不合法
    s5 = BidAction(BidKind.NORMAL, Bid(8, Face.SIX))
    assert bid_legal(s5, state, s4.bid, _PLAYERS, cfg).legal
    state = apply_bid(s5, state)
    s6 = BidAction(BidKind.NORMAL, Bid(8, Face.SIX))
    verdict = bid_legal(s6, state, s5.bid, _PLAYERS, cfg)
    assert not verdict.legal and verdict.reason  # 只能叫 "9 个 X"

    # 7. B 改叫 "9 个 3" ✓
    s7 = BidAction(BidKind.NORMAL, Bid(9, Face.THREE))
    assert bid_legal(s7, state, s5.bid, _PLAYERS, cfg).legal
    state = apply_bid(s7, state)

    # 8. C 飞斋 "18 个 5"：X' ≥ 2×9 = 18 ✓ 且未过 1 ✓ ⇒ FLY（R-21、R-23）
    s8 = BidAction(BidKind.FEI, Bid(18, Face.FIVE))
    assert bid_legal(s8, state, s7.bid, _PLAYERS, cfg).legal
    state = apply_bid(s8, state)
    assert state == CallState(ZhaiState.FLY, False)

    # 9. D 接叫 "18 个 6"：比较用动作生效前的状态（WILD），6 > 5 ✓
    s9 = BidAction(BidKind.NORMAL, Bid(18, Face.SIX))
    assert bid_legal(s9, state, s8.bid, _PLAYERS, cfg).legal
    state = apply_bid(s9, state)

    # 10. A 过 1 "19 个 1"：19 > 18，WILD 序中 1 最大 ✓ ⇒ 触发过 1（R-22）
    s10 = BidAction(BidKind.NORMAL, Bid(19, Face.ONE))
    assert bid_legal(s10, state, s9.bid, _PLAYERS, cfg).legal
    state = apply_bid(s10, state)
    assert state == CallState(ZhaiState.DEAD, True)

    # 本局此后不可再飞斋（R-23）
    s_fly = BidAction(BidKind.FEI, Bid(38, Face.FIVE))
    verdict = bid_legal(s_fly, state, s10.bid, _PLAYERS, cfg)
    assert not verdict.legal and verdict.reason

    # 11. B 开杀相邻上家 A ✓
    assert challenge_legal(ChallengeKind.OPEN, _B, (_A,), (_A, _B, _C, _D, _A), _PLAYERS, cfg).legal

    # 开盅计数（被叫点数 1，DEAD：无癞子、无围骰加成）
    expected = {_A: 3, _B: 0, _C: 0, _D: 1}
    for seat, hand in hands.items():
        assert player_contribution(hand, Face.ONE, state, cfg) == expected[seat]
    count = total_count(hands, Face.ONE, state, cfg)
    assert count == 4

    # 判定与结算：4 < 19 ⇒ 不成立 ⇒ 被开者 A 输，付 1 码
    assert judge(count, Bid(19, Face.ONE)) is False
    entry = settle_stake(
        StakeContext(
            loser=_A,
            side=LoserSide.CHALLENGED,
            chain=ChallengeKind.OPEN,
            base_multiplier=Fraction(1),
            bid=Bid(19, Face.ONE),
            bid_stood=False,
            count=count,
        ),
        cfg,
    )
    assert entry.player == _A and entry.codes == 1


def test_example2_advanced_on_r54() -> None:
    """D-04 裁决：进阶全开时，count(4) < 19/2 ⇒ R-54「不够一半」×2（开杀链）。"""
    entry = settle_stake(
        StakeContext(
            loser=_A,
            side=LoserSide.CHALLENGED,
            chain=ChallengeKind.OPEN,
            base_multiplier=Fraction(1),
            bid=Bid(19, Face.ONE),
            bid_stood=False,
            count=4,
        ),
        advanced_cfg(),
    )
    assert entry.codes == 2


# ---------------------------------------------------------------------------
# 13.3 例三：劈 + 反劈 + 全骰计数
# ---------------------------------------------------------------------------


def test_example3_full_reconciliation() -> None:
    cfg = baseline_cfg()
    hands = {_A: H(1, 1, 1, 1, 1), _B: H(3, 3, 3, 2, 4), _C: H(6, 6, 6, 5, 5), _D: H(2, 3, 4, 5, 6)}
    state = CallState.initial()

    # 1. A 起叫 "6 个 3"；2. B 接叫 "7 个 3"；3. C 接叫 "8 个 4"
    s1 = BidAction(BidKind.NORMAL, Bid(6, Face.THREE))
    s2 = BidAction(BidKind.NORMAL, Bid(7, Face.THREE))
    s3 = BidAction(BidKind.NORMAL, Bid(8, Face.FOUR))
    assert opening_legal(s1, _PLAYERS, cfg).legal
    state = apply_bid(s1, state)
    assert bid_legal(s2, state, s1.bid, _PLAYERS, cfg).legal
    state = apply_bid(s2, state)
    assert bid_legal(s3, state, s2.bid, _PLAYERS, cfg).legal
    state = apply_bid(s3, state)

    # 4. D 劈 B：座位环 A-B-C-D，B 与 D 不相邻 ✓（R-30）
    assert challenge_legal(ChallengeKind.JUMP, _D, (_B,), (_A, _B, _C), _PLAYERS, cfg).legal
    # 被劈者可反杀（R-34）
    assert ResponseKind.COUNTER in response_options(ChallengeKind.JUMP, cfg)

    # 开盅计数（被叫点数 3，飞状态；A 的 5 个 1 = 全骰 7，R-40/R-43）
    expected = {_A: 7, _B: 3, _C: 0, _D: 1}
    for seat, hand in hands.items():
        assert player_contribution(hand, Face.THREE, state, cfg) == expected[seat]
    count = total_count(hands, Face.THREE, state, cfg)
    assert count == 11

    # 判定与结算：11 ≥ 7 ⇒ 成立 ⇒ 劈的人 D 输；反劈后倍数 ×4 ⇒ D 付 4 码
    assert judge(count, Bid(7, Face.THREE)) is True
    entry = settle_stake(
        StakeContext(
            loser=_D,
            side=LoserSide.CHALLENGER,
            chain=ChallengeKind.JUMP,
            base_multiplier=Fraction(4),  # 跳杀 ×2 → 反杀 ×4（01 §14.2）
            bid=Bid(7, Face.THREE),
            bid_stood=True,
            count=count,
        ),
        cfg,
    )
    assert entry.player == _D and entry.codes == 4


def test_example3_recounter_step6() -> None:
    """（可选）第 6 步：D 再反劈 A —— R-36 允许原开杀者对下一位叫骰者再反杀一次，×8。

    A 是 D 沿座位方向的下一位叫骰者（01 §13.3 第 6 步）。
    """
    cfg = baseline_cfg()
    assert recounter_target(_D, (_A, _B, _C), _PLAYERS, cfg) == _A
    entry = settle_stake(
        StakeContext(
            loser=_D,
            side=LoserSide.CHALLENGER,
            chain=ChallengeKind.JUMP,
            base_multiplier=Fraction(8),  # 跳杀 ×2 → 反杀 ×4 → 再反杀 ×8
            bid=Bid(7, Face.THREE),
            bid_stood=True,
            count=11,
        ),
        cfg,
    )
    assert entry.codes == 8


def test_example3_advanced_on_r56() -> None:
    """D-04 裁决：进阶全开时，反杀链上跳杀者输再吃 R-56「跳杀失败」×2 ⇒ ×8。"""
    entry = settle_stake(
        StakeContext(
            loser=_D,
            side=LoserSide.CHALLENGER,
            chain=ChallengeKind.JUMP,
            base_multiplier=Fraction(4),
            bid=Bid(7, Face.THREE),
            bid_stood=True,
            count=11,
        ),
        advanced_cfg(),
    )
    assert entry.codes == 8
