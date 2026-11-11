"""从 stream.jsonl 重放重建与逐字段验证（05 §2.2，A-10）。

宿主重启路径：``stream.jsonl``（权威持久层）携带种子 + 决策全量 ⇒ 引擎重放
重建 ⇒ 事件流逐字段重现 ⇒ 桌局转 SUSPENDED 等待恢复。重放期间不调用玩家、
不写流；``verified`` 标记重生成事件流与记录流是否逐字段一致（争议仲裁 /
内核回归的依据）。

注：若原局在终局前被挂起/弃局，重建停在最后一个决策点（SUSPENDED）；此时
记录流含宿主操作事件（挂起/弃局），``verified`` 只对引擎叙事成立——用
``replay.verify_events`` 自选比较窗口。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from perudo.engine.events import Event
from perudo.engine.match import Match
from perudo.engine.stream import (
    extract_config,
    extract_decisions,
    extract_match_id,
    extract_seed,
    read_events,
)
from perudo.players.base import Player

__all__ = ["ReplayResult", "resume_match", "replay_decisions"]


@dataclass
class ReplayResult:
    """重放重建结果。"""

    match: Match
    #: 重生成事件流与记录流逐字段一致（A-10）
    verified: bool
    recorded: tuple[Event, ...]


def resume_match(stream_path: Path, roster: Sequence[Player]) -> ReplayResult:
    """从权威流重建桌局：重放全部已记录决策后转 SUSPENDED，等待宿主恢复。

    ``roster`` 为重建后的玩家对象（名字须与名册一致——事件署名依赖它）；
    重建后 ``result.match.resume()`` + ``run_to_end()`` 即可用真实玩家继续。
    """
    events = read_events(stream_path)
    match = replay_decisions(
        match_id=extract_match_id(events),
        events=events,
        roster=roster,
    )
    verified = match.event_log() == events
    return ReplayResult(match=match, verified=verified, recorded=events)


def replay_decisions(
    *,
    match_id: str,
    events: Sequence[Event],
    roster: Sequence[Player],
) -> Match:
    """按事件流中记录的配置/种子/决策重放一局（不写流、不调用玩家 decide）。"""
    match = Match.create(
        match_id,
        extract_config(events),
        roster,
        seed=extract_seed(events),
        decision_log=extract_decisions(events),
    )
    match.run_to_end()
    return match
