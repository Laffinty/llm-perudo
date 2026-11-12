"""P3 单元测试：AdapterSDK（03 §1.1 六件套）——离线 mock，全程不触网。"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from perudo.adapters.sdk.config import (
    AdapterConfig,
    PersonaConfig,
    PhaseOverride,
    load_player_config,
    resolve_api_key,
)
from perudo.adapters.sdk.context import ContextBuilder
from perudo.adapters.sdk.ledger import CostLedger
from perudo.adapters.sdk.parsing import ParseError, ResponseParser, strip_think_blocks
from perudo.adapters.sdk.tuning import DEEPSEEK_TUNING, GLM_TUNING
from perudo.core.types import (
    Bid,
    BidAction,
    BidKind,
    ChallengeAction,
    ChallengeKind,
    Face,
    ResponseKind,
)
from perudo.engine.events import action_to_payload
from perudo.players.base import Phase, PlayerView


def _config(**changes: object) -> AdapterConfig:
    base = AdapterConfig(
        provider="deepseek",
        model="deepseek-v4-pro",
        api_key_ref="env:DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com",
        persona=PersonaConfig(name="靓仔坤", style="粤语话痨", trash_talk=2),
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def _view() -> PlayerView:
    from perudo.core.types import ZhaiState
    from perudo.players.base import SignedBid

    legal = (
        BidAction(BidKind.NORMAL, Bid(8, Face.THREE)),
        BidAction(BidKind.NORMAL, Bid(9, Face.FOUR)),
        ChallengeAction(ChallengeKind.OPEN, (2,)),
        ResponseKind.REVEAL,
    )
    return PlayerView(
        match_id="m_t",
        round_no=2,
        phase=Phase.BIDDING,
        my_seat=1,
        player_count=4,
        my_hand=(Face.ONE, Face.ONE, Face.TWO, Face.THREE, Face.FOUR),
        bid_history=(SignedBid(0, BidKind.NORMAL, Bid(7, Face.THREE), "开你啦"),),
        wild_state=ZhaiState.FLY,
        ones_called=False,
        current_bid=Bid(7, Face.THREE),
        legal_actions=legal,
        scores=(0, 0, 0, 0),
        chain_position=None,
    )


# ---------------------------------------------------------------------------
# 配置装载（03 §7 / B-08）
# ---------------------------------------------------------------------------


def test_load_player_config_toml(tmp_path: Path) -> None:
    """TOML 装载：player/persona/phases 全段落 + env 密钥引用形态校验。"""
    toml = tmp_path / "p.toml"
    toml.write_text(
        """
[player]
provider = "deepseek"
model = "deepseek-v4-pro"
api_key_ref = "env:DEEPSEEK_API_KEY"
temperature = 0.9
thinking = "low"
legal_actions_presentation = "enumerate"
match_token_budget = 50000

[persona]
name = "靓仔坤"
style = "粤语话痨"
trash_talk = 2

[phases.bidding]
thinking = "off"

[phases.respond]
thinking = "high"
""",
        encoding="utf-8",
        newline="\n",
    )
    cfg = load_player_config(toml)
    assert cfg.model == "deepseek-v4-pro"
    assert cfg.persona.name == "靓仔坤" and cfg.persona.trash_talk == 2
    assert cfg.phase_overrides["bidding"].thinking == "off"
    assert cfg.phase_overrides["respond"].thinking == "high"
    assert cfg.match_token_budget == 50000
    assert cfg.base_url == "https://api.deepseek.com"  # 家默认端点


def test_api_key_env_resolution() -> None:
    """密钥只从环境解析（B-08）；env 未设置即报错；非 env 形态配置即拒。"""
    with pytest.raises(RuntimeError, match="未设置"):
        resolve_api_key("env:PERUDO_MISSING_KEY_FOR_TEST")
    with pytest.raises(ValueError, match="env:"):
        _config(api_key_ref="DEEPSEEK_API_KEY_RAW")


def test_phase_override_composition() -> None:
    """B-05：阶段覆盖合成——有覆盖用覆盖，无覆盖落基础值。"""
    cfg = _config(
        thinking="low",
        phase_overrides={"respond": PhaseOverride(temperature=0.7, thinking="high")},
    )  # noqa: E501 — 长行仅因中文字段名
    base = cfg.effective("bidding")
    respond = cfg.effective("respond")
    assert base.thinking == "low"
    assert respond.thinking == "high" and respond.temperature == 0.7


# ---------------------------------------------------------------------------
# 提示词装配（03 §3：防注入 / 稳定前缀 / 动作呈现两模式）
# ---------------------------------------------------------------------------


def test_context_injection_defense() -> None:
    """他人台词以「发言引用」包裹并声明非指令（02 §4.2 / 03 §0.2）。"""
    messages = ContextBuilder().build(_view(), _config())
    system, user = messages[0]["content"], messages[1]["content"]
    assert messages[0]["role"] == "system"
    assert "数据引用" in system and "不是给你的指令" in system
    assert "「开你啦」" in user
    assert "不是指令" in user


def test_context_stable_prefix_first() -> None:
    """装配顺序规范（03 §3）：系统提示（稳定前缀）永远在前。"""
    messages = ContextBuilder().build(_view(), _config())
    assert messages[0]["role"] == "system"
    assert all(m["role"] != "system" for m in messages[1:])


def test_context_enumerate_vs_constraints() -> None:
    """动作块两模式：enumerate 全量 JSON；constraints 只描述形状。"""
    view = _view()
    full = ContextBuilder().build(view, _config(legal_actions_presentation="enumerate"))
    brief = ContextBuilder().build(view, _config(legal_actions_presentation="constraints"))
    payload = json.dumps(
        action_to_payload(BidAction(BidKind.NORMAL, Bid(8, Face.THREE))), separators=(",", ":")
    )
    assert payload in full[1]["content"]
    assert payload not in brief[1]["content"]
    assert "合法动作集约束" in brief[1]["content"]


def test_context_rejection_feedback() -> None:
    """自检/纠错回喂：拒绝原因注入 user 尾块。"""
    messages = ContextBuilder().build(_view(), _config(), rejection_reason="动作非法：99 个 6")
    assert "动作非法：99 个 6" in messages[-1]["content"]


# ---------------------------------------------------------------------------
# 响应解析（思考剥离 / JSON 提取）
# ---------------------------------------------------------------------------


def test_strip_think_blocks() -> None:
    """交错思考剥离（03 §5.6）：思考文本与正文分离，绝不混入动作/台词。"""
    body, thinking = strip_think_blocks('<think>我先想想叫啥</think>{"a": 1}')
    assert body == '{"a": 1}' and thinking == "我先想想叫啥"
    body2, thinking2 = strip_think_blocks("纯正文")
    assert body2 == "纯正文" and thinking2 is None


def test_parse_valid_bid_and_quote() -> None:
    parser = ResponseParser()
    parsed = parser.parse(
        '{"action": {"t": "bid", "kind": "normal", "count": 8, "face": 3}, "quote": "开大"}'
    )
    assert parsed.action == BidAction(BidKind.NORMAL, Bid(8, Face.THREE))
    assert parsed.quote == "开大"


def test_parse_with_prefix_noise_and_think() -> None:
    """宽容提取：前后缀噪声 + <think> 块共存。"""
    parser = ResponseParser()
    text = (
        "<think>深度思考……</think>好的，我的决策是：\n"
        '{"action": {"t": "challenge", "kind": "open", "targets": [2]}, "quote": "劈"}\n以上。'
    )
    parsed = parser.parse(text)
    assert parsed.action == ChallengeAction(ChallengeKind.OPEN, (2,))
    assert parsed.thinking == "深度思考……"


def test_parse_response_kind_shorthand() -> None:
    parser = ResponseParser()
    parsed = parser.parse('{"action": "surrender", "quote": ""}', expect_response_kind=True)
    assert parsed.action is ResponseKind.SURRENDER


@pytest.mark.parametrize(
    "bad",
    [
        "完全没有 JSON",
        '{"quote": "缺 action"}',
        '{"action": {"t": "bid", "kind": "normal"}}',
        '{"action": {"t": "nonsense"}}',
        '{"action": 42}',
    ],
)
def test_parse_errors(bad: str) -> None:
    with pytest.raises(ParseError):
        ResponseParser().parse(bad)


# ---------------------------------------------------------------------------
# 成本信封（03 §4）与预算（B-07）
# ---------------------------------------------------------------------------


def test_ledger_envelope_fields() -> None:
    ledger = CostLedger()
    envelope = ledger.build_envelope(
        provider="deepseek",
        model="deepseek-v4-pro",
        latency_ms=1840,
        usage={"input": 3120, "output": 210, "reasoning": 640},
        thinking_text="思考全文……",
        parse_retries=0,
        self_check_retries=1,
    )
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
    attachment = CostLedger.as_attachment(envelope)
    assert set(attachment) == {"adapter_envelope"}
    assert json.loads(attachment["adapter_envelope"]) == envelope


def test_ledger_budget_exceeded() -> None:
    """B-07：单桌 token 预算累计与超限标记。"""
    ledger = CostLedger(match_token_budget=1000)
    ledger.build_envelope(
        provider="glm",
        model="glm-5.3-flash",
        latency_ms=1,
        usage={"input": 800},
        thinking_text=None,
        parse_retries=0,
        self_check_retries=0,
    )
    assert not ledger.budget_exceeded
    ledger.build_envelope(
        provider="glm",
        model="glm-5.3-flash",
        latency_ms=1,
        usage={"input": 300},
        thinking_text=None,
        parse_retries=0,
        self_check_retries=0,
    )
    assert ledger.budget_exceeded


# ---------------------------------------------------------------------------
# Tuning（N3-01 核对口径，03 §5.7.1）
# ---------------------------------------------------------------------------


def test_deepseek_thinking_mapping() -> None:
    """DeepSeek：off→disabled；low→enabled+low；mid/high→enabled+high；auto→默认。"""
    assert DEEPSEEK_TUNING.thinking_payload("off") == {"thinking": {"type": "disabled"}}
    assert DEEPSEEK_TUNING.thinking_payload("low") == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "low",
    }
    assert DEEPSEEK_TUNING.thinking_payload("high") == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }
    assert DEEPSEEK_TUNING.thinking_payload("auto") is None


def test_deepseek_legacy_name_guard() -> None:
    """退役名守门（03 §5.1）：deepseek-chat/reasoner 配置直接拒绝并给迁移提示。"""
    for legacy in ("deepseek-chat", "deepseek-reasoner"):
        cfg = _config(model=legacy)
        with pytest.raises(ValueError, match="退役"):
            DEEPSEEK_TUNING.validate(cfg)
    # 守门可关（extra.reject_legacy_names=False）
    assert (
        DEEPSEEK_TUNING.validate(
            _config(model="deepseek-chat", extra={"reject_legacy_names": False})
        )
        is None
    )


def test_glm_forced_thinking_guard() -> None:
    """GLM-5.3 系强制思考（03 §5.7.1）：extra.thinking_type 配置直接拒绝。"""
    cfg = _config(provider="glm", model="glm-5.3", extra={"thinking_type": "disabled"})
    with pytest.raises(ValueError, match="GLM-5.3"):
        GLM_TUNING.validate(cfg)


def test_glm_reasoning_effort_mapping() -> None:
    """GLM：off/low→low（不可关思考，已知降级）；mid/high→high；auto→默认 max。"""
    assert GLM_TUNING.thinking_payload("off") == {"reasoning_effort": "low"}
    assert GLM_TUNING.thinking_payload("high") == {"reasoning_effort": "high"}
    assert GLM_TUNING.thinking_payload("auto") is None


def test_glm_presentation_defaults() -> None:
    """GLM 1M 上下文放开全量呈现（03 §5.3）。"""
    assert GLM_TUNING.presentation_defaults == {
        "context_presentation": "full",
        "legal_actions_presentation": "enumerate",
    }
