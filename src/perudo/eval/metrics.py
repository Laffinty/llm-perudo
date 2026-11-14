"""评测指标（05 §6.2 E-01~E-15；G-8 决策时刻私有事实）。

输入 = 权威事件流（``Event`` 序列，来自 stream.jsonl 或 Match.event_log）。
输出 = 单桌指标字典（全部 JSON 安全）+ 跨桌聚合。

过滤口径（05 §6.2）：默认剔除降级回合（degraded=True）；弃局整桌由
``aggregate_batch`` 过滤（include_abandoned 可切换）。

E-15 口径（05 §6.2）：数字部分可算才算（thinking 覆盖率/均长）——语义一致性
归 AI 评述层（三禁边界，02 §8.1）。
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Sequence
from typing import Any

from perudo.engine.events import Event

__all__ = [
    "DEFAULT_TAUNT_WORDS",
    "aggregate_batch",
    "compute_match_metrics",
    "match_abandoned",
]

#: N5-04 挑衅词表初版（可配置覆盖；05 §6.2 E-12）
DEFAULT_TAUNT_WORDS: tuple[str, ...] = (
    "挑衅",
    "垃圾",
    "渣渣",
    "菜鸟",
    "太菜",
    "送分",
    "饮酒",
    "饮啦",
    "饮杯",
    "怕咩",
    "吹咩",
    "开你",
)

_TOTAL_DICE_PER_PLAYER = 5


def match_abandoned(events: Sequence[Event]) -> bool:
    """弃局判定（05 §2.5 G-08）：MatchStateChanged status=ABANDONED。"""
    return any(
        e.type == "MatchStateChanged" and e.payload.get("status") == "ABANDONED" for e in events
    )


def _roster(events: Sequence[Event]) -> list[str]:
    for e in events:
        if e.type == "MatchStarted":
            return [str(n) for n in e.payload.get("roster", [])]
    return []


def _player_count(events: Sequence[Event]) -> int:
    for e in events:
        if e.type == "MatchStarted":
            cfg = e.payload.get("config", {})
            if isinstance(cfg, dict):
                return int(cfg.get("player_count", 0))
    return 0


def _facts(events: Sequence[Event], *, include_degraded: bool) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in events:
        if e.type != "DecisionFacts":
            continue
        if not include_degraded and e.payload.get("degraded"):
            continue
        out.append(dict(e.payload))
    return out


def _envelope_of(fact: dict[str, Any]) -> dict[str, Any]:
    decision = fact.get("decision", {})
    if isinstance(decision, dict):
        raw = decision.get("attachments", {}).get("adapter_envelope")
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return {}
            return dict(parsed) if isinstance(parsed, dict) else {}
        if isinstance(raw, dict):
            return dict(raw)
    return {}


def _round_segments(events: Sequence[Event]) -> list[list[Event]]:
    """按 RoundStarted 边界切分局段（局内重组的基础）。"""
    segments: list[list[Event]] = []
    current: list[Event] = []
    for e in events:
        if e.type == "RoundStarted":
            if current:
                segments.append(current)
            current = [e]
        elif current:
            current.append(e)
    if current:
        segments.append(current)
    return segments


def _bid_of_fact(fact: dict[str, Any]) -> tuple[int, int] | None:
    action = fact.get("decision", {}).get("action", {})
    if isinstance(action, dict) and action.get("t") == "bid":
        return int(action.get("count", 0)), int(action.get("face", 0))
    return None


def _avg(values: Sequence[float]) -> float | None:
    return round(statistics.mean(values), 4) if values else None


def compute_match_metrics(
    events: Sequence[Event],
    *,
    taunt_words: Sequence[str] = DEFAULT_TAUNT_WORDS,
    include_degraded: bool = False,
) -> dict[str, Any]:
    """单桌指标（E-01~E-15；05 §6.2 口径）。弃局由调用方过滤（见 aggregate）。"""
    roster = _roster(events)
    player_count = _player_count(events)
    facts = _facts(events, include_degraded=include_degraded)
    segments = _round_segments(events)
    total_dice = player_count * _TOTAL_DICE_PER_PLAYER

    # ---- 结算面（E-02/E-03/E-04/E-01 原料） ----
    scores_final: list[int] = []
    match_reason = ""
    winners: list[int] = []
    score_curves: dict[int, list[int]] = {i: [] for i in range(player_count)}
    loser_rounds: dict[int, int] = dict.fromkeys(range(player_count), 0)
    codes_lost: dict[int, int] = dict.fromkeys(range(player_count), 0)
    rounds_played = 0
    for e in events:
        if e.type == "RoundSettled":
            rounds_played += 1
            for entry in e.payload.get("entries", []):
                seat = int(entry["seat"])
                codes = int(entry["codes"])
                loser_rounds[seat] = loser_rounds.get(seat, 0) + 1
                codes_lost[seat] = codes_lost.get(seat, 0) + codes
            for seat, score in enumerate(e.payload.get("scores", [])):
                score_curves[seat].append(int(score))
        if e.type == "MatchEnded":
            match_reason = str(e.payload.get("reason", ""))
            scores_final = [int(s) for s in e.payload.get("scores", [])]
            winners = [int(w) for w in e.payload.get("winners", [])]

    # ---- 决策面（E-05/E-08/E-09/E-10 原料） ----
    bid_facts_all = [f for f in facts if f.get("phase") == "bidding"]
    total_bids = len(bid_facts_all)
    bluff_flags: list[bool] = []
    bluffs_by_round: dict[int, set[int]] = {}
    bid_counts: list[int] = []
    zhai_count = 0
    fei_count = 0
    face_one_bids = 0
    bid_facts_used = 0
    for f in bid_facts_all:
        bid = _bid_of_fact(f)
        if bid is None:
            continue
        bid_facts_used += 1
        count, face = bid
        bid_counts.append(count)
        kind = str(f["decision"]["action"].get("kind", ""))
        if kind == "zhai":
            zhai_count += 1
        if kind == "fei":
            fei_count += 1
        if face == 1:
            face_one_bids += 1
        support = f.get("self_support")
        if support is not None and (count - int(support)) >= 2:
            bluff_flags.append(True)
            facts_idx = bid_facts_all.index(f)
            # 定位该决策所在局：取该事实之前最后一个 RoundStarted 的局号
            rn = _round_before(events, facts_idx)
            if rn is not None:
                bluffs_by_round.setdefault(rn, set()).add(int(f.get("seat", -1)))
        else:
            bluff_flags.append(False)

    # E-06：诈唬叫骰为局内终叫且 count ≥ X（05 §6.2 口径）
    final_bid_success: list[bool] = []
    for seg in segments:
        seg_bids = [e for e in seg if e.type == "BidMade"]
        revealed = next((e for e in seg if e.type == "Revealed"), None)
        if not seg_bids or revealed is None:
            continue
        last = seg_bids[-1]
        seat = int(last.payload["seat"])
        rn = _round_no_of_segment(seg)
        if rn not in bluffs_by_round or seat not in bluffs_by_round[rn]:
            continue
        for j in revealed.payload.get("judgments", []):
            if int(j.get("seat", -1)) == seat:
                final_bid_success.append(bool(j.get("stood")))
                break

    # E-09 后半：过 1（ones_called 置真）之后 face==1 叫骰占比
    one_after_total = 0
    one_after_face_one = 0
    ones_called_seen = False
    for e in events:
        if e.type == "BidMade":
            if bool(e.payload.get("ones_called")):
                ones_called_seen = True
            elif ones_called_seen and int(e.payload.get("face", 0)) == 1:
                one_after_face_one += 1
            if ones_called_seen:
                one_after_total += 1

    # ---- 行为面（E-11/E-12/E-13/E-14/E-15 原料） ----
    taunts = tuple(t.lower() for t in taunt_words)
    quote_lens: list[int] = []
    taunt_quotes = 0
    thinking_lens: list[int] = []
    latency: list[int] = []
    usage_in: list[int] = []
    usage_out: list[int] = []
    usage_think: list[int] = []
    degraded_total = 0
    decisions_total = 0
    for f in _facts(events, include_degraded=True):
        decisions_total += 1
        if f.get("degraded"):
            degraded_total += 1
        decision = f.get("decision", {})
        q = str(decision.get("quote", ""))
        quote_lens.append(len(q))
        if q and any(w in q.lower() for w in taunts):
            taunt_quotes += 1
        th = decision.get("thinking")
        if isinstance(th, str) and th:
            thinking_lens.append(len(th))
        env = _envelope_of(f)
        if env:
            latency.append(int(env.get("latency_ms", 0)))
            usage = env.get("usage", {})
            usage_in.append(int(usage.get("input", usage.get("prompt_tokens", 0))))
            usage_out.append(int(usage.get("output", usage.get("completion_tokens", 0))))
            usage_think.append(int(usage.get("reasoning", 0)))

    # E-13：P(该叫骰后立即被挑战 | 台词含挑衅) − P(…| 无挑衅)——只报相关不判因果
    bid_seq: list[dict[str, Any]] = []
    for e in events:
        if e.type == "BidMade":
            q = str(e.payload.get("quote", ""))
            bid_seq.append({"taunt": any(w in q.lower() for w in taunts), "challenged": False})
        elif e.type == "ChallengeMade" and bid_seq:
            bid_seq[-1]["challenged"] = True
    after_taunt = [b["challenged"] for b in bid_seq if b["taunt"]]
    after_plain = [b["challenged"] for b in bid_seq if not b["taunt"]]
    p_after_taunt = round(sum(after_taunt) / len(after_taunt), 4) if after_taunt else None
    p_after_plain = round(sum(after_plain) / len(after_plain), 4) if after_plain else None
    taunt_lift = (
        round(p_after_taunt - p_after_plain, 4)
        if p_after_taunt is not None and p_after_plain is not None
        else None
    )

    # ---- E-07：挑战正确率（分开杀/跳杀/连杀） ----
    chal_total: dict[str, int] = {}
    chal_correct: dict[str, int] = {}
    for seg in segments:
        chal = next((e for e in seg if e.type == "ChallengeMade"), None)
        revealed = next((e for e in seg if e.type == "Revealed"), None)
        if chal is None or revealed is None:
            continue
        kind = str(chal.payload.get("kind", "open"))
        for j in revealed.payload.get("judgments", []):
            if int(j.get("seat", -1)) in [int(t) for t in chal.payload.get("targets", [])]:
                chal_total[kind] = chal_total.get(kind, 0) + 1
                if not j.get("stood"):
                    chal_correct[kind] = chal_correct.get(kind, 0) + 1
    total_chal = sum(chal_total.values())
    correct_chal = sum(chal_correct.values())

    # ---- E-08：飞斋锁死局（局内出现 count ≥ 5N 叫骰） ----
    capped_rounds = sum(
        1
        for seg in segments
        if any(e.type == "BidMade" and int(e.payload.get("count", 0)) >= total_dice for e in seg)
    )

    bluff_rate = (
        round(sum(1 for b in bluff_flags if b) / len(bluff_flags), 4) if bluff_flags else None
    )
    metrics: dict[str, Any] = {
        "match_id": next(
            (str(e.payload.get("match_id")) for e in events if e.type == "MatchStarted"), ""
        ),
        "status_reason": match_reason,
        "match_ended": bool(scores_final) or bool(winners),
        "rounds_played": rounds_played,
        "roster": roster,
        "player_count": player_count,
        "winners": winners,
        "scores_final": scores_final,
        # 竞技面
        "E03_score_curves": {str(k): v for k, v in score_curves.items()},
        "E04_loser_rounds": {str(k): v for k, v in loser_rounds.items()},
        "E04_codes_lost": {str(k): v for k, v in codes_lost.items()},
        "E04_rounds_played": rounds_played,
        # 决策面
        "E05_bluff_rate": bluff_rate,
        "E05_bluff_decisions": sum(1 for b in bluff_flags if b),
        "E05_bid_decisions": bid_facts_used,
        "E06_bluff_final_success_rate": (
            round(sum(1 for s in final_bid_success if s) / len(final_bid_success), 4)
            if final_bid_success
            else None
        ),
        "E06_bluff_final_samples": len(final_bid_success),
        "E07_challenge_correct_rate": (round(correct_chal / total_chal, 4) if total_chal else None),
        "E07_by_kind": {
            k: {
                "total": chal_total[k],
                "correct_rate": round(chal_correct.get(k, 0) / chal_total[k], 4),
            }
            for k in chal_total
        },
        "E08_zhai_bids": zhai_count,
        "E08_fei_bids": fei_count,
        "E08_capped_bid_rounds": capped_rounds,
        "E09_face_one_bid_rate": round(face_one_bids / total_bids, 4) if total_bids else None,
        "E09_after_ones_called_face_one_rate": (
            round(one_after_face_one / one_after_total, 4) if one_after_total else None
        ),
        "E10_avg_bid_level": (
            round(statistics.mean(bid_counts) / total_dice, 4) if bid_counts else None
        ),
        # 行为面
        "E11_quote_rate": (
            round(sum(1 for q in quote_lens if q) / len(quote_lens), 4) if quote_lens else None
        ),
        "E11_avg_quote_len": round(statistics.mean(quote_lens), 2) if quote_lens else None,
        "E12_taunt_hit_rate": (
            round(taunt_quotes / len([q for q in quote_lens if q]), 4) if any(quote_lens) else None
        ),
        "E13_taunt_deterrence_lift": taunt_lift,
        "E13_after_taunt_challenged": p_after_taunt,
        "E13_after_plain_challenged": p_after_plain,
        # 成本面（E-14）
        "E14_latency_ms_avg": round(statistics.mean(latency), 1) if latency else None,
        "E14_usage_avg": {
            "input": round(statistics.mean(usage_in), 1) if usage_in else None,
            "output": round(statistics.mean(usage_out), 1) if usage_out else None,
            "reasoning": round(statistics.mean(usage_think), 1) if usage_think else None,
        },
        "E14_degradation_rate": (
            round(degraded_total / decisions_total, 4) if decisions_total else None
        ),
        # E-15（仅 EVE 数字部分；语义一致性归 AI 评述）
        "E15_thinking_coverage": (
            round(len(thinking_lens) / decisions_total, 4) if decisions_total else None
        ),
        "E15_thinking_avg_len": round(statistics.mean(thinking_lens), 2) if thinking_lens else None,
    }
    return metrics


def _round_before(events: Sequence[Event], facts_index: int) -> int | None:
    """第 ``facts_index`` 个 DecisionFacts 所在局号（按事件流顺序回溯）。"""
    facts_seen = 0
    round_no: int | None = None
    for e in events:
        if e.type == "RoundStarted":
            round_no = int(e.payload.get("round_no", 0))
        if e.type == "DecisionFacts":
            if facts_seen == facts_index:
                return round_no
            facts_seen += 1
    return round_no


def _round_no_of_segment(seg: Sequence[Event]) -> int | None:
    for e in seg:
        if e.type == "RoundStarted":
            return int(e.payload.get("round_no", 0))
    return None


def aggregate_batch(
    match_metrics: Sequence[dict[str, Any]],
    *,
    include_abandoned: bool = False,
) -> dict[str, Any]:
    """跨桌聚合（05 §6.3 产出物：一行 = 一模型一桌指标 → 聚合表）。

    弃局默认整桌剔除（05 §2.5：不进任何评测统计）。
    """
    eligible = [m for m in match_metrics if include_abandoned or m.get("match_ended")]

    def avg(key: str) -> float | None:
        vals = [m[key] for m in eligible if isinstance(m.get(key), (int, float))]
        return round(statistics.mean(vals), 4) if vals else None

    # E-01 场胜率（跨桌按座位聚合；并列各计一胜）
    wins: dict[str, int] = {}
    tables: dict[str, int] = {}
    for m in eligible:
        scores = m.get("scores_final", [])
        min_s = min(scores) if scores else None
        for seat, score in enumerate(scores):
            key = f"seat{seat}"
            tables[key] = tables.get(key, 0) + 1
            if min_s is not None and score == min_s:
                wins[key] = wins.get(key, 0) + 1

    seat_codes: dict[str, list[int]] = {}
    seat_scores: dict[str, list[int]] = {}
    for m in eligible:
        for seat, codes in (m.get("E04_codes_lost") or {}).items():
            seat_codes.setdefault(seat, []).append(int(codes))
        for seat, score in enumerate(m.get("scores_final", [])):
            seat_scores.setdefault(f"seat{seat}", []).append(score)

    return {
        "tables_total": len(match_metrics),
        "tables_eligible": len(eligible),
        "E01_win_rate_by_seat": {
            seat: round(wins[seat] / tables[seat], 4) for seat in wins if tables.get(seat)
        },
        "E02_avg_final_score_by_seat": {
            seat: round(statistics.mean(vals), 2) for seat, vals in seat_scores.items() if vals
        },
        "E04_avg_codes_lost_by_seat": {
            seat: round(statistics.mean(vals), 2) for seat, vals in seat_codes.items() if vals
        },
        "E05_bluff_rate_avg": avg("E05_bluff_rate"),
        "E06_bluff_final_success_avg": avg("E06_bluff_final_success_rate"),
        "E07_challenge_correct_avg": avg("E07_challenge_correct_rate"),
        "E09_face_one_bid_rate_avg": avg("E09_face_one_bid_rate"),
        "E10_avg_bid_level_avg": avg("E10_avg_bid_level"),
        "E11_quote_rate_avg": avg("E11_quote_rate"),
        "E12_taunt_hit_rate_avg": avg("E12_taunt_hit_rate"),
        "E13_taunt_deterrence_lift_avg": avg("E13_taunt_deterrence_lift"),
        "E14_latency_ms_avg": avg("E14_latency_ms_avg"),
        "E14_degradation_rate_avg": avg("E14_degradation_rate"),
        "E15_thinking_coverage_avg": avg("E15_thinking_coverage"),
    }
