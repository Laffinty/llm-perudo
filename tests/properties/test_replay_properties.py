"""P2 属性测试：同种子重放逐字段一致（02 A-10，05 §2.2）+ 信息隔离（02 §5）。

用保守机器人驱动完整桌局，跨种子/配置穷举式验证引擎的两条硬性质。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from perudo.engine.config import MatchConfig
from perudo.engine.events import EventType
from perudo.engine.match import Match
from perudo.engine.replay import resume_match
from perudo.engine.state import MatchStatus
from perudo.engine.stream import extract_decisions
from perudo.players.base import Decision, PlayerView
from perudo.players.bot import ConservativeBot

_SEEDS = [1, 7, 42, 2026, 99991]
_CONFIGS = [
    MatchConfig(end_threshold=30, max_rounds=200),
    replace(MatchConfig(), end_threshold=30, max_rounds=200, player_count=2),
    replace(MatchConfig(), end_threshold=40, max_rounds=200, player_count=6).with_rules(
        darkness=True, drink_along=True
    ),
]


def _run(match_id: str, seed: int, config: MatchConfig, tmp_path: Path | None = None) -> Match:
    roster = [ConservativeBot(f"bot{i}") for i in range(config.player_count)]
    kwargs: dict = {"seed": seed}
    if tmp_path is not None:
        stream = tmp_path / f"{match_id}" / "stream.jsonl"
        stream.parent.mkdir(parents=True, exist_ok=True)
        kwargs["stream_path"] = stream
    match = Match.create(match_id, config, roster, **kwargs)
    match.run_to_end()
    return match


@pytest.mark.parametrize("seed", _SEEDS)
@pytest.mark.parametrize("config", _CONFIGS, ids=["p4-base", "p2-base", "p6-toggles"])
def test_same_seed_reproduces_event_stream(tmp_path: Path, seed: int, config: MatchConfig) -> None:
    """A-10：同种子 + 同决策 ⇒ 事件流逐字段相等（多 seed × 多配置穷举）。"""
    events_a = _run("m_repro", seed, config).event_log()
    events_b = _run("m_repro", seed, config).event_log()
    assert events_a == events_b


@pytest.mark.parametrize("seed", _SEEDS)
@pytest.mark.parametrize("config", _CONFIGS, ids=["p4-base", "p2-base", "p6-toggles"])
def test_stream_replay_rebuilds_and_verifies(
    tmp_path: Path, seed: int, config: MatchConfig
) -> None:
    """A-10 / 05 §2.2：权威流 → 重放重建 → 事件逐字段一致（verified）。"""
    match = _run("m_resume", seed, config, tmp_path=tmp_path)
    assert match.status is MatchStatus.ENDED
    stream = tmp_path / "m_resume" / "stream.jsonl"
    roster = [ConservativeBot(f"bot{i}") for i in range(config.player_count)]
    result = resume_match(stream, roster)
    assert result.verified, "重放重建的事件流必须与权威流逐字段一致"
    assert result.match.status is MatchStatus.ENDED
    assert result.match.scores == match.scores


def test_stream_replay_mid_match_suspends_and_continues(tmp_path: Path) -> None:
    """宿主中途重启（真·中局截断）：重建停在截断点（SUSPENDED），恢复后继续到终局。

    bot 决策是视图的确定性函数 ⇒ 截断前的决策逐字重放、截断后续局与原局
    同构 ⇒ 终局积分一致（A-10 的续局推论）。
    """
    config = MatchConfig(end_threshold=10_000, max_rounds=50)
    roster = [ConservativeBot(f"bot{i}") for i in range(config.player_count)]
    stream = tmp_path / "m_mid" / "stream.jsonl"
    stream.parent.mkdir(parents=True)
    match = Match.create("m_mid", config, roster, seed=5, stream_path=stream)
    match.run_to_end()
    assert match.status is MatchStatus.ENDED
    # 截断权威流到约 40% 行数（行边界截断，模拟宿主崩溃时刻）
    lines = stream.read_text(encoding="utf-8").splitlines()
    cut = max(2, int(len(lines) * 0.4))
    truncated = tmp_path / "m_mid" / "truncated.jsonl"
    truncated.write_text("\n".join(lines[:cut]) + "\n", encoding="utf-8", newline="")
    result = resume_match(truncated, roster)
    assert result.match.status is MatchStatus.SUSPENDED
    assert any(
        event.payload["reason"] == "replay_exhausted"
        for event in result.match.event_log()
        if event.type == EventType.MATCH_STATE_CHANGED
    )
    result.match.resume()
    result.match.run_to_end()
    assert result.match.status is MatchStatus.ENDED
    assert result.match.scores == match.scores  # 续局与原局同构


class _ViewRecorder(ConservativeBot):
    """记录每次 decide 收到视图的机器人（信息隔离取证用）。"""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.views: list[PlayerView] = []

    def decide(self, view: PlayerView) -> Decision:
        self.views.append(view)
        return super().decide(view)


def test_information_isolation_every_view(tmp_path: Path) -> None:
    """02 §5：任意玩家视图不含他人手牌与种子（全决策点穷举取证）。

    断言：①视图 my_hand == 该座位最新 HandShaken 骰面（HandObserved 同源）；
    ②视图字段集不含他人手牌/种子载体；③视图 JSON 化不含其他座位的完整手牌
    五元组（以最新 HandShaken 的骰面序列为指纹）。
    """
    config = MatchConfig(end_threshold=60, max_rounds=200)
    roster = [_ViewRecorder(f"bot{i}") for i in range(config.player_count)]
    stream = tmp_path / "m_iso" / "stream.jsonl"
    stream.parent.mkdir(parents=True)
    match = Match.create("m_iso", config, roster, seed=31, stream_path=stream)
    match.run_to_end()
    events = match.event_log()
    assert EventType.MATCH_ENDED in [e.type for e in events]
    # 按局号配对（视图在决策时刻的手牌 = 该局最新 HandShaken）
    latest_hand: dict[tuple[int, int], tuple[int, ...]] = {}
    round_no = 0
    for event in events:
        if event.type == EventType.ROUND_STARTED:
            round_no = int(event.payload["round_no"])
        if event.type == EventType.HAND_SHAKEN:
            seat = int(event.payload["seat"])
            latest_hand[(round_no, seat)] = tuple(int(f) for f in event.payload["dice"])
    assert latest_hand, "必须有私密手牌事件"
    recorded_views: list[PlayerView] = []
    for player in roster:
        recorded_views.extend(player.views)
    assert len(recorded_views) >= 4, "必须覆盖多个决策点"
    view_seats = {view.my_seat for view in recorded_views}
    assert view_seats == set(range(config.player_count))
    for view in recorded_views:
        # ① 本人手牌与该局最新 HandShaken 一致
        assert view.my_hand == latest_hand[(view.round_no, view.my_seat)]
        # ② 结构面：视图不含他人手牌集合与种子
        from dataclasses import fields as dc_fields

        names = {f.name for f in dc_fields(PlayerView)}
        assert "hands" not in names and "seed" not in names
        # ③ 其他座位最新手牌序列不得出现在视图 JSON 中
        import json as _json

        blob = _json.dumps(
            {
                "bid_history": [
                    [b.seat, b.kind.value, b.bid.count, int(b.bid.face), b.quote]
                    for b in view.bid_history
                ],
                "scores": list(view.scores),
                "current_bid": None
                if view.current_bid is None
                else [view.current_bid.count, int(view.current_bid.face)],
            },
            ensure_ascii=False,
        )
        for (hand_round, seat), dice in latest_hand.items():
            if seat == view.my_seat and hand_round == view.round_no:
                continue
            assert str(list(dice)) not in blob
    # ④ 种子不进任何视图（结构断言由 ② 承担；此处再证事件层：种子只在私密层）
    private_seed_events = [e for e in events if e.type == EventType.SEED_RECORDED]
    assert private_seed_events and private_seed_events[0].visibility.value == "private"
    decision_facts = [e for e in events if e.type == EventType.DECISION_FACTS]
    assert decision_facts and all(e.visibility.value == "eval" for e in decision_facts)


def test_decision_facts_are_eval_layer_only() -> None:
    """三层纪律（02 §5.2）：DecisionFacts 只进评测层；HandShaken 只进私密层。"""
    match = _run("m_layers", 3, MatchConfig(end_threshold=40, max_rounds=100))
    for event in match.event_log():
        if event.type == EventType.DECISION_FACTS:
            assert event.visibility.value == "eval"
        if event.type == EventType.HAND_SHAKEN:
            assert event.visibility.value == "private"
        if event.type in (
            EventType.BID_MADE,
            EventType.CHALLENGE_MADE,
            EventType.RESPONDED,
            EventType.REVEALED,
            EventType.ROUND_SETTLED,
        ):
            assert event.visibility.value == "public"
            assert "seed" not in event.payload


def test_extract_decisions_roundtrip_through_stream(tmp_path: Path) -> None:
    """评测层决策经权威流往返无损（重放重建的数据地基，G-8）。"""
    match = _run("m_rt", 17, MatchConfig(end_threshold=30, max_rounds=100), tmp_path=tmp_path)
    stream = tmp_path / "m_rt" / "stream.jsonl"
    decisions = extract_decisions(match.event_log())
    assert decisions
    from perudo.engine.stream import read_events

    assert extract_decisions(read_events(stream)) == decisions
