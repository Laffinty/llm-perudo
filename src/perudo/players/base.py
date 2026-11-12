"""玩家接口契约（统一规格，02 §4 / 05 §4.3 字段定稿）。

本模块是引擎与一切玩家实现（LLM 适配器 / 人类界面 / 脚本机器人）之间的
唯一接口面：**字段可增不可删**（A-20），玩家无差别（A-09）——引擎不感知
对方是人、是 LLM 还是脚本。

依赖方向：本模块只 import core（规则内核契约），是引擎与玩家的共享层
（计划 §2.2：`players/` = 玩家契约 + 保守机器人）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from perudo.core.types import (
    Bid,
    BidAction,
    BidKind,
    ChallengeAction,
    Face,
    ResponseKind,
    ZhaiState,
)

__all__ = [
    "ChainPosition",
    "Decision",
    "Phase",
    "Player",
    "PlayerView",
    "SignedBid",
    "action_in_legal",
]


class Phase(Enum):
    """决策阶段（02 §4.1：叫骰轮 / 应牌链）。"""

    BIDDING = "bidding"
    RESPOND = "respond"


@dataclass(frozen=True)
class Decision:
    """玩家交回的决策（02 §4.1：动作 + 台词 + 不透明附件）。

    ``action`` 必须取自 ``PlayerView.legal_actions``（引擎据此校验）；
    ``thinking`` 为适配器剥离后的思考文本（04 F-06，仅纯 EVE 桌进观战流）；
    ``attachments`` 为不透明附件——引擎原样存档不解析（03 §4，A-06）。
    """

    action: BidAction | ChallengeAction | ResponseKind
    quote: str = ""
    thinking: str | None = None
    attachments: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SignedBid:
    """叫骰流水条目（署名 + 动作 + 台词，公开层）。"""

    seat: int
    kind: BidKind
    bid: Bid
    quote: str


@dataclass(frozen=True)
class ChainPosition:
    """应牌链位置（05 §4.3 `chain_position`，仅 RESPOND 阶段非空）。"""

    initiator: int
    kind: str  # ChallengeKind.value
    #: 当前链上倍数（×1 → ×2 → ×4 → ×8）
    stake_numerator: int
    stake_denominator: int
    contested_bid: Bid
    can_reveal: bool
    can_counter: bool
    can_recounter: bool
    can_surrender: bool


@dataclass(frozen=True)
class PlayerView:
    """引擎 → 玩家的私有视图（02 §4.1 + 05 §4.3 字段定稿）。

    **不含**他人手牌、种子与任何他人私有信息——信息隔离的唯一出口纪律由
    ``engine.views.build_view`` 落实（02 §5）。
    """

    match_id: str
    round_no: int
    phase: Phase
    my_seat: int
    player_count: int
    my_hand: tuple[Face, ...]
    bid_history: tuple[SignedBid, ...]
    wild_state: ZhaiState
    ones_called: bool
    current_bid: Bid | None
    legal_actions: tuple[BidAction | ChallengeAction | ResponseKind, ...]
    scores: tuple[int, ...]
    chain_position: ChainPosition | None
    #: 非法动作被驳回后的纠错提示（第 n 次重提交；首次提交为空串，02 §4.3）
    correction_reason: str = ""


@runtime_checkable
class Player(Protocol):
    """玩家接口（统一规格，A-09）：引擎同步调用，返回一个决策。"""

    @property
    def name(self) -> str:
        """玩家名（名册与事件署名用，同一桌内唯一）。"""
        ...

    def decide(self, view: PlayerView) -> Decision:
        """给定私有视图，返回一个决策（动作须取自合法动作集）。"""
        ...


def action_in_legal(
    action: BidAction | ChallengeAction | ResponseKind,
    legal: tuple[BidAction | ChallengeAction | ResponseKind, ...],
) -> bool:
    """动作是否属于合法动作集（挑战目标按**集合语义**比较，R-29~R-32）。

    契约级判等：引擎驳回（match.py）与适配器自检（B-04）共用同一实现，
    保证"自检通过 ⇒ 引擎必然接受"。
    """
    from perudo.core.types import ChallengeAction as _CA

    for candidate in legal:
        if isinstance(action, _CA) and isinstance(candidate, _CA):
            if action.kind is candidate.kind and frozenset(action.targets) == frozenset(
                candidate.targets
            ):
                return True
            continue
        if action == candidate:
            return True
    return False
