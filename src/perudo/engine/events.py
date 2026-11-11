"""事件流与三层记录（02 §5.1 / 05 §4.1）。

事件流是引擎对外的唯一叙述（A-10b）。三层纪律：

- **公开层**（``PUBLIC``）：界面 / 复盘 / AI 评述可见——永不含未开盅手牌与种子；
- **私密层**（``PRIVATE``）：引擎与最终复盘档案——手牌、种子；
- **评测层**（``EVAL``）：决策时刻私有事实（05 §5.4 / G-8）——永不进任何玩家上下文。

载荷一律为 JSON 基元（dict/list/str/int/bool/None；Fraction 以 ``[分子, 分母]``
编码）。事件不参与哈希；逐字段一致（A-10）以 ``==`` 比较。

事件类型总表（``*`` = 相对 02 §5.1 的新增，已登记计划 R-04，契约 A-20 只增不删）：

| 类型 | 层 | 载荷要点 |
| --- | --- | --- |
| MatchStarted | 公开 | match_id、config 快照、roster 名册 |
| SeedRecorded* | 私密 | seed（宿主重启重放重建依赖，05 §2.2） |
| MatchStateChanged* | 公开 | match_id、status、reason（05 G-01） |
| RoundStarted | 公开 | round_no、caller |
| HandShaken | 私密 | seat、dice |
| HandObserved* | 公开 | seat、dice、leopard_flag（仅纯 EVE 桌，05 G-01） |
| Rerolled | 公开 | seat、reason、times |
| ThinkingObserved* | 公开 | seat、thinking_text（仅纯 EVE 桌，05 G-01） |
| BidMade | 公开 | seat、kind、count、face、quote |
| ChallengeMade | 公开 | seat、kind、targets、base_multiplier |
| Responded | 公开 | seat、choice、quote、declared_target |
| Revealed | 公开 | hands、judgments、darkness |
| RoundSettled | 公开 | entries、scores、next_caller |
| TurnDegraded | 公开 | seat、reason、action |
| DecisionFacts* | 评测 | 05 §5.4 全字段 + decision 全量（重放重建依赖） |
| MatchEnded | 公开 | reason、scores、winners |
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from typing import Any

from perudo.core.types import (
    Bid,
    BidAction,
    BidKind,
    ChallengeAction,
    ChallengeKind,
    Face,
    ResponseKind,
)

__all__ = [
    "Event",
    "EventType",
    "Visibility",
    "frac_pair",
    "bid_pair",
    "action_to_payload",
    "action_from_payload",
    "event_to_json",
    "event_from_json",
]


class Visibility(Enum):
    """三层记录可见性（02 §5.2）。"""

    PUBLIC = "public"
    PRIVATE = "private"
    EVAL = "eval"


class EventType:
    """事件类型常量（载荷要点见模块 docstring 总表）。"""

    MATCH_STARTED = "MatchStarted"
    SEED_RECORDED = "SeedRecorded"
    MATCH_STATE_CHANGED = "MatchStateChanged"
    ROUND_STARTED = "RoundStarted"
    ROUND_SETTLED = "RoundSettled"
    HAND_SHAKEN = "HandShaken"
    HAND_OBSERVED = "HandObserved"
    REROLLED = "Rerolled"
    THINKING_OBSERVED = "ThinkingObserved"
    BID_MADE = "BidMade"
    CHALLENGE_MADE = "ChallengeMade"
    RESPONDED = "Responded"
    REVEALED = "Revealed"
    TURN_DEGRADED = "TurnDegraded"
    DECISION_FACTS = "DecisionFacts"
    MATCH_ENDED = "MatchEnded"


@dataclass(frozen=True)
class Event:
    """一条事件：全局序号 + 类型 + 可见性 + JSON 安全载荷。

    ``seq`` 从 1 起按发射顺序连续编号；重放逐字段一致（A-10）以 ``==`` 比较。
    ``payload`` 不得哈希（仅比较）。
    """

    seq: int
    type: str
    visibility: Visibility
    payload: dict[str, Any] = field(default_factory=dict)


def frac_pair(value: Fraction) -> list[int]:
    """Fraction → ``[分子, 分母]``（JSON 安全编码）。"""
    return [value.numerator, value.denominator]


def bid_pair(bid: Bid) -> list[int]:
    """Bid → ``[count, face]``（JSON 安全编码）。"""
    return [bid.count, int(bid.face)]


def action_to_payload(
    action: BidAction | ChallengeAction | ResponseKind,
) -> dict[str, Any]:
    """动作 → JSON 载荷（DecisionFacts / TurnDegraded 共用编解码，重放依赖）。

    三种形态：``{"t": "bid", "kind", "count", "face"}``、
    ``{"t": "challenge", "kind", "targets"}``、``{"t": "response", "kind"}``。
    """
    if isinstance(action, BidAction):
        return {
            "t": "bid",
            "kind": action.kind.value,
            "count": action.bid.count,
            "face": int(action.bid.face),
        }
    if isinstance(action, ChallengeAction):
        return {"t": "challenge", "kind": action.kind.value, "targets": list(action.targets)}
    if isinstance(action, ResponseKind):
        return {"t": "response", "kind": action.value}
    raise TypeError(f"未知动作类型：{type(action).__name__}")


def action_from_payload(payload: dict[str, Any]) -> BidAction | ChallengeAction | ResponseKind:
    """``action_to_payload`` 的逆变换（重放重建决策用）。"""
    tag = str(payload["t"])
    if tag == "bid":
        return BidAction(
            BidKind(str(payload["kind"])), Bid(int(payload["count"]), Face(int(payload["face"])))
        )
    if tag == "challenge":
        return ChallengeAction(
            ChallengeKind(str(payload["kind"])),
            tuple(int(t) for t in payload["targets"]),
        )
    if tag == "response":
        return ResponseKind(str(payload["kind"]))
    raise ValueError(f"未知动作载荷标记：{tag!r}")


def event_to_json(event: Event) -> str:
    """单事件 → JSONL 行（键序稳定，保证逐字节可复现）。"""
    record = {
        "seq": event.seq,
        "type": event.type,
        "visibility": event.visibility.value,
        "payload": event.payload,
    }
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def event_from_json(line: str) -> Event:
    """JSONL 行 → 单事件（重放恢复用）。"""
    record = json.loads(line)
    return Event(
        seq=int(record["seq"]),
        type=str(record["type"]),
        visibility=Visibility(str(record["visibility"])),
        payload=dict(record["payload"]),
    )
