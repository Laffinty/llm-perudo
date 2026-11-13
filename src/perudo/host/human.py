"""人类席桥（PVE，05 §4.2 POST /action 的落地；W1 建桥、W2 前端接线）。

引擎同步调用 ``decide``——桥以线程事件等待宿主 POST 的动作；等待期广播
``ActionRequired``（宿主提示消息，非引擎事件，04 §1"宿主只有界面文案"）。
等待超时上抛 → 引擎故障政策兜底（A-15：代打 + 降级）。
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from perudo.core.types import Face, ResponseKind
from perudo.engine.events import action_from_payload
from perudo.players.base import Decision, Player, PlayerView

__all__ = ["HostHumanPlayer", "HumanSeatTimeout"]

_WAIT_TIMEOUT_S = 600.0


class HumanSeatTimeout(Exception):
    """人类席等待动作超时（交引擎故障政策）。"""


class HostHumanPlayer(Player):
    """PVE 人类席：decide 阻塞等待前端动作，submit 由 REST 注入。"""

    def __init__(self, name: str, seat: int, on_action_required: Callable[[PlayerView], None] | None = None) -> None:
        self._name = name
        self._seat = seat
        self._on_action_required = on_action_required  # 回调：广播 ActionRequired
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._decision: Decision | None = None
        self._pending_view: PlayerView | None = None
        self._error: str | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def seat(self) -> int:
        return self._seat

    @property
    def pending_view(self) -> PlayerView | None:
        """当前等待动作的视图（断线恢复：REST 可查）。"""
        return self._pending_view

    def decide(self, view: PlayerView) -> Decision:
        with self._lock:
            self._pending_view = view
            self._decision = None
            self._error = None
            self._event.clear()
        if self._on_action_required is not None:
            self._on_action_required(view)
        if not self._event.wait(timeout=_WAIT_TIMEOUT_S):
            raise HumanSeatTimeout(f"人类席 {self._seat} 等待动作超时（{_WAIT_TIMEOUT_S}s）")
        if self._error is not None:
            raise RuntimeError(self._error)
        assert self._decision is not None
        return self._decision

    def submit(self, action_payload: dict[str, object]) -> None:
        """REST 注入动作（engine.events 动作编码形态）；非法动作按引擎纠错路径走。"""
        try:
            action = action_from_payload(action_payload)
        except (KeyError, ValueError, TypeError) as error:
            with self._lock:
                self._error = f"动作载荷非法：{error}"
            self._event.set()
            return
        with self._lock:
            self._decision = Decision(action=action)
        self._event.set()

    def snapshot_pending(self) -> dict[str, object] | None:
        """视图快照（JSON 安全）供 REST 查询；无等待返回 None。"""
        view = self._pending_view
        if view is None:
            return None
        return {
            "seat": view.my_seat,
            "round_no": view.round_no,
            "phase": view.phase.value,
            "my_hand": [int(f) for f in view.my_hand],
            "current_bid": None
            if view.current_bid is None
            else [view.current_bid.count, int(view.current_bid.face)],
            "legal_actions": [_payload(a) for a in view.legal_actions],
            "correction_reason": view.correction_reason,
        }


def _payload(action: object) -> dict[str, object]:
    from perudo.engine.events import action_to_payload

    return action_to_payload(action)  # type: ignore[arg-type]
