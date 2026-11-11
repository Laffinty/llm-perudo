"""桌局/局/回合状态（02 §2 对象模型 + 05 §2 生命周期，G-03）。

``MatchState`` 是编排层的内部可变状态；对外只经 ``views.build_view`` 暴露
（信息隔离唯一出口，02 §5）。生命周期转移合法性在此强制（05 §2.1）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction

from perudo.core.types import Bid, CallState, ChallengeKind, Hand, LoserEntry
from perudo.engine.config import MatchConfig
from perudo.players.base import Phase, SignedBid

__all__ = ["ChainState", "MatchState", "MatchStatus", "transition_status"]


class MatchStatus(Enum):
    """桌局生命周期状态（05 §2.1 G-03）。"""

    DRAFT = "DRAFT"
    RUNNING = "RUNNING"
    SUSPENDED = "SUSPENDED"
    ENDED = "ENDED"
    ARCHIVED = "ARCHIVED"
    ABANDONED = "ABANDONED"


_TRANSITIONS: dict[MatchStatus, frozenset[MatchStatus]] = {
    MatchStatus.DRAFT: frozenset({MatchStatus.RUNNING, MatchStatus.ABANDONED}),
    MatchStatus.RUNNING: frozenset(
        {MatchStatus.SUSPENDED, MatchStatus.ENDED, MatchStatus.ABANDONED}
    ),
    MatchStatus.SUSPENDED: frozenset({MatchStatus.RUNNING, MatchStatus.ABANDONED}),
    MatchStatus.ENDED: frozenset({MatchStatus.ARCHIVED}),
    MatchStatus.ARCHIVED: frozenset(),
    MatchStatus.ABANDONED: frozenset(),
}


def transition_status(current: MatchStatus, target: MatchStatus) -> MatchStatus:
    """校验并返回目标状态；非法转移抛 ``ValueError``（05 §2.1，计划 §4.2 属性）。"""
    if target not in _TRANSITIONS[current]:
        raise ValueError(f"非法生命周期转移：{current.value} → {target.value}（05 §2.1）")
    return target


@dataclass
class ChainState:
    """应牌链子状态机（02 §2.4.2）。

    多目标挑战（连杀/通杀）逐目标持有倍数与被挑战叫骰（分别结算，R-51）；
    反杀/再反杀（D-06 同链升级口径）把**当前 battle 目标**的倍数沿
    ×1 → ×2 跳杀 → ×4 反杀 → ×8 再反杀阶梯翻倍。``awaiting`` 为待决策座位
    （目标或反杀后的原杀者）；``counter_focus`` 为反杀战所涉目标。
    """

    initiator: int
    kind: ChallengeKind
    targets: tuple[int, ...]  # 应牌顺序（全量；以 responses 判定待应牌者）
    stakes: dict[int, Fraction] = field(default_factory=dict)  # seat → 当前倍数
    contested_bids: dict[int, Bid] = field(default_factory=dict)  # seat → 被挑战叫骰
    awaiting: int = -1  # 待决策座位
    responses: dict[int, str] = field(default_factory=dict)  # seat → ResponseKind.value
    countered: bool = False
    counter_focus: int | None = None
    recounter_declared: int | None = None

    def next_pending(self) -> int | None:
        """下一个待应牌目标（应牌顺序）；全部应牌完毕返回 ``None``。"""
        for seat in self.targets:
            if seat not in self.responses:
                return seat
        return None


@dataclass
class MatchState:
    """编排层内部状态（02 §2.1 三层对象中的桌局 + 局）。

    纪律：``hands`` 与种子永不进 ``views`` 以外的一切对外出口；本类型不感知
    "玩家是什么"（02 A-09）。
    """

    match_id: str
    config: MatchConfig
    status: MatchStatus = MatchStatus.DRAFT
    scores: list[int] = field(default_factory=list)  # 按座位
    round_no: int = 0
    caller: int = 0  # 本局起叫者
    hands: dict[int, Hand] = field(default_factory=dict)
    reroll_counts: dict[int, int] = field(default_factory=dict)
    disqualified: set[int] = field(default_factory=set)  # 重摇超限判负（跳过本局行动）
    call_state: CallState = field(default_factory=CallState.initial)
    current_bid: Bid | None = None
    bid_history: list[SignedBid] = field(default_factory=list)
    last_callers: list[int] = field(default_factory=list)  # 本局叫骰流水
    phase: Phase = Phase.BIDDING
    chain: ChainState | None = None
    round_entries: list[LoserEntry] = field(default_factory=list)  # 本局累积（含重摇判负、陪饮）
    turn_seq: int = 0  # 决策回合序（评测层 G-8）
    end_reason: str | None = None  # threshold / max_rounds（MatchEnded 载荷）
