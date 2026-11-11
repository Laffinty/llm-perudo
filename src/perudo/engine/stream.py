"""stream.jsonl 权威持久层（05 §3，G-07）。

``stream.jsonl`` 是唯一权威：重放恢复、评测统计、复盘档生成全部从它派生。
本模块提供追加写器、读回校验、重放事实提取与 meta.json 快照。

行尾纪律：所有写文件显式 ``newline="\\n"``——Windows 默认翻译会把 LF 改写为
CRLF，污染权威持久层（P1 教训 R-03.6）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from perudo.engine.config import MatchConfig
from perudo.engine.events import (
    Event,
    EventType,
    action_from_payload,
    event_from_json,
    event_to_json,
)
from perudo.players.base import Decision

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "StreamRecorder",
    "read_events",
    "extract_match_id",
    "extract_config",
    "extract_seed",
    "extract_roster_names",
    "extract_decisions",
    "build_meta",
    "write_meta",
    "read_meta",
]


class StreamRecorder:
    """JSONL 追加写器（权威持久层，G-07）。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle = path.open("a", encoding="utf-8", newline="\n")

    def append(self, event: Event) -> None:
        self._handle.write(event_to_json(event))
        self._handle.write("\n")
        self._handle.flush()

    def flush(self) -> None:
        self._handle.flush()

    def close(self) -> None:
        if not self._handle.closed:
            self._handle.close()

    def __enter__(self) -> StreamRecorder:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def read_events(path: Path) -> tuple[Event, ...]:
    """读回事件流并校验 seq 从 1 起严格连续；空文件返回 ()。"""
    events: list[Event] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            events.append(event_from_json(stripped))
    for index, event in enumerate(events, start=1):
        if event.seq != index:
            raise ValueError(
                f"事件流 seq 断裂：第 {index} 条应为 seq={index}，实际 seq={event.seq}"
            )
    return tuple(events)


def _first_of_type(events: Sequence[Event], event_type: str) -> Event:
    for event in events:
        if event.type == event_type:
            return event
    raise ValueError(f"事件流缺少 {event_type}，无法提取")


def extract_match_id(events: Sequence[Event]) -> str:
    """从 MatchStarted 取 match_id。"""
    started = _first_of_type(events, EventType.MATCH_STARTED)
    return str(started.payload["match_id"])


def extract_config(events: Sequence[Event]) -> MatchConfig:
    """从 MatchStarted 的配置快照重建 MatchConfig（重放恢复依赖）。"""
    started = _first_of_type(events, EventType.MATCH_STARTED)
    return MatchConfig.from_snapshot(dict(started.payload["config"]))


def extract_seed(events: Sequence[Event]) -> int:
    """从 SeedRecorded（私密层）取种子（宿主重启重放重建依赖）。"""
    recorded = _first_of_type(events, EventType.SEED_RECORDED)
    return int(recorded.payload["seed"])


def extract_roster_names(events: Sequence[Event]) -> tuple[str, ...]:
    """从 MatchStarted 取名册名列表。"""
    started = _first_of_type(events, EventType.MATCH_STARTED)
    return tuple(str(name) for name in started.payload["roster"])


def extract_decisions(events: Sequence[Event]) -> tuple[Decision, ...]:
    """从 DecisionFacts（评测层）按序重建决策全量（重放重建依赖）。"""
    decisions: list[Decision] = []
    for event in events:
        if event.type != EventType.DECISION_FACTS:
            continue
        decision_payload = dict(event.payload["decision"])
        raw_attachments = dict(decision_payload.get("attachments", {}))
        decisions.append(
            Decision(
                action=action_from_payload(dict(decision_payload["action"])),
                quote=str(decision_payload.get("quote", "")),
                thinking=_opt_str(decision_payload.get("thinking")),
                attachments={str(k): str(v) for k, v in raw_attachments.items()},
            )
        )
    return tuple(decisions)


def build_meta(
    match_id: str,
    config: MatchConfig,
    roster_names: Sequence[str],
    status: str,
    seed: int,
    *,
    abandoned: bool = False,
) -> dict[str, Any]:
    """meta.json 快照（05 §3：配置、名册、状态、种子、abandoned 标记）。"""
    return {
        "match_id": match_id,
        "config": config.snapshot(),
        "roster": list(roster_names),
        "status": status,
        "seed": seed,
        "abandoned": abandoned,
    }


def write_meta(path: Path, meta: Mapping[str, Any]) -> None:
    """写 meta.json（键序稳定、UTF-8、LF 行尾）。"""
    text = json.dumps(dict(meta), ensure_ascii=False, sort_keys=True, indent=2)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def read_meta(path: Path) -> dict[str, Any]:
    """读 meta.json。"""
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)
