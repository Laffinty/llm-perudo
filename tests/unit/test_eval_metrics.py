"""P7 单元测试：评测指标（05 §6.2 E-01~E-15 口径）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from perudo.adapters.deepseek import make_player as make_deepseek
from perudo.adapters.sdk.config import AdapterConfig, PersonaConfig
from perudo.engine.config import MatchConfig
from perudo.engine.match import Match
from perudo.eval.metrics import (
    DEFAULT_TAUNT_WORDS,
    aggregate_batch,
    compute_match_metrics,
    match_abandoned,
)


def _config(**changes: object) -> MatchConfig:
    from dataclasses import replace

    return replace(MatchConfig(), **changes)  # type: ignore[arg-type]


def _bots(n: int = 4) -> list:
    from perudo.players.bot import ConservativeBot

    return [ConservativeBot(f"bot{i}") for i in range(n)]


def _bot_match(tmp_path: Path, seed: int = 11, threshold: int = 6, max_rounds: int = 60):
    match = Match.create(
        "m_eval",
        _config(end_threshold=threshold, max_rounds=max_rounds),
        _bots(4),
        seed=seed,
        stream_path=tmp_path / "stream.jsonl",
    )
    match.run_to_end()
    return match


@pytest.fixture()
def bot_events(tmp_path: Path):
    match = _bot_match(tmp_path, seed=33)
    return match.event_log()


def test_e01_win_rate_aggregation(tmp_path: Path) -> None:
    """E-01：跨桌场胜率——同主种子两桌聚合（并列各计一胜）。"""
    from perudo.engine.rng import derive_seed
    from perudo.eval.metrics import compute_match_metrics

    batch = []
    for index in range(2):
        match = Match.create(
            "m_e01",
            _config(end_threshold=6, max_rounds=100),
            _bots(4),
            seed=derive_seed(2026, index),
        )
        match.run_to_end()
        batch.append(compute_match_metrics(match.event_log()))
    agg = aggregate_batch(batch)
    assert agg["tables_eligible"] == 2
    assert "seat0" in agg["E01_win_rate_by_seat"]


def test_match_metrics_all_present(bot_events) -> None:
    """E-01~E-15 键全部存在且值类型合法（E-15 仅 EVE 数字部分）。"""
    metrics = compute_match_metrics(bot_events)
    expected_keys = {
        "E03_score_curves",
        "E04_loser_rounds",
        "E04_codes_lost",
        "E05_bluff_rate",
        "E06_bluff_final_success_rate",
        "E07_challenge_correct_rate",
        "E08_zhai_bids",
        "E08_fei_bids",
        "E08_capped_bid_rounds",
        "E09_face_one_bid_rate",
        "E09_after_ones_called_face_one_rate",
        "E10_avg_bid_level",
        "E11_quote_rate",
        "E11_avg_quote_len",
        "E12_taunt_hit_rate",
        "E13_taunt_deterrence_lift",
        "E14_latency_ms_avg",
        "E14_degradation_rate",
        "E15_thinking_coverage",
        "E15_thinking_avg_len",
        "scores_final",
        "rounds_played",
        "match_ended",
    }
    missing = expected_keys - set(metrics)
    assert not missing, f"缺指标键：{missing}"
    assert metrics["match_ended"] is True
    assert 0 <= metrics["E05_bluff_decisions"] <= metrics["E05_bid_decisions"]


def test_degraded_filter(bot_events) -> None:
    """降级回合过滤口径（05 §6.2）：include_degraded 切换改变样本量。"""
    all_metrics = compute_match_metrics(bot_events, include_degraded=True)
    filtered = compute_match_metrics(bot_events, include_degraded=False)
    assert all_metrics["E05_bid_decisions"] >= filtered["E05_bid_decisions"]


def test_abandoned_flag(bot_events) -> None:
    """弃局判定（G-08）：正常终局局不含 ABANDONED 状态。"""
    assert match_abandoned(bot_events) is False


def test_taunt_words_default_not_empty() -> None:
    """N5-04：挑衅词表初版非空（E-12 可算前提）。"""
    assert len(DEFAULT_TAUNT_WORDS) >= 5


def test_real_llm_player_metrics_with_attachments(tmp_path: Path) -> None:
    """LLM 玩家（mock transport）信封经评测层进入 E-14（离线）。"""
    from perudo.adapters.sdk.transport import CompletionResponse, Transport

    class EchoTransport(Transport):
        def complete(self, request):
            user_text = request.messages[-1]["content"]
            import re

            payloads = re.findall(r'\{"t":"(?:bid|challenge|response)"[^}]*\}', user_text)
            if payloads:
                body = json.dumps({"action": json.loads(payloads[0]), "quote": "跟你说，稳阵"})
            else:
                body = (
                    '{"action": {"t": "bid", "kind": "normal", "count": 6, "face": 3}, "quote": ""}'
                )
            return CompletionResponse(
                content=body,
                usage={"input": 100, "output": 20},
            )

    config = AdapterConfig(
        provider="deepseek",
        model="deepseek-v4-flash",
        api_key_ref="env:DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com",
        persona=PersonaConfig(name="靓仔坤"),
        legal_actions_presentation="enumerate",
        thinking="off",
    )
    roster: list = [
        make_deepseek(config, EchoTransport(), api_key="test"),
        *_bots(4)[1:],
    ]
    match = Match.create("m_llm_eval", _config(end_threshold=6, max_rounds=50), roster, seed=7)
    match.run_to_end()
    metrics = compute_match_metrics(match.event_log())
    assert metrics["E14_latency_ms_avg"] is not None
    assert metrics["E14_usage_avg"]["input"] is not None


import json  # noqa: E402 —— 供上面 echo 测试的 json 使用
