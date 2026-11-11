"""两个专门子流程（02 §2.4）：摇骰重摇子流程 + 摊牌结算。

应牌链的**决策交互**由 ``match`` 驱动（与纠错/故障政策共用问询机制）；
本模块承担其中无决策的部分：摇骰合规、摊牌判定与逐 stake 结算（含 R-50）。
"""

from __future__ import annotations

from collections.abc import Callable
from fractions import Fraction
from typing import Any

from perudo.core.counting import total_count
from perudo.core.legality import needs_reshake, reroll_verdict_failed
from perudo.core.settlement import (
    decide_bid_stood,
    drink_along_pick,
    multi_kill_double,
    settle_stake,
)
from perudo.core.types import (
    CallState,
    ChallengeKind,
    Face,
    Hand,
    LoserEntry,
    LoserSide,
    StakeContext,
    ZhaiState,
)
from perudo.engine.events import EventType, Visibility, bid_pair
from perudo.engine.rng import Rng
from perudo.engine.state import ChainState, MatchState

__all__ = ["EmitFn", "leopard_flag", "holds_leopard", "run_shake_phase", "showdown"]

EmitFn = Callable[[str, Visibility, dict[str, Any]], None]


def leopard_flag(hand: Hand, call_state: CallState) -> str | None:
    """骰盅卡的围骰/全骰标注（05 G-01：引擎预渲染，前端零规则逻辑）。

    "全骰" = 5 颗本来全同；"围骰" = 飞态可借 1 凑成同面值（R-39）；
    1 死状态下借 1 不成立（R-41），故只按全骰判断。
    """
    dice = hand.dice
    if len(set(dice)) == 1:
        return "全骰"
    if call_state.zhai is ZhaiState.FLY:
        for face_value in range(2, 7):
            if sum(1 for d in dice if int(d) == face_value or d == Face.ONE) == 5:
                return "围骰"
    return None


def holds_leopard(hand: Hand, face: Face, call_state: CallState) -> bool:
    """输家手牌对被叫面值是否构成围骰/全骰（R-53 豹子加倍前提；仅飞态，R-41）。"""
    dice = hand.dice
    if call_state.zhai is not ZhaiState.FLY:
        return False
    n_face = sum(1 for d in dice if d == face)
    n_ones = sum(1 for d in dice if d == Face.ONE)
    if n_face == 5 or n_ones == 5:  # 全骰（5 个 1 对任意面值，R-43）
        return True
    return face != Face.ONE and n_face + n_ones >= 5  # 围骰


def run_shake_phase(state: MatchState, rng: Rng, emit: EmitFn) -> None:
    """摇骰 + 自动重摇子流程（R-01/R-07/R-08~R-10/R-60/R-65）。

    - 每获得新手牌发 HandShaken（私密）；每次重摇发 Rerolled（公开，当众动作）；
    - 超过重摇上限仍不合规 → 判负罚 1 码（R-65/R-46）：入 round_entries、
      跳过本局行动，最后一次手牌保留（仍参与全场计数，R-03 字面）；
    - 最终手牌确定后，纯 EVE 观战桌发 HandObserved（05 G-01，引擎预渲染标注）。
    """
    rules = state.config.rules
    for seat in range(state.config.player_count):
        hand = Hand(rng.roll(5))
        times = 0
        while True:
            state.hands[seat] = hand
            emit(
                EventType.HAND_SHAKEN,
                Visibility.PRIVATE,
                {"seat": seat, "dice": [int(f) for f in hand.dice]},
            )
            reason = needs_reshake(hand, rules)
            if reason is None:
                break
            times += 1
            state.reroll_counts[seat] = times
            emit(
                EventType.REROLLED,
                Visibility.PUBLIC,
                {"seat": seat, "reason": reason.value, "times": times},
            )
            if reroll_verdict_failed(times, rules):
                state.disqualified.add(seat)
                state.round_entries.append(
                    LoserEntry(seat, 1, Fraction(1), (("reroll:R-65", Fraction(1)),))
                )
                break
            hand = Hand(rng.roll(5))
        if state.config.spectated:
            flag = leopard_flag(hand, state.call_state)
            emit(
                EventType.HAND_OBSERVED,
                Visibility.PUBLIC,
                {
                    "seat": seat,
                    "dice": [int(f) for f in hand.dice],
                    "leopard_flag": flag,
                },
            )


def showdown(state: MatchState, chain: ChainState, emit: EmitFn) -> list[LoserEntry]:
    """摊牌：REVEALED（有判定 stake 时）+ 逐 stake 结算（R-45/R-50/R-51/R-53/R-54/R-55/R-56）。

    返回本链的全部结算 entries（不含陪饮附属）。有 REVEAL 的 stake 才有判定；
    全员投降时无 REVEALED、无判定。R-50 连赢 ×2 仅作用于连杀（MULTI）中
    被判不成立的目标（01 §14.2）。
    """
    rules = state.config.rules
    # 载荷键一律字符串：JSON 往返稳定（A-10 逐字段一致经由权威流验证）
    hands_payload = {
        str(seat): [int(f) for f in hand.dice] for seat, hand in sorted(state.hands.items())
    }
    judgments: list[dict[str, Any]] = []
    for seat in chain.targets:
        bid = chain.contested_bids[seat]
        count = total_count(state.hands, bid.face, state.call_state, rules)
        stood = decide_bid_stood(bid, count, state.hands, rules)
        judgments.append({"seat": seat, "bid": bid_pair(bid), "count": count, "stood": stood})
    if judgments:
        emit(
            EventType.REVEALED,
            Visibility.PUBLIC,
            {"hands": hands_payload, "judgments": judgments, "darkness": rules.darkness},
        )
    win_count = sum(1 for j in judgments if not j["stood"])
    double_targets = chain.kind is ChallengeKind.MULTI and multi_kill_double(win_count, rules)
    entries: list[LoserEntry] = []
    for index, seat in enumerate(chain.targets):
        bid = chain.contested_bids[seat]
        base = chain.stakes[seat]
        response = chain.responses.get(seat)
        stake_chain = chain.kind if chain.kind is ChallengeKind.JUMP else ChallengeKind.OPEN
        if response == "surrender":
            entries.append(
                settle_stake(
                    StakeContext(
                        loser=seat,
                        side=LoserSide.CHALLENGED,
                        chain=stake_chain,
                        base_multiplier=base,
                        bid=bid,
                        bid_stood=None,
                        count=None,
                    ),
                    rules,
                )
            )
            continue
        judgment = judgments[index]
        count = int(judgment["count"])
        stood = bool(judgment["stood"])
        if stood:
            entries.append(
                settle_stake(
                    StakeContext(
                        loser=chain.initiator,
                        side=LoserSide.CHALLENGER,
                        chain=stake_chain,
                        base_multiplier=base,
                        bid=bid,
                        bid_stood=True,
                        count=count,
                    ),
                    rules,
                )
            )
        else:
            multiplier = base * 2 if double_targets else base  # R-50（连杀连赢达标）
            entries.append(
                settle_stake(
                    StakeContext(
                        loser=seat,
                        side=LoserSide.CHALLENGED,
                        chain=stake_chain,
                        base_multiplier=multiplier,
                        bid=bid,
                        bid_stood=False,
                        count=count,
                        loser_holds_leopard=holds_leopard(
                            state.hands[seat], bid.face, state.call_state
                        ),
                    ),
                    rules,
                )
            )
    return entries


def drink_along_entries(state: MatchState, rng: Rng, entries: list[LoserEntry]) -> list[LoserEntry]:
    """陪饮附属子流程（R-57，05 §5：结算后执行，骰面由引擎种子驱动）。

    每个输家摇陪饮骰（N ≥ 6 用 1 颗大骰，否则 2 颗）；选中他人 → 同罚一份；
    摇中自己 → 自己再多喝一倍（再罚一份）。映射细则见计划 §8 D-05。
    """
    if not state.config.rules.drink_along:
        return []
    player_count = state.config.player_count
    extra: list[LoserEntry] = []
    for entry in entries:
        if entry.codes <= 0:
            continue
        roll = rng.roll(1 if player_count >= 6 else 2)
        result = drink_along_pick(entry.player, roll, player_count, state.config.rules)
        if result.self_hit:
            extra.append(
                LoserEntry(
                    entry.player, entry.codes, Fraction(1), (("R-57 陪饮自中", Fraction(1)),)
                )
            )
        else:
            extra.append(
                LoserEntry(result.buddy, entry.codes, Fraction(1), (("R-57 陪饮", Fraction(1)),))
            )
    return extra
