"""桌局管理器（04 §1）：创建/驱动/扇出/LOG——宿主是管道，不是裁判。

扇出纪律（F-02）：观战流仅纯 EVE 桌（= 公开层全部）；玩家流 = 公开层 +
本人 HandShaken；评测层事件（DecisionFacts）不进任何呈现流（05 §4.1）。
"""

from __future__ import annotations

import dataclasses
import datetime
import random
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from perudo.engine.config import MatchConfig
from perudo.engine.events import Event, Visibility
from perudo.engine.match import Match
from perudo.adapters.sdk.player import LLMPlayer
from perudo.host.human import HostHumanPlayer
from perudo.host.logwriter import MatchLogWriter
from perudo.players.base import Player
from perudo.players.bot import ConservativeBot

__all__ = ["MatchHandle", "MatchManager", "MatchNotFoundError"]


class MatchNotFoundError(KeyError):
    pass


@dataclass
class _Subscriber:
    role: str
    wake: threading.Event
    queue: list[Event]


@dataclass
class MatchHandle:
    """一桌运行中桌局的宿主侧全部状态。"""

    match_id: str
    match: Match
    mode: str  # eve / pve
    events: list[Event] = field(default_factory=list)  # 全量缓存（G-02 补发）
    log_writer: MatchLogWriter | None = None
    log_path: Path | None = None
    human: HostHumanPlayer | None = None
    subscribers: list[_Subscriber] = field(default_factory=list)
    thread: threading.Thread | None = None
    created_at: str = ""

    def snapshot(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "mode": self.mode,
            "status": self.match.status.value,
            "round_no": self.match.round_no,
            "scores": list(self.match.scores),
            "event_count": len(self.events),
            "log_path": str(self.log_path) if self.log_path else None,
            "created_at": self.created_at,
        }


class MatchManager:
    """桌局管理器：创建（冻结配置）→ 后台线程驱动 → 实时扇出 + LOG。"""

    def __init__(self, data_root: Path) -> None:
        self._data_root = data_root
        self._matches: dict[str, MatchHandle] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ 查询
    def get(self, match_id: str) -> MatchHandle:
        handle = self._matches.get(match_id)
        if handle is None:
            raise MatchNotFoundError(match_id)
        return handle

    def list_matches(self) -> list[dict[str, Any]]:
        return [h.snapshot() for h in self._matches.values()]

    # ------------------------------------------------------------------ 创建
    def create_match(self, spec: dict[str, Any]) -> MatchHandle:
        """开桌：解析名册槽位 → 冻结配置 → 后台线程驱动（05 §4.2 POST /matches）。"""
        mode = str(spec.get("mode", "eve"))
        if mode not in ("eve", "pve"):
            raise ValueError("mode 须为 eve / pve（F-01/F-02）")
        slots: list[dict[str, Any]] = list(spec.get("slots", []))
        if not slots:
            raise ValueError("slots 不得为空")
        if mode == "pve" and sum(1 for s in slots if s.get("kind") == "human") != 1:
            raise ValueError("PVE 恰需一席 human（F-01：人类席恒为 1）")
        if mode == "eve" and any(s.get("kind") == "human" for s in slots):
            raise ValueError("EVE 桌不得含人类席（F-02：观战流仅纯 EVE）")

        players: list[Player] = []
        human: HostHumanPlayer | None = None
        for index, slot in enumerate(slots):
            kind = str(slot.get("kind", "bot"))
            if kind == "bot":
                players.append(ConservativeBot(str(slot.get("name", f"bot{index}"))))
            elif kind == "human":
                human = HostHumanPlayer(str(slot.get("name", "人类")), index)
                players.append(human)
            elif kind == "llm":
                players.append(self._build_llm(slot, index))
            else:
                raise ValueError(f"未知席位类型：{kind}")

        cfg_overrides = dict(spec.get("config", {}))
        rules_overrides = dict(cfg_overrides.pop("rules", {}) or {})
        cfg_overrides.pop("player_count", None)  # 人数以名册槽位数为准（02 §6）
        base = MatchConfig(player_count=len(slots), **cfg_overrides)
        if rules_overrides:
            base = base.with_rules(**rules_overrides)
        if mode == "eve" and not base.spectated:
            base = dataclasses.replace(base, spectated=True)  # 观战投影事件（05 G-01）

        match_id = self._new_match_id(mode)
        match_dir = self._data_root / "matches" / match_id
        match_dir.mkdir(parents=True, exist_ok=True)
        stream_path = match_dir / "stream.jsonl"
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = match_dir / "log" / f"match_{stamp}_{mode}.log"

        handle = MatchHandle(
            match_id=match_id,
            match=None,  # type: ignore[arg-type]
            mode=mode,
            log_path=log_path,
            human=human,
            created_at=datetime.datetime.now().isoformat(timespec="seconds"),
        )
        handle.log_writer = MatchLogWriter(log_path)

        def sink(event: Event) -> None:
            # 宿主管道三件事：缓存（补发）、扇出（WS）、LOG（落盘）——不改写不补叙事
            with self._lock:
                handle.events.append(event)
                subscribers = list(handle.subscribers)
            if handle.log_writer is not None:
                handle.log_writer.append(event)
            for sub in subscribers:
                if self._visible(event, sub.role):
                    sub.queue.append(event)
                    sub.wake.set()

        match = Match.create(
            match_id,
            base,
            players,
            seed=int(spec.get("seed", random.randint(0, 2**63 - 1))),
            stream_path=stream_path,
            event_sink=sink,
        )
        handle.match = match
        with self._lock:
            self._matches[match_id] = handle
        self._start_thread(handle)
        return handle

    def _build_llm(self, slot: dict[str, Any], index: int) -> LLMPlayer:
        from perudo.adapters.deepseek import make_player as make_deepseek
        from perudo.adapters.glm import make_player as make_glm
        from perudo.adapters.sdk.config import AdapterConfig, PersonaConfig, QuoteConfig, default_base_url

        provider = str(slot.get("provider", ""))
        factories = {"deepseek": make_deepseek, "glm": make_glm}
        factory = factories.get(provider)
        if factory is None:
            raise ValueError(f"provider {provider} 未接入（P3：deepseek/glm；M4b：其余）")
        base_url = str(slot.get("base_url") or "") or default_base_url(provider)
        cfg = AdapterConfig(
            provider=provider,
            model=str(slot.get("model", "")),
            api_key_ref=str(slot.get("api_key_ref", "env:PERUDO_API_KEY")),
            base_url=base_url,
            persona=PersonaConfig(
                name=str(slot.get("persona_name", f"LLM{index}")),
                style=str(slot.get("persona_style", "")),
                trash_talk=int(slot.get("trash_talk", 1)),
            ),
            quote=QuoteConfig(
                enabled=bool(slot.get("quote_enabled", True)),
                trash_talk=int(slot.get("trash_talk", 1)),
            ),
            thinking=str(slot.get("thinking", "auto")),
            timeout_ms=int(slot.get("timeout_ms", 60_000)),
            legal_actions_presentation=str(slot.get("legal_actions_presentation", "constraints")),
            context_presentation=str(slot.get("context_presentation", "summary")),
        )
        return factory(cfg, backoff_base=float(slot.get("backoff_base", 0.5)))

    def _new_match_id(self, mode: str) -> str:
        stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        code = f"{random.randint(0, 0xFFFF):04X}"
        return f"m_{stamp}_{mode}_{code}"

    # ------------------------------------------------------------------ 驱动
    def _start_thread(self, handle: MatchHandle) -> None:
        thread = threading.Thread(
            target=self._run, args=(handle,), daemon=True, name=f"match-{handle.match_id}"
        )
        handle.thread = thread
        thread.start()

    def _run(self, handle: MatchHandle) -> None:
        try:
            handle.match.run_to_end()
        except Exception as error:  # noqa: BLE001 —— 宿主兜底：线程异常不静默
            import traceback

            traceback.print_exc()
            self._system_message(handle, f"桌局线程异常终止：{error}")

    # ------------------------------------------------------------------ 状态
    def transition(self, match_id: str, action: str) -> dict[str, Any]:
        handle = self.get(match_id)
        if action == "suspend":
            handle.match.suspend()
        elif action == "resume":
            handle.match.resume()
            if handle.thread is None or not handle.thread.is_alive():
                self._start_thread(handle)
        elif action == "abandon":
            handle.match.abandon()
        else:
            raise ValueError(f"未知状态操作：{action}")
        return handle.snapshot()

    # ------------------------------------------------------------------ 扇出
    def subscribe(
        self, match_id: str, role: str, after_seq: int | None
    ) -> tuple[MatchHandle, list[Event], threading.Event, Callable[[], None]]:
        """订阅视图流：返回（句柄, 补发事件, 唤醒事件, 退订闭包）。

        G-02 全量重放优先：``after_seq`` 为空 → 全量；非空 → 增量补发
        （事件缓存全量在手，差量始终可行）。观战流（eve 桌）= 公开层全部；
        玩家流 = 公开层 + 本人 HandShaken（W2 接线真实席位）。
        """
        handle = self.get(match_id)
        if role == "spectator" and handle.mode != "eve":
            raise ValueError("观战流仅纯 EVE 桌开放（F-02）")
        with self._lock:
            visible = [e for e in handle.events if self._visible(e, role)]
        if after_seq is None or after_seq < 0:
            backlog = list(visible)  # 全量重放
        else:
            backlog = [e for e in visible if e.seq > after_seq]  # 增量补发
        sub = _Subscriber(role=role, wake=threading.Event(), queue=[])
        handle.subscribers.append(sub)
        handle_ref = handle

        def unsubscribe() -> None:
            # 列表 remove 在 CPython 下原子（GIL）；订阅者量级为个位数，无锁化可接受
            if sub in handle_ref.subscribers:
                handle_ref.subscribers.remove(sub)

        return handle, backlog, sub.wake, unsubscribe

    def _visible(self, event: Event, role: str) -> bool:
        if event.visibility is Visibility.PUBLIC:
            return True
        if event.visibility is Visibility.PRIVATE and role == "player":
            # 玩家流：本人 HandShaken（W2 接线真实席位；W1 无玩家流场景）
            return event.type == "HandShaken"
        return False  # EVAL 层永不进呈现流（05 §4.1）

    def _system_message(self, handle: MatchHandle, text: str) -> None:
        """宿主界面级系统消息（非引擎事件；进 LOG 与扇出，不入权威流）。"""
        event = Event(
            seq=0, type="HostMessage", visibility=Visibility.PUBLIC, payload={"text": text}
        )
        if handle.log_writer is not None:
            handle.log_writer.append(event)
        with self._lock:
            subscribers = list(handle.subscribers)
        for sub in subscribers:
            sub.queue.append(event)
            sub.wake.set()
