"""P3 集成测试：LLMPlayer 与引擎的对接（03 M4a 验收，离线 Fake Transport）。

- LLM 玩家 vs 脚本机器人完整桌局跑通（02 §4 契约通道）；
- B-04：自检循环不消耗引擎纠错预算（单测证明）；
- 解析/自检耗尽 → AdapterFailure → 引擎故障政策（代打 + 降级）；
- 附件信封经引擎原样入评测层（02 §4.1）。
"""

from __future__ import annotations

import json
import re
from dataclasses import replace

from perudo.adapters.sdk.config import AdapterConfig, PersonaConfig
from perudo.adapters.sdk.player import LLMPlayer
from perudo.adapters.sdk.transport import (
    CompletionRequest,
    CompletionResponse,
    Transport,
    TransportError,
)
from perudo.engine.config import MatchConfig
from perudo.engine.events import EventType
from perudo.engine.match import Match
from perudo.engine.state import MatchStatus
from perudo.players.bot import ConservativeBot

_ACTION_PATTERN = re.compile(r'\{"t":"(?:bid|challenge|response)"[^}]*\}')


def _llm_config(**changes: object) -> AdapterConfig:
    base = AdapterConfig(
        provider="deepseek",
        model="deepseek-v4-pro",
        api_key_ref="env:DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com",
        persona=PersonaConfig(name="靓仔坤", style="粤语话痨", trash_talk=2),
        legal_actions_presentation="enumerate",
        thinking="off",
    )
    return replace(base, **changes)  # type: ignore[arg-type]


class EchoTransport:
    """从动作块抓取第一个合法动作 JSON 原样回包——任意视图下必产出合法决策。"""

    def __init__(self, *, inject_first: str | None = None) -> None:
        self._inject_first = inject_first
        self.calls = 0

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.calls += 1
        if self._inject_first is not None and self.calls == 1:
            return CompletionResponse(content=self._inject_first, usage={"input": 10, "output": 6})
        user_text = request.messages[-1]["content"]
        payloads = _ACTION_PATTERN.findall(user_text)
        if payloads:
            body = json.dumps(
                {"action": json.loads(payloads[0]), "quote": "跟你说，稳阵"},
                ensure_ascii=False,
            )
            return CompletionResponse(content=body, usage={"input": 20, "output": 8})
        # 动作块无 JSON（constraints 模式）→ 交白卷，触发解析重试路径
        return CompletionResponse(content="我想想再说", usage={"input": 20, "output": 2})


class FlakyTransport:
    """前 N 次抛网络错误，之后交给回声逻辑（网络重试测试）。"""

    def __init__(self, failures: int, inner: Transport) -> None:
        self._failures = failures
        self._inner = inner
        self.attempts = 0

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.attempts += 1
        if self.attempts <= self._failures:
            raise TransportError("模拟网络抖动")
        return self._inner.complete(request)


def _bots(n: int) -> list[ConservativeBot]:
    return [ConservativeBot(f"bot{i}") for i in range(n)]


def test_llm_player_vs_bots_full_match() -> None:
    """03 M4a（离线）：LLM 玩家 vs 脚本机器人完整桌局跑通，信封齐全。"""
    config = MatchConfig(end_threshold=40, max_rounds=200)
    roster: list = [LLMPlayer(_llm_config(), EchoTransport(), api_key="test"), *_bots(4)[1:]]
    match = Match.create("m_llm", config, roster, seed=42)
    match.run_to_end()
    assert match.status is MatchStatus.ENDED
    envelope_events = [
        e
        for e in match.event_log()
        if e.type == EventType.DECISION_FACTS
        and "adapter_envelope" in e.payload["decision"]["attachments"]
    ]
    assert envelope_events, "LLM 决策必须带评测附件信封（03 §4）"
    envelope = json.loads(envelope_events[0].payload["decision"]["attachments"]["adapter_envelope"])
    assert envelope["provider"] == "deepseek" and envelope["model"] == "deepseek-v4-pro"
    assert set(envelope) == {
        "provider",
        "model",
        "latency_ms",
        "usage",
        "thinking_text",
        "parse_retries",
        "self_check_retries",
        "degrade_reason",
    }


def test_self_check_loop_does_not_touch_engine_budget() -> None:
    """B-04：首次响应为非法动作 → 适配器自检内部重试 → 合法提交；引擎纠错计数为 0。"""
    # 注入：第一响应为非法动作（99 个 6 超上限），其余回声
    inject = json.dumps(
        {"action": {"t": "bid", "kind": "normal", "count": 99, "face": 6}, "quote": "通杀"},
        ensure_ascii=False,
    )
    config = MatchConfig(end_threshold=40, max_rounds=200)
    roster: list = [
        LLMPlayer(_llm_config(), EchoTransport(inject_first=inject), api_key="test"),
        *_bots(4)[1:],
    ]
    match = Match.create("m_selfcheck", config, roster, seed=42)
    match.run_to_end()
    facts = [e for e in match.event_log() if e.type == EventType.DECISION_FACTS]
    llm_facts = [e for e in facts if e.payload["actor"] == "靓仔坤" and not e.payload["degraded"]]
    assert llm_facts, "LLM 决策事实必须存在"
    assert all(e.payload["correction_count"] == 0 for e in llm_facts), (
        "自检循环必须在适配器内部消化非法动作，不耗引擎纠错预算（B-04）"
    )


class GarbageTransport:
    """恒返回非 JSON 正文（解析耗尽路径测试）。"""

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        return CompletionResponse(content="我想想再说", usage={"input": 5, "output": 2})


def test_parse_exhaustion_degrades_via_engine() -> None:
    """解析耗尽 → AdapterFailure → 引擎故障政策：代打 + TurnDegraded。"""
    config = MatchConfig(end_threshold=100_000, max_rounds=2)
    roster: list = [
        LLMPlayer(
            _llm_config(self_check_retries=0),
            GarbageTransport(),
            api_key="test",
        ),
        *_bots(4)[1:],
    ]
    match = Match.create("m_parse_fail", config, roster, seed=1)
    match.run_to_end()
    degraded = [e for e in match.event_log() if e.type == EventType.TURN_DEGRADED]
    assert degraded and all(e.payload["seat"] == 0 for e in degraded)


def test_network_retries_within_adapter() -> None:
    """网络层重试在适配器内部完成（03 §8）：抖动 2 次仍成功，引擎无感。"""
    config = MatchConfig(end_threshold=40, max_rounds=200)
    echo = EchoTransport()
    flaky = FlakyTransport(failures=2, inner=echo)
    roster: list = [LLMPlayer(_llm_config(net_retries=3), flaky, api_key="test"), *_bots(4)[1:]]
    match = Match.create("m_net", config, roster, seed=42)
    match.run_to_end()
    assert match.status is MatchStatus.ENDED
    assert flaky.attempts >= echo.calls + 2
    degraded = [e for e in match.event_log() if e.type == EventType.TURN_DEGRADED]
    assert not degraded, "网络重试成功后引擎不应看到任何降级"
