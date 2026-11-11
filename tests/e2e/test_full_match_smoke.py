"""P2 端到端冒烟（计划 §4.3 G-e2e）：脚本机器人全桌冒烟——开关各局 + 权威流 + 重放验证。

02 M2 验收：完整桌局跑通（重摇 / 应牌链 / 通杀 / 陪饮 / 天黑黑开关各局）；
05 §2.2：宿主重启重放重建成功。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from perudo.core.types import StraightPolicy
from perudo.engine.config import MatchConfig
from perudo.engine.events import EventType
from perudo.engine.match import Match
from perudo.engine.replay import resume_match
from perudo.engine.state import MatchStatus
from perudo.players.bot import ConservativeBot

_SCENARIOS: dict[str, MatchConfig] = {
    "baseline": MatchConfig(end_threshold=40, max_rounds=300, spectated=True),
    "darkness": MatchConfig(end_threshold=40, max_rounds=300).with_rules(darkness=True),
    "drink": MatchConfig(end_threshold=40, max_rounds=300).with_rules(drink_along=True),
    "counter_on_open": MatchConfig(end_threshold=40, max_rounds=300).with_rules(
        counter_on_open=True
    ),
    "all_red_eight": MatchConfig(end_threshold=40, max_rounds=300).with_rules(all_ones_eight=True),
    "straight_normal": MatchConfig(end_threshold=40, max_rounds=300).with_rules(
        straight=StraightPolicy.NORMAL
    ),
    "six_players": MatchConfig(end_threshold=40, max_rounds=300, player_count=6, spectated=True),
    "heads_up": MatchConfig(end_threshold=40, max_rounds=300, player_count=2),
}


@pytest.mark.parametrize("scenario", list(_SCENARIOS), ids=list(_SCENARIOS))
def test_bot_full_match_with_toggles(tmp_path: Path, scenario: str) -> None:
    """bot 自对弈完整桌局：终局、权威流落盘、重放重建逐字段一致。"""
    config = _SCENARIOS[scenario]
    roster = [ConservativeBot(f"bot{i}") for i in range(config.player_count)]
    stream = tmp_path / scenario / "stream.jsonl"
    stream.parent.mkdir(parents=True)
    match = Match.create(
        f"e2e_{scenario}", config, roster, seed=hash(scenario) % 10000, stream_path=stream
    )
    match.run_to_end()
    assert match.status is MatchStatus.ENDED
    events = match.event_log()
    # 事件面覆盖：叫骰、挑战、应牌、摊牌、结算、终局俱全
    required = {
        EventType.ROUND_STARTED,
        EventType.BID_MADE,
        EventType.CHALLENGE_MADE,
        EventType.RESPONDED,
        EventType.REVEALED,
        EventType.ROUND_SETTLED,
        EventType.MATCH_ENDED,
        EventType.HAND_SHAKEN,
        EventType.DECISION_FACTS,
    }
    present = {e.type for e in events}
    missing = required - present
    assert not missing, f"事件流缺类型：{missing}"
    # 三层纪律抽查
    assert all(e.visibility.value == "private" for e in events if e.type == EventType.HAND_SHAKEN)
    assert all(e.visibility.value == "eval" for e in events if e.type == EventType.DECISION_FACTS)
    # 权威流逐字节一致
    from perudo.engine.stream import read_events

    assert read_events(stream) == events
    # 重放重建（A-10 / 05 §2.2）
    result = resume_match(stream, roster)
    assert result.verified
    assert result.match.status is MatchStatus.ENDED
    assert result.match.scores == match.scores


def test_reroll_occurs_naturally_across_long_match(tmp_path: Path) -> None:
    """重摇子流程（R-08/R-09/R-60/R-65）：长局中散骰/顺色重摇自然发生并被记录。"""
    config = MatchConfig(end_threshold=200, max_rounds=2000, spectated=True)
    roster = [ConservativeBot(f"bot{i}") for i in range(config.player_count)]
    stream = tmp_path / "reroll" / "stream.jsonl"
    stream.parent.mkdir(parents=True)
    match = Match.create("e2e_reroll", config, roster, seed=777, stream_path=stream)
    match.run_to_end()
    rerolled = [e for e in match.event_log() if e.type == EventType.REROLLED]
    assert rerolled, "2000 局内散骰/顺色重摇必现（基线必重摇口径）"
    assert all(e.visibility.value == "public" for e in rerolled)
    reasons = {e.payload["reason"] for e in rerolled}
    assert reasons <= {"scattered", "straight", "stacked"}
    # 每座位重摇次数不越上限（R-65）
    from collections import Counter

    per_seat: Counter = Counter()
    for e in rerolled:
        per_seat[e.payload["seat"]] = max(per_seat[e.payload["seat"]], e.payload["times"])
    assert all(times <= 3 for times in per_seat.values())
    assert match.status is MatchStatus.ENDED


def test_match_state_changed_lifecycle_chain(tmp_path: Path) -> None:
    """生命周期事件链（05 §2.1）：RUNNING →（挂起/恢复）→ ENDED 全程可见。"""
    config = MatchConfig(end_threshold=40, max_rounds=300)
    roster = [ConservativeBot(f"bot{i}") for i in range(config.player_count)]
    stream = tmp_path / "lifecycle" / "stream.jsonl"
    stream.parent.mkdir(parents=True)
    match = Match.create("e2e_life", config, roster, seed=88, stream_path=stream)
    match.suspend()
    match.resume()
    match.run_to_end()
    chain = [
        e.payload["status"] for e in match.event_log() if e.type == EventType.MATCH_STATE_CHANGED
    ]
    assert chain[0] == "RUNNING"
    assert "SUSPENDED" in chain and chain.index("SUSPENDED") < chain.index("ENDED")
    assert chain[-1] == "ENDED"
    assert match.status is MatchStatus.ENDED
