"""单桌与批量评测报告（05 §6.5）：Markdown 产物，数字全部来自程序指标层。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

__all__ = ["render_match_report", "render_batch_report"]


def render_match_report(metrics: dict[str, Any]) -> str:
    """单桌报告（05 §6.5：结算摘要 + E 指标表）。"""
    g = metrics.get
    lines: list[str] = [
        f"# 桌局评测报告 · {g('match_id', '')}",
        "",
        f"- 局数：{g('rounds_played')}（终局原因：{g('status_reason') or '—'}）",
        f"- 终局积分：{g('scores_final')}（胜者：{[f'{w}号' for w in g('winners', [])]}）",
        "",
        "## E 指标（05 §6.2 口径，全部程序产出）",
        "",
        "| 编号 | 指标 | 值 |",
        "| --- | --- | --- |",
        f"| E-02 | 终局积分 | {g('scores_final')} |",
        "| E-03 | 积分曲线 | 见附表（逐局累计） |",
        f"| E-04 | 各席位负局数 / 受罚码数 | {g('E04_loser_rounds')} / {g('E04_codes_lost')} |",
        f"| E-05 | 诈唬频率 | {g('E05_bluff_rate')}（诈唬叫骰 "
        f"{g('E05_bluff_decisions')}/{g('E05_bid_decisions')}） |",
        f"| E-06 | 诈唬终叫成功率 | {g('E06_bluff_final_success_rate')}"
        f"（样本 {g('E06_bluff_final_samples')}） |",
        f"| E-07 | 挑战正确率 | {g('E07_challenge_correct_rate')}"
        f"（分链：{json.dumps(g('E07_by_kind', {}), ensure_ascii=False)}） |",
        f"| E-08 | 转斋/飞斋次数 | {g('E08_zhai_bids')} / {g('E08_fei_bids')}"
        f"；锁死局 {g('E08_capped_bid_rounds')} |",
        f"| E-09 | 过 1 触发（face=1 叫骰占比） | {g('E09_face_one_bid_rate')}"
        f"；过 1 后含 1 占比 {g('E09_after_ones_called_face_one_rate')} |",
        f"| E-10 | 叫量水位（均叫量/5N） | {g('E10_avg_bid_level')} |",
        f"| E-11 | 台词率 / 均长 | {g('E11_quote_rate')} / {g('E11_avg_quote_len')} |",
        f"| E-12 | 挑衅词表命中 | {g('E12_taunt_hit_rate')} |",
        f"| E-13 | 台词威慑相关（差值） | {g('E13_taunt_deterrence_lift')}"
        f"（含挑衅 {g('E13_after_taunt_challenged')} / 无 {g('E13_after_plain_challenged')}"
        f"，只报相关不判因果） |",
        f"| E-14 | 均延迟 / 降级率 | {g('E14_latency_ms_avg')}ms / {g('E14_degradation_rate')} |",
        f"| E-15 | thinking 覆盖 / 均长 | {g('E15_thinking_coverage')}"
        f" / {g('E15_thinking_avg_len')}（语义一致性归 AI 评述） |",
        "",
        "> 本报告数字全部由程序产出（02 §8.1 统计唯一权威）。",
    ]
    curves = metrics.get("E03_score_curves")
    if curves:
        lines.append("")
        lines.append("## 附表 · 积分曲线（逐局累计）")
        lines.append("")
        lines.append("```")
        for seat, curve in sorted(curves.items()):
            lines.append(f"{seat}号: {curve}")
        lines.append("```")
    return "\n".join(lines) + "\n"


def render_batch_report(
    aggregate: dict[str, Any],
    match_reports: Sequence[str],
) -> str:
    """批量报告（05 §6.5：跨桌聚合 + 单桌报告汇编）。"""
    a = aggregate.get
    lines: list[str] = [
        "# 批量评测报告（跨桌聚合）",
        "",
        f"- 桌局总数：{a('tables_total')}（纳入聚合：{a('tables_eligible')}）",
        "",
        "## 聚合指标（跨桌均值）",
        "",
        "| 编号 | 指标 | 值 |",
        "| --- | --- | --- |",
        "| E-01 | 场胜率（按座位） | "
        f"{json.dumps(a('E01_win_rate_by_seat', {}), ensure_ascii=False)} |",
        "| E-02 | 均终局积分（按座位） | "
        f"{json.dumps(a('E02_avg_final_score_by_seat', {}), ensure_ascii=False)} |",
        "| E-04 | 均受罚码数（按座位） | "
        f"{json.dumps(a('E04_avg_codes_lost_by_seat', {}), ensure_ascii=False)} |",
        f"| E-05 | 诈唬频率均值 | {a('E05_bluff_rate_avg')} |",
        f"| E-06 | 诈唬终叫成功率均值 | {a('E06_bluff_final_success_avg')} |",
        f"| E-07 | 挑战正确率均值 | {a('E07_challenge_correct_avg')} |",
        f"| E-09 | 过 1 触发率均值 | {a('E09_face_one_bid_rate_avg')} |",
        f"| E-10 | 叫量水位均值 | {a('E10_avg_bid_level_avg')} |",
        f"| E-11 | 台词率均值 | {a('E11_quote_rate_avg')} |",
        f"| E-12 | 挑衅词表命中均值 | {a('E12_taunt_hit_rate_avg')} |",
        f"| E-13 | 台词威慑相关均值 | {a('E13_taunt_deterrence_lift_avg')} |",
        f"| E-14 | 均延迟 / 降级率 | {a('E14_latency_ms_avg')} / "
        f"{a('E14_degradation_rate_avg')} |",
        f"| E-15 | thinking 覆盖均值 | {a('E15_thinking_coverage_avg')} |",
        "",
        "> 数字全部由程序产出；AI 评述（如有）另附且强制标注（05 §6.4 三禁）。",
        "",
        "---",
        "",
        "# 单桌报告汇编",
        "",
    ]
    lines.extend(match_reports)
    return "\n".join(lines) + "\n"
