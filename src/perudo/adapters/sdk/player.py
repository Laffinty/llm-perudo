"""LLM 玩家：02 §4 契约的第一个正式消费者（03 §0.1 / §1.3）。

一次决策的内部状态机（03 §1.3）：视图 → ContextBuilder → Transport（网络
重试）→ ResponseParser → SelfChecker（不耗引擎预算，B-04）→ 提交引擎。
解析彻底失败 → ``AdapterFailure`` 上抛（引擎代打 + 降级，A-15）；自检耗尽
→ 按原样提交（引擎驳回层接手，走引擎纠错预算）。
"""

from __future__ import annotations

import dataclasses
import time

from perudo.adapters.sdk.config import AdapterConfig
from perudo.adapters.sdk.context import ContextBuilder
from perudo.adapters.sdk.ledger import CostLedger
from perudo.adapters.sdk.parsing import ParseError, ResponseParser
from perudo.adapters.sdk.transport import (
    CompletionRequest,
    RetryController,
    Transport,
)
from perudo.adapters.sdk.tuning import ProviderTuning, get_tuning
from perudo.core.types import BidAction, ChallengeAction, ResponseKind
from perudo.players.base import Decision, Phase, Player, PlayerView

__all__ = ["AdapterFailure", "LLMPlayer"]


class AdapterFailure(RuntimeError):
    """适配器无法产出可提交决策（解析耗尽等）——引擎故障政策接手（A-15）。"""


class LLMPlayer(Player):
    """组装六件套的玩家实现；引擎眼里与脚本机器人无差别（A-09）。"""

    def __init__(
        self,
        config: AdapterConfig,
        transport: Transport | None = None,
        tuning: ProviderTuning | None = None,
        *,
        api_key: str | None = None,
        backoff_base: float = 0.5,
    ) -> None:
        self._config = config
        self._tuning = tuning if tuning is not None else get_tuning(config.provider)
        if self._tuning.validate is not None:
            self._tuning.validate(config)
        cfg = config
        for key, value in (self._tuning.presentation_defaults or {}).items():
            if key == "context_presentation":
                cfg = dataclasses.replace(cfg, context_presentation=value)
            elif key == "legal_actions_presentation":
                cfg = dataclasses.replace(cfg, legal_actions_presentation=value)
        self._config = cfg
        self._api_key = api_key if api_key is not None else _resolve(config.api_key_ref)
        self._transport: Transport = (
            transport if transport is not None else _default_transport(cfg.timeout_ms)
        )
        self._retry = RetryController(cfg.net_retries, backoff_base)
        self._parser = ResponseParser()
        self._ledger = CostLedger(cfg.match_token_budget)
        self._context = ContextBuilder()

    @property
    def name(self) -> str:
        return self._config.persona.name

    @property
    def ledger(self) -> CostLedger:
        """成本台账（B-07 预算检查 / 评测成本面取数）。"""
        return self._ledger

    def decide(self, view: PlayerView) -> Decision:
        phase_name = {
            Phase.BIDDING: "bidding" if view.current_bid is not None else "opening",
            Phase.RESPOND: "respond",
        }[view.phase]
        cfg = self._config.effective(phase_name)
        rejection = view.correction_reason  # 引擎纠错回喂（耗引擎预算的重试）
        parse_retries = 0
        self_check_retries = 0
        started = time.monotonic()
        thinking_text: str | None = None
        usage: dict[str, int] = {}
        while True:
            messages = self._context.build(view, cfg, rejection_reason=rejection)
            request = CompletionRequest(
                base_url=cfg.base_url,
                api_key=self._api_key,
                model=cfg.model,
                messages=messages,
                temperature=cfg.temperature
                if cfg.temperature is not None
                else self._tuning.default_temperature,
                top_p=cfg.top_p,
                max_tokens=cfg.max_tokens,
                extra_payload=self._tuning.thinking_payload(cfg.thinking) or {},
            )
            response = self._retry.call(self._transport, request)
            usage = response.usage or usage
            try:
                parsed = self._parser.parse(response.content, response.reasoning)
            except ParseError as error:
                parse_retries += 1
                if parse_retries > cfg.self_check_retries:
                    raise AdapterFailure(
                        f"解析重试耗尽（{parse_retries - 1} 次）：{error}"
                    ) from error
                rejection = f"输出无法解析：{error}"
                continue
            thinking_text = parsed.thinking
            if _action_in_legal(parsed.action, view.legal_actions):
                latency_ms = int((time.monotonic() - started) * 1000)
                envelope = self._ledger.build_envelope(
                    provider=self._tuning.provider,
                    model=cfg.model,
                    latency_ms=latency_ms,
                    usage=usage,
                    thinking_text=thinking_text,
                    parse_retries=parse_retries - 1 if parse_retries else 0,
                    self_check_retries=self_check_retries,
                )
                quote = parsed.quote if cfg.quote.enabled else ""
                return Decision(
                    action=parsed.action,
                    quote=quote,
                    thinking=thinking_text,
                    attachments=CostLedger.as_attachment(envelope),
                )
            self_check_retries += 1
            if self_check_retries > cfg.self_check_retries:
                # 自检耗尽（B-04）：按原样提交——引擎驳回层接手（走引擎纠错预算）
                latency_ms = int((time.monotonic() - started) * 1000)
                envelope = self._ledger.build_envelope(
                    provider=self._tuning.provider,
                    model=cfg.model,
                    latency_ms=latency_ms,
                    usage=usage,
                    thinking_text=thinking_text,
                    parse_retries=parse_retries - 1 if parse_retries else 0,
                    self_check_retries=self_check_retries - 1,
                    degrade_reason="self_check_exhausted",
                )
                return Decision(
                    action=parsed.action,
                    quote=parsed.quote if cfg.quote.enabled else "",
                    thinking=thinking_text,
                    attachments=CostLedger.as_attachment(envelope),
                )
            rejection = f"动作不在合法动作集：{parsed.action}（合法集见动作块）"


def _resolve(api_key_ref: str) -> str:
    from perudo.adapters.sdk.config import resolve_api_key

    return resolve_api_key(api_key_ref)


def _default_transport(timeout_ms: int) -> Transport:
    from perudo.adapters.sdk.transport import OpenAICompatTransport

    return OpenAICompatTransport(timeout_ms)


def _action_in_legal(
    action: object, legal: tuple[BidAction | ChallengeAction | ResponseKind, ...]
) -> bool:
    from perudo.players.base import action_in_legal as _contract_check

    return _contract_check(action, legal)  # type: ignore[arg-type]
