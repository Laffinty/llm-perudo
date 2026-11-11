"""对局编排门面（02 §2 / 05 §2；契约签名见 engine/__init__.py）。

职责：驱动桌局/局/回合生命周期、向玩家要决策（纠错 + 故障政策，A-15）、
驱动重摇与应牌链子流程、产出事件流与三层记录（A-10b）、积分制终局判定
（A-03/A-04/A-05）。引擎不感知"玩家是什么"（A-09）。

随机只经注入的 ``Rng`` 进入（A-10）；``decision_log`` 重放模式按记录回放
全部决策、不调用玩家的 ``decide``（宿主重启重建，05 §2.2）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Any

from perudo.core.counting import player_contribution
from perudo.core.legality import (
    apply_bid,
    bid_legal,
    challenge_legal,
    next_seat,
    opening_legal,
    recounter_target,
)
from perudo.core.opening import opening_caller
from perudo.core.types import (
    Bid,
    BidAction,
    ChallengeAction,
    ChallengeKind,
    Face,
    ResponseKind,
)
from perudo.engine.config import MatchConfig
from perudo.engine.events import (
    Event,
    EventType,
    Visibility,
    action_to_payload,
    bid_pair,
    frac_pair,
)
from perudo.engine.phases import EmitFn, drink_along_entries, run_shake_phase, showdown
from perudo.engine.rng import Rng, SplitMix64
from perudo.engine.state import ChainState, MatchState, MatchStatus, transition_status
from perudo.engine.stream import StreamRecorder, build_meta, write_meta
from perudo.engine.views import build_view
from perudo.players.base import Decision, Phase, Player, PlayerView, SignedBid
from perudo.players.bot import ConservativeBot

__all__ = ["Match"]

_FALLBACK_BOT_NAME = "引擎代打"


class _ReplayExhausted(Exception):
    """重放模式决策日志耗尽（内部信号：状态已转 SUSPENDED）。"""


def _action_in_legal(action: object, legal: tuple[Any, ...]) -> bool:
    """动作是否在合法集内（挑战目标按集合语义比较，R-29~R-32）。"""
    for candidate in legal:
        if isinstance(action, ChallengeAction) and isinstance(candidate, ChallengeAction):
            if action.kind is candidate.kind and frozenset(action.targets) == frozenset(
                candidate.targets
            ):
                return True
            continue
        if action == candidate:
            return True
    return False


class Match:
    """桌局编排门面。构造请走 ``Match.create``（冻结配置并开局）。"""

    # ------------------------------------------------------------------ 创建
    @classmethod
    def create(
        cls,
        match_id: str,
        config: MatchConfig,
        roster: Sequence[Player],
        *,
        seed: int,
        stream_path: Path | None = None,
        decision_log: Sequence[Decision] | None = None,
        rng: Rng | None = None,
    ) -> Match:
        """创建桌局：冻结配置、开第一局（DRAFT → RUNNING，A-12）。

        - ``roster`` 长度必须等于 ``config.player_count``，名册名唯一；
        - ``decision_log`` 提供时进入**重放模式**：全部决策点按日志回放、不调用
          玩家的 ``decide``（此时 ``stream_path`` 必须为 ``None``；roster 仍需提供
          ——名字用于事件署名）；
        - ``stream_path`` 提供时逐事件追加写 stream.jsonl 并维护同目录 meta.json；
        - ``rng`` 覆盖内部 SplitMix64（测试注入受控随机用；生产传 seed 即可）。
        """
        names = [player.name for player in roster]
        if decision_log is not None and stream_path is not None:
            raise ValueError("重放模式不得写流（stream_path 必须为 None，05 §2.2）")
        if len(roster) != config.player_count:
            raise ValueError(f"名册 {len(roster)} 人 ≠ 配置 {config.player_count} 人（02 §6）")
        if len(set(names)) != len(names):
            raise ValueError("名册名重复（02 §4：署名唯一）")
        state = MatchState(match_id=match_id, config=config)
        state.scores = [0] * config.player_count
        match = cls(
            state=state,
            roster=tuple(roster),
            rng=rng if rng is not None else SplitMix64(seed),
            seed=seed,
            decision_log=list(decision_log) if decision_log is not None else None,
        )
        if stream_path is not None:
            match._stream_path = stream_path
            match._recorder = StreamRecorder(stream_path)
        state.status = transition_status(state.status, MatchStatus.RUNNING)
        match._emit(
            EventType.MATCH_STARTED,
            Visibility.PUBLIC,
            {"match_id": match_id, "config": config.snapshot(), "roster": names},
        )
        match._emit(
            EventType.MATCH_STATE_CHANGED,
            Visibility.PUBLIC,
            {"match_id": match_id, "status": MatchStatus.RUNNING.value, "reason": "match_started"},
        )
        match._emit(EventType.SEED_RECORDED, Visibility.PRIVATE, {"seed": seed})
        match._write_meta()
        match._begin_round(first=True)
        return match

    def __init__(
        self,
        state: MatchState,
        roster: tuple[Player, ...],
        rng: Rng,
        seed: int,
        decision_log: list[Decision] | None,
    ) -> None:
        self._state = state
        self._roster = roster
        self._rng = rng
        self._seed = seed
        self._decision_log = decision_log
        self._log_index = 0
        self._events: list[Event] = []
        self._seq = 0
        self._recorder: StreamRecorder | None = None
        self._stream_path: Path | None = None
        self._cursor = 0  # BIDDING 轮转指针
        self._fallback_bot = ConservativeBot(_FALLBACK_BOT_NAME)

    # ------------------------------------------------------------------ 契约面
    @property
    def match_id(self) -> str:
        return self._state.match_id

    @property
    def status(self) -> MatchStatus:
        return self._state.status

    @property
    def scores(self) -> tuple[int, ...]:
        return tuple(self._state.scores)

    @property
    def round_no(self) -> int:
        return self._state.round_no

    @property
    def config(self) -> MatchConfig:
        return self._state.config

    def event_log(self) -> tuple[Event, ...]:
        """全量已发射事件（含 seq；重放逐字段验证用，A-10）。"""
        return tuple(self._events)

    def current_pending_seat(self) -> int | None:
        """等待决策的座位；终局/摊牌自动段返回 ``None``。"""
        if self._state.status is not MatchStatus.RUNNING:
            return None
        if self._state.phase is Phase.BIDDING:
            return self._cursor
        if self._state.chain is not None:
            return self._state.chain.awaiting
        return None

    def view_for(self, seat: int) -> PlayerView:
        return build_view(self._state, seat)

    def run_to_end(self) -> None:
        """驱动至 ENDED / ABANDONED / 挂起（恢复后可再次调用继续）。

        重放模式决策日志耗尽 → 自动转 SUSPENDED（reason=replay_exhausted）并收束。
        """
        while self._state.status is MatchStatus.RUNNING:
            try:
                self._step()
            except _ReplayExhausted:
                return

    def suspend(self) -> None:
        self._transition(MatchStatus.SUSPENDED, reason="owner_suspended")
        self._write_meta()

    def resume(self) -> None:
        self._transition(MatchStatus.RUNNING, reason="owner_resumed")
        self._write_meta()

    def abandon(self) -> None:
        """业主弃局（G-08：记录保留、标记 abandoned、不进评测统计）。"""
        self._transition(MatchStatus.ABANDONED, reason="owner_abandoned")
        self._write_meta(abandoned=True)

    def archive(self) -> None:
        """终局后生成复盘档入口（ENDED → ARCHIVED；档内容随 P4 落地）。"""
        self._transition(MatchStatus.ARCHIVED, reason="archived")
        self._write_meta()

    # ------------------------------------------------------------------ 事件
    def _emit(self, etype: str, visibility: Visibility, payload: dict[str, Any]) -> None:
        self._seq += 1
        event = Event(seq=self._seq, type=etype, visibility=visibility, payload=payload)
        self._events.append(event)
        if self._recorder is not None:
            self._recorder.append(event)

    def _emit_fn(self) -> EmitFn:
        return lambda etype, visibility, payload: self._emit(etype, visibility, payload)

    def _transition(self, target: MatchStatus, *, reason: str) -> None:
        self._state.status = transition_status(self._state.status, target)
        self._emit(
            EventType.MATCH_STATE_CHANGED,
            Visibility.PUBLIC,
            {"match_id": self._state.match_id, "status": target.value, "reason": reason},
        )

    def _write_meta(self, *, abandoned: bool | None = None) -> None:
        if self._stream_path is None:
            return
        meta = build_meta(
            self._state.match_id,
            self._state.config,
            [player.name for player in self._roster],
            self._state.status.value,
            self._seed,
            abandoned=(
                abandoned if abandoned is not None else self._state.status is MatchStatus.ABANDONED
            ),
        )
        write_meta(self._stream_path.parent / "meta.json", meta)

    # ------------------------------------------------------------------ 局循环
    def _step(self) -> None:
        state = self._state
        if state.phase is Phase.BIDDING:
            self._step_bidding()
        elif state.phase is Phase.RESPOND:
            self._step_respond()
        else:  # pragma: no cover - phase 只有两态
            raise AssertionError(f"未知阶段：{state.phase}")

    def _begin_round(self, *, first: bool) -> None:
        state = self._state
        state.round_no += 1
        if first:
            caller = (
                state.config.first_caller
                if state.config.first_caller is not None
                else self._rng.below(state.config.player_count)
            )
        else:
            caller = self._next_caller_after_settle()
        state.caller = caller
        state.call_state = state.call_state.initial()
        state.current_bid = None
        state.bid_history = []
        state.last_callers = []
        state.chain = None
        state.phase = Phase.BIDDING
        state.round_entries = []
        state.disqualified = set()
        state.reroll_counts = {}
        self._emit(
            EventType.ROUND_STARTED,
            Visibility.PUBLIC,
            {"round_no": state.round_no, "caller": caller},
        )
        run_shake_phase(state, self._rng, self._emit_fn())
        # 重摇判负导致有效玩家不足两人 → 本局无人可叫，直接收局（登记口径 R-04）
        active = [s for s in range(state.config.player_count) if s not in state.disqualified]
        if len(active) < 2:
            self._finish_round()
            return
        first_seat = caller if caller not in state.disqualified else self._next_active(caller)
        self._cursor = first_seat

    def _next_active(self, seat: int) -> int:
        """沿行动方向的下一个未判负座位；不存在返回 -1。"""
        state = self._state
        current = seat
        for _ in range(state.config.player_count):
            current = next_seat(current, state.config.player_count, state.config.rules)
            if current not in state.disqualified:
                return current
        return -1

    def _finish_round(self) -> None:
        """收局：ROUND_SETTLED → 积分入账 → 终局判定（A-03 完整结算后）。"""
        state = self._state
        for entry in state.round_entries:
            state.scores[entry.player] += entry.codes
        next_caller = self._next_caller_after_settle()
        self._emit(
            EventType.ROUND_SETTLED,
            Visibility.PUBLIC,
            {
                "round_no": state.round_no,
                "entries": [
                    {
                        "seat": entry.player,
                        "codes": entry.codes,
                        "multiplier": frac_pair(entry.multiplier),
                        "breakdown": [
                            [label, frac_pair(factor)] for label, factor in entry.breakdown
                        ],
                    }
                    for entry in state.round_entries
                ],
                "scores": list(state.scores),
                "next_caller": next_caller,
            },
        )
        if any(score >= state.config.end_threshold for score in state.scores):
            self._end_match("threshold")
            return
        if state.round_no >= state.config.max_rounds:
            self._end_match("max_rounds")
            return
        self._begin_round(first=False)

    def _next_caller_after_settle(self) -> int:
        loser_codes: dict[int, int] = {}
        for entry in self._state.round_entries:
            loser_codes[entry.player] = loser_codes.get(entry.player, 0) + entry.codes
        if not loser_codes:  # pragma: no cover - 每局必有输家
            return self._state.caller
        return opening_caller(
            loser_codes, self._state.config.player_count, self._state.config.rules
        )

    def _end_match(self, reason: str) -> None:
        state = self._state
        self._transition(MatchStatus.ENDED, reason=f"match_ended:{reason}")
        minimum = min(state.scores)
        winners = [seat for seat, score in enumerate(state.scores) if score == minimum]
        self._emit(
            EventType.MATCH_ENDED,
            Visibility.PUBLIC,
            {"reason": reason, "scores": list(state.scores), "winners": winners},
        )
        self._write_meta()

    # ------------------------------------------------------------------ 决策机制
    def _take_decision(self, seat: int) -> Decision:
        """取一个合法决策：纠错循环（02 §4.3）+ 故障政策（A-15：重试 → 代打）。"""
        state = self._state
        correction_count = 0
        reason = ""
        while True:
            base_view = build_view(state, seat)
            legal = base_view.legal_actions
            view = replace(base_view, correction_reason=reason)
            decision, degraded, fault_reason = self._obtain(view, seat)
            if _action_in_legal(decision.action, legal):
                if degraded:
                    self._emit(
                        EventType.TURN_DEGRADED,
                        Visibility.PUBLIC,
                        {
                            "seat": seat,
                            "reason": fault_reason,
                            "action": action_to_payload(decision.action),
                        },
                    )
                self._emit_decision_facts(seat, decision, correction_count, degraded)
                return decision
            correction_count += 1
            reason = (
                f"动作不在合法动作集（纠错 {correction_count}/{state.config.correction_budget}）"
            )
            if correction_count > state.config.correction_budget:
                fallback_view = replace(base_view, correction_reason=reason)
                decision, fault_reason = self._fallback(seat, fallback_view, f"纠错超限：{reason}")
                self._emit(
                    EventType.TURN_DEGRADED,
                    Visibility.PUBLIC,
                    {
                        "seat": seat,
                        "reason": fault_reason,
                        "action": action_to_payload(decision.action),
                    },
                )
                self._emit_decision_facts(seat, decision, correction_count, True)
                return decision

    def _obtain(self, view: PlayerView, seat: int) -> tuple[Decision, bool, str]:
        """从决策日志（重放）/玩家取得决策；调用异常走 A-15 重试 → 代打。"""
        if self._decision_log is not None:
            if self._log_index >= len(self._decision_log):
                # 重放重建完成：交还决策权给 roster、转 SUSPENDED 等待宿主恢复（05 §2.2）
                self._decision_log = None
                self._transition(MatchStatus.SUSPENDED, reason="replay_exhausted")
                raise _ReplayExhausted
            decision = self._decision_log[self._log_index]
            self._log_index += 1
            return decision, False, ""
        attempts = 0
        while True:
            try:
                return self._roster[seat].decide(view), False, ""
            except Exception:  # noqa: BLE001 —— 故障政策边界（A-15）
                attempts += 1
                if attempts > self._state.config.fault_retries:
                    decision, fault_reason = self._fallback(seat, view, "调用故障重试耗尽")
                    return decision, True, fault_reason

    def _fallback(self, seat: int, view: PlayerView, fault_reason: str) -> tuple[Decision, str]:
        """引擎代打（A-15/A-18：内置保守机器人）。"""
        bot = self._fallback_bot
        return bot.decide(view), fault_reason

    def _emit_decision_facts(
        self, seat: int, decision: Decision, correction_count: int, degraded: bool
    ) -> None:
        state = self._state
        state.turn_seq += 1
        if isinstance(decision.action, BidAction):
            relevant_face = decision.action.bid.face
        elif state.current_bid is not None:
            relevant_face = state.current_bid.face
        else:  # pragma: no cover - 非首叫必有 current_bid
            relevant_face = Face.ONE
        hand = state.hands.get(seat)
        self_support = (
            player_contribution(hand, relevant_face, state.call_state, state.config.rules)
            if hand is not None
            else 0
        )
        self._emit(
            EventType.DECISION_FACTS,
            Visibility.EVAL,
            {
                "turn_seq": state.turn_seq,
                "actor": self._roster[seat].name,
                "phase": state.phase.value,
                "seat": seat,
                "prev_bid": bid_pair(state.current_bid) if state.current_bid is not None else None,
                "wild_state": state.call_state.zhai.value,
                "ones_called": state.call_state.ones_called,
                "self_support": self_support,
                "legal_count": len(build_view(state, seat).legal_actions),
                "correction_count": correction_count,
                "degraded": degraded,
                "decision": {
                    "action": action_to_payload(decision.action),
                    "quote": decision.quote,
                    "thinking": decision.thinking,
                    "attachments": dict(decision.attachments),
                },
            },
        )
        if state.config.spectated and decision.thinking:
            self._emit(
                EventType.THINKING_OBSERVED,
                Visibility.PUBLIC,
                {"seat": seat, "thinking_text": decision.thinking},
            )

    # ------------------------------------------------------------------ BIDDING
    def _step_bidding(self) -> None:
        state = self._state
        seat = self._cursor
        decision = self._take_decision(seat)
        action = decision.action
        quote = self._truncate(decision.quote)
        if isinstance(action, BidAction):
            if state.current_bid is None:
                verdict = opening_legal(action, state.config.player_count, state.config.rules)
            else:
                verdict = bid_legal(
                    action,
                    state.call_state,
                    state.current_bid,
                    state.config.player_count,
                    state.config.rules,
                )
            if not verdict.legal:  # pragma: no cover —— 合法集来自内核枚举，防御性
                raise AssertionError(f"内核枚举与判定不一致：{verdict.reason}")
            state.call_state = apply_bid(action, state.call_state)
            state.current_bid = action.bid
            state.last_callers.append(seat)
            state.bid_history.append(
                SignedBid(seat=seat, kind=action.kind, bid=action.bid, quote=quote)
            )
            self._emit(
                EventType.BID_MADE,
                Visibility.PUBLIC,
                {
                    "seat": seat,
                    "kind": action.kind.value,
                    "count": action.bid.count,
                    "face": int(action.bid.face),
                    "quote": quote,
                },
            )
            nxt = self._next_active(seat)
            if nxt == -1 or nxt == seat:
                # 无其他有效玩家可接叫（登记口径 R-04）：直接收局
                self._finish_round()
                return
            self._cursor = nxt
            return
        if isinstance(action, ChallengeAction):
            verdict = challenge_legal(
                action.kind,
                seat,
                action.targets,
                tuple(state.last_callers),
                state.config.player_count,
                state.config.rules,
            )
            if not verdict.legal:  # pragma: no cover
                raise AssertionError(f"内核枚举与判定不一致：{verdict.reason}")
            stake0 = Fraction(2) if action.kind is ChallengeKind.JUMP else Fraction(1)
            order = self._response_order(seat, action.targets)
            chain = ChainState(
                initiator=seat,
                kind=action.kind,
                targets=order,
                stakes=dict.fromkeys(action.targets, stake0),
                contested_bids={t: self._last_bid_of(t) for t in action.targets},
                awaiting=order[0],
            )
            state.chain = chain
            state.phase = Phase.RESPOND
            self._emit(
                EventType.CHALLENGE_MADE,
                Visibility.PUBLIC,
                {
                    "seat": seat,
                    "kind": action.kind.value,
                    "targets": list(action.targets),
                    "base_multiplier": frac_pair(stake0),
                },
            )
            return
        raise AssertionError(f"BIDDING 阶段收到非叫骰/杀类动作：{type(action).__name__}")

    def _truncate(self, quote: str) -> str:
        return quote[: self._state.config.quote_max_len]

    def _last_bid_of(self, seat: int) -> Bid:
        for signed in reversed(self._state.bid_history):
            if signed.seat == seat:
                return signed.bid
        raise AssertionError(f"目标 {seat} 本局无叫骰（枚举保证）")

    def _response_order(self, initiator: int, targets: tuple[int, ...]) -> tuple[int, ...]:
        """应牌顺序：沿发起者行动方向从下一位起环行遇到的 target 顺序（登记口径 R-04）。"""
        order: list[int] = []
        current = initiator
        for _ in range(self._state.config.player_count):
            current = next_seat(current, self._state.config.player_count, self._state.config.rules)
            if current in targets and current not in order:
                order.append(current)
        return tuple(order)

    # ------------------------------------------------------------------ RESPOND
    def _step_respond(self) -> None:
        state = self._state
        chain = state.chain
        assert chain is not None
        if chain.awaiting < 0:
            self._resolve_round()
            return
        seat = chain.awaiting
        decision = self._take_decision(seat)
        action = decision.action
        quote = self._truncate(decision.quote)
        if not isinstance(action, ResponseKind):  # pragma: no cover
            raise AssertionError(f"RESPOND 阶段收到非应牌动作：{type(action).__name__}")
        chain.responses[seat] = action.value
        declared = self._declared_target(chain, action)
        self._emit(
            EventType.RESPONDED,
            Visibility.PUBLIC,
            {"seat": seat, "choice": action.value, "quote": quote, "declared_target": declared},
        )
        self._advance_chain(chain, seat, action)

    def _declared_target(self, chain: ChainState, action: ResponseKind) -> int | None:
        if action is ResponseKind.COUNTER:
            return chain.initiator
        if action is ResponseKind.RECOUNTER:
            return recounter_target(
                chain.initiator,
                tuple(self._state.last_callers),
                self._state.config.player_count,
                self._state.config.rules,
            )
        return None

    def _advance_chain(self, chain: ChainState, seat: int, action: ResponseKind) -> None:
        """应牌后的链推进（D-06 同链升级口径：×2 → ×4 → ×8）。"""
        if action is ResponseKind.COUNTER:
            focus = seat
            chain.countered = True
            chain.counter_focus = focus
            chain.stakes[focus] *= 2
            chain.awaiting = chain.initiator
            return
        if action is ResponseKind.RECOUNTER:
            assert chain.counter_focus is not None
            chain.stakes[chain.counter_focus] *= 2
            chain.recounter_declared = self._declared_target(chain, action)
            self._await_next(chain)
            return
        if chain.countered and seat == chain.initiator:
            # 原杀者摊牌（REVEAL）：反杀战落定，倍数保持
            self._await_next(chain)
            return
        self._await_next(chain)

    def _await_next(self, chain: ChainState) -> None:
        pending = chain.next_pending()
        chain.awaiting = pending if pending is not None else -1

    def _resolve_round(self) -> None:
        """摊牌 → 结算 → 陪饮 → 收局。"""
        state = self._state
        chain = state.chain
        assert chain is not None
        entries = showdown(state, chain, self._emit_fn())
        entries.extend(drink_along_entries(state, self._rng, entries))
        state.round_entries.extend(entries)
        state.chain = None
        state.phase = Phase.BIDDING
        self._finish_round()
