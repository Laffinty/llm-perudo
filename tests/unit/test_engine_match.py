"""P2 单元测试：对局编排门面（生命周期 / bot 自对弈 / 同种子与决策日志重放 /
故障政策 / 应牌链场景 / 观战投影 / 挂起与弃局 / meta 落盘）。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from conftest import ExceptionPlayer, IllegalPlayer, ScriptedPlayer, ScriptedRng
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
from perudo.engine.events import EventType
from perudo.engine.match import Match
from perudo.engine.state import MatchStatus, transition_status
from perudo.engine.stream import extract_decisions, read_events
from perudo.players.base import Decision
from perudo.players.bot import ConservativeBot

_MATCH_FIELDS = {
    "player_count",
    "end_threshold",
    "max_rounds",
    "quote_max_len",
    "correction_budget",
    "fault_retries",
    "first_caller",
    "spectated",
}


def _bot_config(**changes: object) -> MatchConfig:
    """构造测试配置：MatchConfig 字段直传，其余路由进 RuleConfig（§12 开关）。"""
    cfg_changes = {k: v for k, v in changes.items() if k in _MATCH_FIELDS}
    rule_changes = {k: v for k, v in changes.items() if k not in _MATCH_FIELDS}
    config = replace(MatchConfig(), **cfg_changes)  # type: ignore[arg-type]
    if rule_changes:
        config = config.with_rules(**rule_changes)  # type: ignore[arg-type]
    return config


def _bots(n: int = 4) -> list[ConservativeBot]:
    return [ConservativeBot(f"bot{i}") for i in range(n)]


def _types(events: list) -> list[str]:
    return [event.type for event in events]


def _settle_entries(events: list, round_no: int = 1) -> list[dict]:
    for event in events:
        if event.type == EventType.ROUND_SETTLED and event.payload["round_no"] == round_no:
            return event.payload["entries"]
    raise AssertionError(f"缺少第 {round_no} 局 ROUND_SETTLED")


def _first_legal_bid():
    from perudo.core.legality import enumerate_bid_actions
    from perudo.core.types import RuleConfig

    return enumerate_bid_actions(None, None, 4, RuleConfig())[0]


# ---------------------------------------------------------------------------
# 生命周期状态机（05 §2.1）
# ---------------------------------------------------------------------------


def test_lifecycle_transitions_valid_and_invalid() -> None:
    """全部合法转移放行、非法转移拒绝（05 §2.1，计划 §4.2 属性）。"""
    legal_chain = [
        (MatchStatus.DRAFT, MatchStatus.RUNNING),
        (MatchStatus.RUNNING, MatchStatus.SUSPENDED),
        (MatchStatus.SUSPENDED, MatchStatus.RUNNING),
        (MatchStatus.RUNNING, MatchStatus.ENDED),
        (MatchStatus.ENDED, MatchStatus.ARCHIVED),
        (MatchStatus.RUNNING, MatchStatus.ABANDONED),
        (MatchStatus.SUSPENDED, MatchStatus.ABANDONED),
    ]
    for current, target in legal_chain:
        assert transition_status(current, target) is target
    for current, target in (
        (MatchStatus.DRAFT, MatchStatus.ENDED),
        (MatchStatus.DRAFT, MatchStatus.ARCHIVED),
        (MatchStatus.RUNNING, MatchStatus.DRAFT),
        (MatchStatus.ENDED, MatchStatus.RUNNING),
        (MatchStatus.ARCHIVED, MatchStatus.ENDED),
        (MatchStatus.ABANDONED, MatchStatus.RUNNING),
    ):
        with pytest.raises(ValueError, match="非法生命周期转移"):
            transition_status(current, target)


# ---------------------------------------------------------------------------
# bot 自对弈完整桌局（02 M2）
# ---------------------------------------------------------------------------


def test_bot_self_play_full_match() -> None:
    """脚本机器人自对弈完整桌局：ENDED、seq 连续、积分与结算一致、winners 正确。"""
    match = Match.create(
        "m_bot",
        _bot_config(end_threshold=30, max_rounds=200),
        _bots(4),
        seed=2026,
    )
    match.run_to_end()
    assert match.status is MatchStatus.ENDED
    events = match.event_log()
    seqs = [event.seq for event in events]
    assert seqs == list(range(1, len(seqs) + 1))
    ended = events[-1]
    assert ended.type == EventType.MATCH_ENDED
    assert ended.payload["scores"] == list(match.scores)
    minimum = min(match.scores)
    assert ended.payload["winners"] == [s for s, v in enumerate(match.scores) if v == minimum]
    total_codes = sum(
        entry["codes"]
        for event in events
        if event.type == EventType.ROUND_SETTLED
        for entry in event.payload["entries"]
    )
    assert total_codes == sum(match.scores)
    assert any(
        event.payload["reason"] == "match_ended:threshold"
        for event in events
        if event.type == EventType.MATCH_STATE_CHANGED
    )


def test_same_seed_replay_identical_events() -> None:
    """A-10：同种子 + 同 bot ⇒ 事件流逐字段一致。"""
    events_a = _run_bot_match(seed=7)
    events_b = _run_bot_match(seed=7)
    assert events_a == events_b


def _run_bot_match(seed: int, threshold: int = 30) -> tuple:
    match = Match.create(
        "m_seed",
        _bot_config(end_threshold=threshold, max_rounds=200),
        _bots(4),
        seed=seed,
    )
    match.run_to_end()
    return match.event_log()


def test_decision_log_replay_identical_events() -> None:
    """A-10 / 05 §2.2：决策日志重放 → 事件流逐字段重现（宿主重启重建路径）。"""
    original = Match.create(
        "m_replay",
        _bot_config(end_threshold=30, max_rounds=200),
        _bots(4),
        seed=99,
    )
    original.run_to_end()
    decisions = extract_decisions(original.event_log())
    assert decisions, "决策事实（评测层）必须可提取"
    replayed = Match.create(
        "m_replay",
        _bot_config(end_threshold=30, max_rounds=200),
        _bots(4),
        seed=99,
        decision_log=decisions,
    )
    replayed.run_to_end()
    assert replayed.event_log() == original.event_log()


def test_decision_log_exhaustion_suspends() -> None:
    """重放模式决策日志耗尽 → 自动转 SUSPENDED（05 §2.2 宿主重启重建语义）。"""
    config = _bot_config(end_threshold=10_000, max_rounds=1)
    partial = Match.create(
        "m_short",
        config,
        _bots(4),
        seed=1,
        decision_log=[Decision(action=_first_legal_bid())],
    )
    partial.run_to_end()
    assert partial.status is MatchStatus.SUSPENDED
    assert any(
        event.payload["reason"] == "replay_exhausted"
        for event in partial.event_log()
        if event.type == EventType.MATCH_STATE_CHANGED
    )


# ---------------------------------------------------------------------------
# 故障政策（A-15）
# ---------------------------------------------------------------------------


def test_fault_policy_bot_fallback_after_retries() -> None:
    """玩家调用故障：重试 3 次 → 引擎代打（保守机器人）+ TurnDegraded，对局继续。"""
    roster = [ExceptionPlayer("boom"), *_bots(4)[1:]]
    match = Match.create(
        "m_fault",
        _bot_config(end_threshold=100_000, max_rounds=3, fault_retries=3),
        roster,
        seed=5,
    )
    match.run_to_end()
    degraded = [e for e in match.event_log() if e.type == EventType.TURN_DEGRADED]
    assert degraded, "故障必须触发降级代打"
    assert all(event.payload["seat"] == 0 for event in degraded)
    assert any("重试耗尽" in str(event.payload["reason"]) for event in degraded)
    assert match.status in (MatchStatus.ENDED, MatchStatus.RUNNING)


def test_correction_budget_exceeded_degrades() -> None:
    """非法动作纠错超预算（默认 2）→ 进故障政策 → 代打 + 降级。"""
    roster = [IllegalPlayer("bad"), *_bots(4)[1:]]
    match = Match.create(
        "m_illegal",
        _bot_config(end_threshold=100_000, max_rounds=2),
        roster,
        seed=6,
    )
    match.run_to_end()
    degraded = [e for e in match.event_log() if e.type == EventType.TURN_DEGRADED]
    assert any("纠错超限" in str(event.payload["reason"]) for event in degraded)


# ---------------------------------------------------------------------------
# Scripted 场景：应牌链与结算口径（脚本按阶段分队；耗尽回退保守机器人）
# ---------------------------------------------------------------------------

HANDS = [(Face.ONE, Face.ONE, Face.TWO, Face.THREE, Face.FOUR)] * 4


def _scripted_match(
    bids: dict[int, list[Decision]],
    responds: dict[int, list[Decision]] | None = None,
    *,
    rng: ScriptedRng | None = None,
    config: MatchConfig | None = None,
    seat_hands: list[tuple[Face, ...]] | None = None,
) -> Match:
    cfg = config or _bot_config(end_threshold=1_000_000, max_rounds=1)
    responds = responds or {}
    roster = []
    for i in range(cfg.player_count):
        if i in bids or i in responds:
            roster.append(
                ScriptedPlayer(f"p{i}", bids=bids.get(i, []), responds=responds.get(i, []))
            )
        else:
            roster.append(ConservativeBot(f"p{i}"))
    rng = rng or ScriptedRng(rolls=list(seat_hands or HANDS))
    match = Match.create("m_script", cfg, roster, seed=0, rng=rng)
    match.run_to_end()
    return match


def test_open_challenge_surrender_floor() -> None:
    """开杀 → 投降：R-52 减半保底 1 码（×1 → ½ → 保底 1）。"""
    match = _scripted_match(
        {
            0: [Decision(action=BidAction(BidKind.NORMAL, Bid(6, Face.THREE)))],
            1: [Decision(action=BidAction(BidKind.NORMAL, Bid(7, Face.THREE)))],
            2: [Decision(action=BidAction(BidKind.NORMAL, Bid(8, Face.THREE)))],
            3: [Decision(action=ChallengeAction(ChallengeKind.OPEN, (2,)))],
        },
        {2: [Decision(action=ResponseKind.SURRENDER)]},
    )
    entries = _settle_entries(match.event_log())
    assert [(e["seat"], e["codes"]) for e in entries] == [(2, 1)]
    assert entries[0]["multiplier"] == [1, 2]


def test_jump_counter_reveal_quadruples() -> None:
    """跳杀 → 反杀 → 原杀者摊牌：链上倍数 ×2 → ×4（R-48/R-49），输家付 4 码。

    全场 count(3) = 12 ≥ 7 → 被挑战叫骰成立 → 劈者（initiator=3）输。
    关闭进阶项以隔离链阶梯（R-54/R-55/R-56 各有单测）。
    """
    match = _scripted_match(
        {
            0: [Decision(action=BidAction(BidKind.NORMAL, Bid(6, Face.THREE)))],
            1: [Decision(action=BidAction(BidKind.NORMAL, Bid(7, Face.THREE)))],
            2: [Decision(action=BidAction(BidKind.NORMAL, Bid(8, Face.FOUR)))],
            3: [Decision(action=ChallengeAction(ChallengeKind.JUMP, (1,)))],
        },
        {
            1: [Decision(action=ResponseKind.COUNTER)],
            3: [Decision(action=ResponseKind.REVEAL)],
        },
        config=_bot_config(
            end_threshold=1_000_000, max_rounds=1, half_double=False, jump_fail_double=False
        ),
    )
    entries = _settle_entries(match.event_log())
    assert [(e["seat"], e["codes"]) for e in entries] == [(3, 4)]
    assert entries[0]["multiplier"] == [4, 1]


def test_jump_counter_recounter_octuples() -> None:
    """跳杀 → 反杀 → 再反杀（R-36 / D-06 同链升级）：倍数 ×8，不可再被反杀。"""
    match = _scripted_match(
        {
            0: [Decision(action=BidAction(BidKind.NORMAL, Bid(6, Face.THREE)))],
            1: [Decision(action=BidAction(BidKind.NORMAL, Bid(7, Face.THREE)))],
            2: [Decision(action=BidAction(BidKind.NORMAL, Bid(8, Face.FOUR)))],
            3: [Decision(action=ChallengeAction(ChallengeKind.JUMP, (1,)))],
        },
        {
            1: [Decision(action=ResponseKind.COUNTER)],
            3: [Decision(action=ResponseKind.RECOUNTER)],
        },
        config=_bot_config(
            end_threshold=1_000_000, max_rounds=1, half_double=False, jump_fail_double=False
        ),
    )
    entries = _settle_entries(match.event_log())
    assert [(e["seat"], e["codes"]) for e in entries] == [(3, 8)]
    assert entries[0]["multiplier"] == [8, 1]
    responded = [e for e in match.event_log() if e.type == EventType.RESPONDED]
    recounter = [e for e in responded if e.payload["choice"] == "recounter"]
    assert recounter and recounter[0].payload["declared_target"] == 0  # §13.3 第 6 步：D 再反劈 A


def test_multi_kill_separate_settlement() -> None:
    """连杀两目标分别结算（R-51）：一成一降各走各的 stake。"""
    match = _scripted_match(
        {
            0: [Decision(action=BidAction(BidKind.NORMAL, Bid(6, Face.THREE)))],
            1: [Decision(action=BidAction(BidKind.NORMAL, Bid(7, Face.THREE)))],
            2: [Decision(action=BidAction(BidKind.NORMAL, Bid(8, Face.FOUR)))],
            3: [Decision(action=ChallengeAction(ChallengeKind.MULTI, (2, 1)))],
        },
        {
            1: [Decision(action=ResponseKind.REVEAL)],
            2: [Decision(action=ResponseKind.SURRENDER)],
        },
    )
    entries = _settle_entries(match.event_log())
    by_seat = {e["seat"]: e for e in entries}
    assert by_seat[2]["codes"] == 1  # 投降保底
    assert by_seat[3]["codes"] == 2  # seat1 叫骰成立 → 杀者输 ×2（R-55）


def test_multi_kill_win_three_doubles() -> None:
    """R-50：连杀连赢 ≥ 3 家 → 被杀者惩罚再翻倍（6 人局，count(3)=0 全部不成立）。"""
    hands6 = [(Face.TWO, Face.TWO, Face.TWO, Face.FIVE, Face.FIVE)] * 6
    match = _scripted_match(
        {
            0: [Decision(action=BidAction(BidKind.NORMAL, Bid(9, Face.THREE)))],
            1: [Decision(action=BidAction(BidKind.NORMAL, Bid(10, Face.THREE)))],
            2: [Decision(action=BidAction(BidKind.NORMAL, Bid(11, Face.THREE)))],
            3: [Decision(action=BidAction(BidKind.NORMAL, Bid(12, Face.THREE)))],
            4: [Decision(action=ChallengeAction(ChallengeKind.MULTI, (3, 2, 1)))],
        },
        {
            1: [Decision(action=ResponseKind.REVEAL)],
            2: [Decision(action=ResponseKind.REVEAL)],
            3: [Decision(action=ResponseKind.REVEAL)],
        },
        seat_hands=hands6,
        config=_bot_config(
            end_threshold=1_000_000,
            max_rounds=1,
            player_count=6,
            half_double=False,  # 隔离 R-50（R-54 不够一半另测）
        ),
    )
    entries = _settle_entries(match.event_log())
    assert [(e["seat"], e["codes"]) for e in entries] == [(1, 2), (2, 2), (3, 2)]


def test_darkness_flips_judgment() -> None:
    """天黑黑（R-63）：全场无真 4 → 开骰者输（覆盖常规判定方向）。

    手牌 (1,1,2,4,5)：#4 = 0、#1 = 8 → count(4) = 8 < 13 → 常规应不成立，
    天黑黑把判定翻转为成立（开骰者输）。
    """
    hands = [(Face.ONE, Face.ONE, Face.TWO, Face.THREE, Face.FIVE)] * 4
    cfg = _bot_config(end_threshold=1_000_000, max_rounds=1, darkness=True, half_double=False)
    match = _scripted_match(
        {
            0: [Decision(action=BidAction(BidKind.NORMAL, Bid(6, Face.FOUR)))],
            1: [Decision(action=BidAction(BidKind.NORMAL, Bid(7, Face.FOUR)))],
            2: [Decision(action=BidAction(BidKind.NORMAL, Bid(13, Face.FOUR)))],
            3: [Decision(action=ChallengeAction(ChallengeKind.OPEN, (2,)))],
        },
        {2: [Decision(action=ResponseKind.REVEAL)]},
        config=cfg,
        seat_hands=hands,
    )
    revealed = [e for e in match.event_log() if e.type == EventType.REVEALED]
    assert revealed[0].payload["darkness"] is True
    judgment = revealed[0].payload["judgments"][0]
    assert judgment["count"] == 8 and judgment["count"] < judgment["bid"][0]
    assert judgment["stood"] is True  # 天黑黑翻转：开骰者（=挑战者 3）输
    entries = _settle_entries(match.event_log())
    assert [(e["seat"], e["codes"]) for e in entries] == [(3, 1)]


def test_darkness_off_regular_direction() -> None:
    """天黑黑默认关闭：同一局面回归 R-45 常规方向（被开者输）。"""
    hands = [(Face.ONE, Face.ONE, Face.TWO, Face.THREE, Face.FIVE)] * 4
    cfg = _bot_config(end_threshold=1_000_000, max_rounds=1, darkness=False)
    match = _scripted_match(
        {
            0: [Decision(action=BidAction(BidKind.NORMAL, Bid(6, Face.FOUR)))],
            1: [Decision(action=BidAction(BidKind.NORMAL, Bid(7, Face.FOUR)))],
            2: [Decision(action=BidAction(BidKind.NORMAL, Bid(13, Face.FOUR)))],
            3: [Decision(action=ChallengeAction(ChallengeKind.OPEN, (2,)))],
        },
        {2: [Decision(action=ResponseKind.REVEAL)]},
        config=cfg,
        seat_hands=hands,
    )
    entries = _settle_entries(match.event_log())
    assert [(e["seat"], e["codes"]) for e in entries] == [(2, 1)]


def test_drink_along_on_and_off() -> None:
    """陪饮开关（R-57）：开启时按 D-05 映射追加同罚 entry；关闭时不追加。"""
    drink_rng = ScriptedRng(
        rolls=[(Face.ONE, Face.ONE, Face.TWO, Face.THREE, Face.FOUR)] * 4
        + [(Face.THREE, Face.FOUR)]  # 陪饮骰 s=7 → 偏移 (7-1)%4=2 → buddy=(2+2)%4=0
    )
    bids = {
        0: [Decision(action=BidAction(BidKind.NORMAL, Bid(6, Face.THREE)))],
        1: [Decision(action=BidAction(BidKind.NORMAL, Bid(7, Face.THREE)))],
        2: [Decision(action=BidAction(BidKind.NORMAL, Bid(8, Face.THREE)))],
        3: [Decision(action=ChallengeAction(ChallengeKind.OPEN, (2,)))],
    }
    responds = {2: [Decision(action=ResponseKind.SURRENDER)]}
    match_on = _scripted_match(
        bids,
        responds,
        rng=drink_rng,
        config=_bot_config(end_threshold=1_000_000, max_rounds=1, drink_along=True),
    )
    entries_on = _settle_entries(match_on.event_log())
    assert (0, 1) in [(e["seat"], e["codes"]) for e in entries_on]  # 陪饮对象 seat0
    assert any(e["seat"] == 2 and e["codes"] == 1 for e in entries_on)
    match_off = _scripted_match(
        bids,
        responds,
        config=_bot_config(end_threshold=1_000_000, max_rounds=1, drink_along=False),
    )
    entries_off = _settle_entries(match_off.event_log())
    assert [(e["seat"], e["codes"]) for e in entries_off] == [(2, 1)]


# ---------------------------------------------------------------------------
# 观战投影（05 G-01）
# ---------------------------------------------------------------------------


def test_spectated_projection_events() -> None:
    """spectated=True：HandObserved 带标注；带 thinking 的决策出 ThinkingObserved。"""
    thinking = Decision(
        action=BidAction(BidKind.NORMAL, Bid(6, Face.THREE)),
        thinking="开局叫 3，稳一手",
    )
    cfg_on = _bot_config(end_threshold=1_000_000, max_rounds=1, spectated=True)
    match = _scripted_match({0: [thinking]}, config=cfg_on)
    types_ = _types(match.event_log())
    assert EventType.HAND_OBSERVED in types_
    assert EventType.THINKING_OBSERVED in types_
    match_off = _scripted_match(
        {0: [thinking]}, config=_bot_config(end_threshold=1_000_000, max_rounds=1)
    )
    types_off = _types(match_off.event_log())
    assert EventType.HAND_OBSERVED not in types_off
    assert EventType.THINKING_OBSERVED not in types_off


# ---------------------------------------------------------------------------
# 挂起 / 弃局 / meta 落盘
# ---------------------------------------------------------------------------


def test_suspend_resume_and_meta(tmp_path: Path) -> None:
    """挂起 → run_to_end 停摆 → 恢复继续 → ENDED；meta.json 随状态更新；权威流一致。"""
    stream = tmp_path / "match" / "stream.jsonl"
    stream.parent.mkdir(parents=True)
    match = Match.create(
        "m_meta",
        _bot_config(end_threshold=30, max_rounds=200),
        _bots(4),
        seed=11,
        stream_path=stream,
    )
    match.suspend()
    assert match.status is MatchStatus.SUSPENDED
    match.run_to_end()
    assert match.status is MatchStatus.SUSPENDED  # 停摆
    match.resume()
    match.run_to_end()
    assert match.status is MatchStatus.ENDED
    assert read_events(stream) == match.event_log()  # 权威流与内存逐字段一致
    meta_text = (tmp_path / "match" / "meta.json").read_text(encoding="utf-8")
    assert '"status": "ENDED"' in meta_text


def test_abandon_marks_and_stops(tmp_path: Path) -> None:
    """弃局（G-08）：RUNNING → ABANDONED、meta 标记 abandoned、不进终局。"""
    stream = tmp_path / "m2" / "stream.jsonl"
    stream.parent.mkdir(parents=True)
    match = Match.create(
        "m_abandon",
        _bot_config(end_threshold=30, max_rounds=200),
        _bots(4),
        seed=12,
        stream_path=stream,
    )
    match.abandon()
    assert match.status is MatchStatus.ABANDONED
    match.run_to_end()
    assert match.status is MatchStatus.ABANDONED
    meta_text = (tmp_path / "m2" / "meta.json").read_text(encoding="utf-8")
    assert '"abandoned": true' in meta_text
    assert EventType.MATCH_ENDED not in _types(match.event_log())


def test_roster_validation() -> None:
    """名册人数不符 / 名重复 → create 拒绝（02 §6）。"""
    with pytest.raises(ValueError, match="名册"):
        Match.create("m_bad", _bot_config(player_count=4), _bots(3), seed=1)
    with pytest.raises(ValueError, match="名册名重复"):
        Match.create(
            "m_dup",
            _bot_config(player_count=2),
            [ConservativeBot("同"), ConservativeBot("同")],
            seed=1,
        )


def test_replay_mode_rejects_stream_path() -> None:
    """重放模式不得写流（05 §2.2）。"""
    with pytest.raises(ValueError, match="重放模式"):
        Match.create(
            "m_rp",
            _bot_config(end_threshold=10_000, max_rounds=1),
            _bots(4),
            seed=1,
            stream_path=Path("x.jsonl"),
            decision_log=[Decision(action=_first_legal_bid())],
        )
