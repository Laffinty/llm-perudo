"""P3 真实 API 冒烟（03 M4a 手动验收项，不进 CI——计划 §4.4）。

需要环境变量 DEEPSEEK_API_KEY / GLM_API_KEY；缺键自动跳过。
验收口径：真实 API vs 脚本机器人完整局跑通——由业主持键执行：
``DEEPSEEK_API_KEY=... uv run pytest tests/unit/test_adapters_smoke_real.py -v``
"""

from __future__ import annotations

import json
import os

import pytest

from perudo.adapters.deepseek import make_player as make_deepseek
from perudo.adapters.glm import make_player as make_glm
from perudo.adapters.sdk.config import AdapterConfig, PersonaConfig
from perudo.engine.config import MatchConfig
from perudo.engine.events import EventType
from perudo.engine.match import Match
from perudo.engine.state import MatchStatus
from perudo.players.bot import ConservativeBot

_HAS_DS = bool(os.environ.get("DEEPSEEK_API_KEY"))
_HAS_GLM = bool(os.environ.get("GLM_API_KEY"))


def _ds_config() -> AdapterConfig:
    return AdapterConfig(
        provider="deepseek",
        model=os.environ.get("PERUDO_DS_MODEL", "deepseek-v4-flash"),
        api_key_ref="env:DEEPSEEK_API_KEY",
        persona=PersonaConfig(name="靓仔坤", style="粤语话痨", trash_talk=2),
        thinking="off",
        timeout_ms=60000,
    )


def _glm_config() -> AdapterConfig:
    return AdapterConfig(
        provider="glm",
        model=os.environ.get("PERUDO_GLM_MODEL", "glm-5.3-flash"),
        api_key_ref="env:GLM_API_KEY",
        persona=PersonaConfig(name="细霞", style="广州西关口音", trash_talk=1),
        thinking="low",
        timeout_ms=60000,
    )


@pytest.mark.skipif(not _HAS_DS, reason="DEEPSEEK_API_KEY 未设置（真实 API 冒烟为手动验收项）")
def test_deepseek_real_api_single_decision() -> None:
    """真实 DeepSeek API：单决策往返——产出合法动作 + 思考剥离 + 信封齐全。"""
    from perudo.core.types import Bid, BidAction, BidKind, Face, ZhaiState
    from perudo.players.base import Phase, PlayerView

    player = make_deepseek(_ds_config(), backoff_base=1.0)

    view = PlayerView(
        match_id="smoke",
        round_no=1,
        phase=Phase.BIDDING,
        my_seat=0,
        player_count=4,
        my_hand=(Face.ONE, Face.ONE, Face.TWO, Face.THREE, Face.FOUR),
        bid_history=(),
        wild_state=ZhaiState.FLY,
        ones_called=False,
        current_bid=None,
        legal_actions=(
            BidAction(BidKind.NORMAL, Bid(6, Face.THREE)),
            BidAction(BidKind.NORMAL, Bid(6, Face.FOUR)),
            BidAction(BidKind.ZHAI, Bid(4, Face.TWO)),
        ),
        scores=(0, 0, 0, 0),
        chain_position=None,
    )
    decision = player.decide(view)
    assert decision.action == view.legal_actions[0] or decision.action in view.legal_actions
    envelope = json.loads(decision.attachments["adapter_envelope"])
    assert envelope["provider"] == "deepseek"
    assert envelope["usage"], "真实调用必有 token 用量"


@pytest.mark.skipif(not _HAS_GLM, reason="GLM_API_KEY 未设置（真实 API 冒烟为手动验收项）")
def test_glm_real_api_single_decision() -> None:
    """真实 GLM API：单决策往返（reasoning_effort=low，5.3 系强制思考）。"""
    from perudo.core.types import Bid, BidAction, BidKind, Face, ZhaiState
    from perudo.players.base import Phase, PlayerView

    player = make_glm(_glm_config(), backoff_base=1.0)
    view = PlayerView(
        match_id="smoke",
        round_no=1,
        phase=Phase.BIDDING,
        my_seat=0,
        player_count=4,
        my_hand=(Face.ONE, Face.ONE, Face.TWO, Face.THREE, Face.FOUR),
        bid_history=(),
        wild_state=ZhaiState.FLY,
        ones_called=False,
        current_bid=None,
        legal_actions=(
            BidAction(BidKind.NORMAL, Bid(6, Face.THREE)),
            BidAction(BidKind.NORMAL, Bid(6, Face.FOUR)),
            BidAction(BidKind.ZHAI, Bid(4, Face.TWO)),
        ),
        scores=(0, 0, 0, 0),
        chain_position=None,
    )
    decision = player.decide(view)
    assert decision.action in view.legal_actions
    envelope = json.loads(decision.attachments["adapter_envelope"])
    assert envelope["provider"] == "glm"
    assert envelope["thinking_text"] is not None, "5.3 系强制思考必有 reasoning_content"


@pytest.mark.skipif(not (_HAS_DS and _HAS_GLM), reason="需要两家 API key（手动验收项）")
def test_real_llm_vs_bots_short_match() -> None:
    """03 M4a 真实验收：两家 LLM vs 脚本机器人完整短局跑通。"""
    config = MatchConfig(end_threshold=100_000, max_rounds=6)
    roster: list = [
        make_deepseek(_ds_config(), backoff_base=1.0),
        make_glm(_glm_config(), backoff_base=1.0),
        ConservativeBot("bot2"),
        ConservativeBot("bot3"),
    ]
    match = Match.create("m_real_smoke", config, roster, seed=2026)
    match.run_to_end()
    assert match.status is MatchStatus.ENDED
    assert any(e.type == EventType.MATCH_ENDED for e in match.event_log())
