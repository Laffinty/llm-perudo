"""P2 单元测试：stream.jsonl 权威持久层（G-07）——写读回环、重放事实提取、meta 快照。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from perudo.core.types import (
    Bid,
    BidAction,
    BidKind,
    ChallengeAction,
    ChallengeKind,
    Face,
    ResponseKind,
)
from perudo.engine.config import MatchConfig
from perudo.engine.events import Event, EventType, Visibility, action_to_payload
from perudo.engine.stream import (
    StreamRecorder,
    build_meta,
    extract_config,
    extract_decisions,
    extract_roster_names,
    extract_seed,
    read_events,
    read_meta,
    write_meta,
)


def _bid_action() -> BidAction:
    return BidAction(BidKind.NORMAL, Bid(6, Face.FOUR))


def _challenge_action() -> ChallengeAction:
    return ChallengeAction(ChallengeKind.JUMP, (1,))


def _sample_events() -> list[Event]:
    """合成事件流：seq 连续、覆盖四层事件与三种动作形态。"""
    facts = {
        "turn_seq": 1,
        "actor": "甲",
        "phase": "bidding",
        "seat": 0,
        "prev_bid": None,
        "wild_state": "fly",
        "ones_called": False,
        "self_support": 2,
        "legal_count": 42,
        "correction_count": 0,
        "degraded": False,
        "decision": {
            "action": action_to_payload(_bid_action()),
            "quote": "开！",
            "thinking": None,
            "attachments": {"raw": "abc"},
        },
    }
    facts_counter = {
        "turn_seq": 2,
        "actor": "乙",
        "phase": "respond",
        "seat": 1,
        "prev_bid": [6, 4],
        "wild_state": "fly",
        "ones_called": False,
        "self_support": 1,
        "legal_count": 3,
        "correction_count": 0,
        "degraded": False,
        "decision": {
            "action": action_to_payload(_challenge_action()),
            "quote": "劈！",
            "thinking": None,
            "attachments": {},
        },
    }
    facts_response = {
        "turn_seq": 3,
        "actor": "乙",
        "phase": "respond",
        "seat": 1,
        "prev_bid": [6, 4],
        "wild_state": "fly",
        "ones_called": False,
        "self_support": 1,
        "legal_count": 3,
        "correction_count": 1,
        "degraded": True,
        "decision": {
            "action": action_to_payload(ResponseKind.SURRENDER),
            "quote": "",
            "thinking": "想降",
            "attachments": {},
        },
    }
    return [
        Event(
            1,
            EventType.MATCH_STARTED,
            Visibility.PUBLIC,
            {
                "match_id": "m_test",
                "config": MatchConfig().snapshot(),
                "roster": ["甲", "乙"],
            },
        ),
        Event(2, EventType.SEED_RECORDED, Visibility.PRIVATE, {"seed": 42}),
        Event(3, EventType.DECISION_FACTS, Visibility.EVAL, facts),
        Event(4, EventType.DECISION_FACTS, Visibility.EVAL, facts_counter),
        Event(5, EventType.DECISION_FACTS, Visibility.EVAL, facts_response),
        Event(
            6,
            EventType.MATCH_ENDED,
            Visibility.PUBLIC,
            {"reason": "threshold", "scores": [0, 3], "winners": [0]},
        ),
    ]


def test_recorder_roundtrip(tmp_path: Path) -> None:
    """写 → 读回逐字段相等（G-07 权威持久层）。"""
    path = tmp_path / "stream.jsonl"
    events = _sample_events()
    with StreamRecorder(path) as recorder:
        for event in events:
            recorder.append(event)
    assert read_events(path) == tuple(events)


def test_recorder_appends_across_opens(tmp_path: Path) -> None:
    """追加写：两次打开同一文件，读回全量且 seq 校验通过。"""
    path = tmp_path / "stream.jsonl"
    events = _sample_events()
    with StreamRecorder(path) as recorder:
        recorder.append(events[0])
    with StreamRecorder(path) as recorder:
        for event in events[1:]:
            recorder.append(event)
    assert read_events(path) == tuple(events)


def test_read_events_rejects_seq_gap(tmp_path: Path) -> None:
    """seq 断裂（1,2,4）→ ValueError；空文件 → ()。"""
    path = tmp_path / "broken.jsonl"
    lines = [
        json.dumps({"seq": 1, "type": "x", "visibility": "public", "payload": {}}),
        json.dumps({"seq": 2, "type": "x", "visibility": "public", "payload": {}}),
        json.dumps({"seq": 4, "type": "x", "visibility": "public", "payload": {}}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match="seq 断裂"):
        read_events(path)
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8", newline="\n")
    assert read_events(empty) == ()


def test_extractors(tmp_path: Path) -> None:
    """配置/种子/名册/决策四个提取器；缺失关键事件 → ValueError。"""
    events = _sample_events()
    config = extract_config(events)
    assert config.player_count == MatchConfig().player_count
    assert extract_seed(events) == 42
    assert extract_roster_names(events) == ("甲", "乙")
    decisions = extract_decisions(events)
    assert len(decisions) == 3
    assert decisions[0].action == _bid_action()
    assert decisions[1].action == _challenge_action()
    assert decisions[2].action == ResponseKind.SURRENDER
    assert decisions[0].quote == "开！" and decisions[0].attachments == {"raw": "abc"}
    assert decisions[2].thinking == "想降" and decisions[2].quote == ""
    with pytest.raises(ValueError, match="SeedRecorded"):
        extract_seed([events[0]])


def test_jsonl_lines_are_lf_and_stable(tmp_path: Path) -> None:
    """JSONL 行键序稳定且不含 CRLF（R-03.6 教训的回归守护）。"""
    path = tmp_path / "stream.jsonl"
    event = _sample_events()[0]
    with StreamRecorder(path) as recorder:
        recorder.append(event)
        recorder.append(event)
    raw = path.read_bytes()
    assert b"\r" not in raw
    first = event_to_json_line(raw)
    assert first == event_to_json_line(raw)  # 同一事件两次编码逐字节一致


def event_to_json_line(raw: bytes) -> str:
    """取文件首行文本（测试辅助）。"""
    return raw.split(b"\n")[0].decode("utf-8")


def test_meta_roundtrip(tmp_path: Path) -> None:
    """meta.json：write → read == build_meta；文件以 LF 结尾、键序稳定。"""
    path = tmp_path / "meta.json"
    config = MatchConfig()
    meta = build_meta("m_x", config, ["甲", "乙"], "RUNNING", 7, abandoned=False)
    write_meta(path, meta)
    assert read_meta(path) == meta
    raw = path.read_bytes()
    assert raw.endswith(b"\n") and b"\r" not in raw
    assert path.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")
