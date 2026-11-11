"""P2 单元测试：两个专门子流程（02 §2.4）——摇骰重摇 + 摊牌结算。"""

from __future__ import annotations

from fractions import Fraction

from conftest import ScriptedRng
from perudo.core.types import (
    Bid,
    CallState,
    ChallengeKind,
    Face,
    Hand,
    ZhaiState,
)
from perudo.engine.config import MatchConfig
from perudo.engine.events import Event, Visibility
from perudo.engine.phases import holds_leopard, leopard_flag, run_shake_phase, showdown
from perudo.engine.rng import SplitMix64
from perudo.engine.state import ChainState, MatchState


def _state(config: MatchConfig | None = None) -> MatchState:
    cfg = config or MatchConfig()
    return MatchState(match_id="m_phases", config=cfg, scores=[0] * cfg.player_count)


def _collect(state: MatchState, rng: ScriptedRng | SplitMix64) -> list[Event]:
    events: list[Event] = []
    seq = 0

    def emit(etype: str, visibility: Visibility, payload: dict) -> None:
        nonlocal seq
        seq += 1
        events.append(Event(seq, etype, visibility, payload))

    run_shake_phase(state, rng, emit)
    return events


def test_leopard_flag_rendering() -> None:
    """G-01 预渲染标注：全骰 / 围骰 / 无标注；1 死状态只认全骰（R-41）。"""
    fly = CallState(ZhaiState.FLY, False)
    assert leopard_flag(Hand((Face.FOUR,) * 5), fly) == "全骰"
    assert leopard_flag(Hand((Face.FOUR, Face.FOUR, Face.FOUR, Face.FOUR, Face.ONE)), fly) == "围骰"
    assert leopard_flag(Hand((Face.ONE,) * 5), fly) == "全骰"
    assert leopard_flag(Hand((Face.FOUR, Face.FOUR, Face.THREE, Face.ONE, Face.ONE)), fly) is None
    dead = CallState(ZhaiState.DEAD, False)
    assert leopard_flag(Hand((Face.FOUR, Face.FOUR, Face.FOUR, Face.FOUR, Face.ONE)), dead) is None
    assert leopard_flag(Hand((Face.FOUR,) * 5), dead) == "全骰"


def test_holds_leopard_for_r53() -> None:
    """R-53 前提：被叫面值构成围骰/全骰；1 死状态不构成（R-41）。"""
    fly = CallState(ZhaiState.FLY, False)
    assert holds_leopard(Hand((Face.THREE,) * 5), Face.THREE, fly)
    assert holds_leopard(
        Hand((Face.THREE, Face.THREE, Face.THREE, Face.THREE, Face.ONE)), Face.THREE, fly
    )
    assert holds_leopard(Hand((Face.ONE,) * 5), Face.THREE, fly)  # 5 个 1 对任意面值（R-43）
    assert not holds_leopard(
        Hand((Face.THREE, Face.THREE, Face.TWO, Face.ONE, Face.FIVE)), Face.THREE, fly
    )
    dead = CallState(ZhaiState.DEAD, False)
    assert not holds_leopard(Hand((Face.THREE,) * 5), Face.THREE, dead)


def test_shake_clean_hands_no_reroll() -> None:
    """合规手牌：每人一次 HandShaken（私密）、无 Rerolled、无人判负。"""
    state = _state()
    rng = ScriptedRng(rolls=[(Face.ONE, Face.ONE, Face.TWO, Face.THREE, Face.FOUR)] * 4)
    events = _collect(state, rng)
    shaken = [e for e in events if e.type == "HandShaken"]
    assert len(shaken) == 4 and all(e.visibility is Visibility.PRIVATE for e in shaken)
    assert not [e for e in events if e.type == "Rerolled"]
    assert not state.disqualified and not state.round_entries


def test_shake_scattered_rerolls_and_disqualify() -> None:
    """散骰必重摇（R-09）+ 上限判负（R-65）：第 4 次重摇仍散骰 → 判负罚 1 码。"""
    state = _state()
    scattered: tuple[Face, ...] = (Face.ONE, Face.TWO, Face.THREE, Face.FOUR, Face.SIX)
    clean: tuple[Face, ...] = (Face.ONE, Face.ONE, Face.TWO, Face.THREE, Face.FOUR)
    rng = ScriptedRng(rolls=[scattered, scattered, scattered, scattered, clean, clean, clean])
    events = _collect(state, rng)
    rerolled = [e for e in events if e.type == "Rerolled"]
    assert [e.payload["times"] for e in rerolled] == [1, 2, 3, 4]
    assert state.disqualified == {0}
    assert len(state.round_entries) == 1
    entry = state.round_entries[0]
    assert entry.player == 0 and entry.codes == 1
    # 判负者最后一次手牌保留（仍参与全场计数，登记口径）
    assert state.hands[0].dice == scattered


def test_shake_spectated_projection() -> None:
    """纯 EVE 观战投影（05 G-01）：spectated=True → HandObserved 带围骰标注。"""
    cfg = MatchConfig(spectated=True)
    state = _state(cfg)
    rng = ScriptedRng(rolls=[(Face.FOUR, Face.FOUR, Face.FOUR, Face.FOUR, Face.ONE)] * 4)
    events = _collect(state, rng)
    observed = [e for e in events if e.type == "HandObserved"]
    assert len(observed) == 4
    assert observed[0].payload["leopard_flag"] == "围骰"


def _chain_all_reveal(state: MatchState, bids: dict[int, Bid]) -> ChainState:
    chain = ChainState(
        initiator=3,
        kind=ChallengeKind.MULTI,
        targets=(1, 2),
        stakes={1: Fraction(1), 2: Fraction(1)},
        contested_bids=bids,
        awaiting=1,
    )
    for seat in (1, 2):
        chain.responses[seat] = "reveal"
    return chain


def test_showdown_multi_targets_separate_settlement() -> None:
    """R-51：连杀两目标分别结算；R-50 连赢未达标不翻倍。"""
    state = _state()
    fly = CallState(ZhaiState.FLY, False)
    for seat in range(4):
        state.hands[seat] = Hand((Face.ONE, Face.ONE, Face.TWO, Face.THREE, Face.FOUR))
    state.call_state = fly
    bids = {1: Bid(7, Face.THREE), 2: Bid(8, Face.FOUR)}
    chain = _chain_all_reveal(state, bids)
    events: list[Event] = []
    seq = 0

    def emit(etype: str, visibility: Visibility, payload: dict) -> None:
        nonlocal seq
        seq += 1
        events.append(Event(seq, etype, visibility, payload))

    entries = showdown(state, chain, emit)
    # count(3) = 每人 1×3 + 3×1(癞子) = 8 ≥ 7 → seat1 成立；count(4) = 8 ≥ 8 → seat2 成立
    # 两个 stake 都是开杀型杀者输 → 进阶默认开（R-55 超半）→ 各 ×2
    assert [(e.player, e.codes) for e in entries] == [(3, 2), (3, 2)]
    revealed = [e for e in events if e.type == "Revealed"]
    assert len(revealed) == 1
    assert revealed[0].payload["judgments"][0]["stood"] is True
