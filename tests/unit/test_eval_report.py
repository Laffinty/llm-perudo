"""P7 单元测试：评测报告（05 §6.5）与 AI 评述（05 §6.4 三禁）。"""

from __future__ import annotations

from perudo.adapters.sdk.transport import CompletionResponse, Transport
from perudo.engine.config import MatchConfig
from perudo.engine.match import Match
from perudo.eval.commentary import Commentator
from perudo.eval.metrics import compute_match_metrics
from perudo.eval.report import render_batch_report, render_match_report
from perudo.players.bot import ConservativeBot


def _bot_match(tmp_path: Path, seed: int = 21):
    match = Match.create(
        "m_report",
        MatchConfig(end_threshold=6, max_rounds=40),
        [ConservativeBot(f"bot{i}") for i in range(4)],
        seed=seed,
    )
    match.run_to_end()
    return match


def test_match_report_renders_all_metrics(tmp_path: Path) -> None:
    """单桌报告：E 指标表全键渲染 + 程序产出声明（05 §6.5）。"""
    match = _bot_match(tmp_path)
    metrics = compute_match_metrics(match.event_log())
    report = render_match_report(metrics)
    assert metrics["match_id"] in report
    for eid in (
        "E-04",
        "E-05",
        "E-06",
        "E-07",
        "E-08",
        "E-09",
        "E-10",
        "E-11",
        "E-12",
        "E-13",
        "E-14",
        "E-15",
    ):
        assert eid in report
    assert "程序产出" in report


def test_batch_report_renders_aggregate(tmp_path: Path) -> None:
    """批量报告：聚合表 + 单桌汇编 + AI 评述占位声明。"""
    match = _bot_match(tmp_path)
    metrics = compute_match_metrics(match.event_log())
    single = render_match_report(metrics)
    agg = {
        "tables_total": 1,
        "tables_eligible": 1,
        "E01_win_rate_by_seat": {"seat0": 0.25},
        "E02_avg_final_score_by_seat": {"seat0": 3.0},
        "E04_avg_codes_lost_by_seat": {"seat0": 3.0},
        "E05_bluff_rate_avg": None,
        "E06_bluff_final_success_avg": None,
        "E07_challenge_correct_avg": None,
        "E09_face_one_bid_rate_avg": None,
        "E10_avg_bid_level_avg": None,
        "E11_quote_rate_avg": None,
        "E12_taunt_hit_rate_avg": None,
        "E13_taunt_deterrence_lift_avg": None,
        "E14_latency_ms_avg": None,
        "E14_degradation_rate_avg": None,
        "E15_thinking_coverage_avg": None,
    }
    report = render_batch_report(agg, [single])
    assert "批量评测报告" in report and "单桌报告汇编" in report
    assert "E-01" in report


def test_commentary_reads_metrics_and_tags_output(tmp_path: Path) -> None:
    """AI 评述：只读公开层摘要 + 指标表；产出强制【AI 评述】标注（05 §6.4）。"""
    from perudo.adapters.sdk.transport import CompletionRequest, CompletionResponse

    captured: dict = {}

    class ScriptedTransport(Transport):
        def complete(self, request: CompletionRequest) -> CompletionResponse:
            captured["request"] = request
            return CompletionResponse(content="各玩家牌风稳健。", usage={"input": 10, "output": 5})

    match = _bot_match(tmp_path)
    metrics = compute_match_metrics(match.event_log())
    commentator = Commentator(
        ScriptedTransport(), provider="glm", model="glm-5.3-flash", api_key="test"
    )
    text = commentator.comment(
        match_id="m_report",
        public_summary="第 1 局……（公开层渲染摘要）",
        metrics=metrics,
    )
    assert text.startswith("【AI 评述】")
    assert "稳健" in text
    req = captured["request"]
    assert req.model == "glm-5.3-flash"
    system = req.messages[0]["content"]
    assert "禁止改写任何统计数字" in system  # 三禁声明入提示词（02 §8.1）
    user = req.messages[1]["content"]
    assert "已算指标表" in user


def test_commentary_does_not_receive_private_layer(tmp_path: Path) -> None:
    """三禁输入面：评述请求不含评测层 DecisionFacts / 私密层种子（02 §5.2）。"""
    from perudo.adapters.sdk.transport import CompletionRequest, CompletionResponse

    captured: dict = {}

    class RecordingTransport(Transport):
        def complete(self, request: CompletionRequest) -> CompletionResponse:
            captured["user"] = request.messages[-1]["content"]
            return CompletionResponse(content="评述。")

    match = _bot_match(tmp_path)
    metrics = compute_match_metrics(match.event_log())
    commentator = Commentator(RecordingTransport(), api_key="test")
    text = commentator.comment(
        match_id="m_report",
        public_summary="（摘要）",
        metrics=metrics,
    )
    assert text.startswith("【AI 评述】")
    user_text = captured["user"]
    assert "SeedRecorded" not in user_text
    assert "DecisionFacts" not in user_text
    assert "HandShaken" not in user_text
