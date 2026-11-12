"""成本台账与评测附件信封（03 §4）：适配器 → 引擎"不透明附件"的统一落地。

引擎原样存档不解析（02 §4.1 / A-06）；thinking_text 的呈现纪律由 04 定义
（仅 EVE 观战实时直出，PVE 实时面不提供，复盘档全量留存——F-06/F-10）。
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["CostLedger"]


class CostLedger:
    """构建评测附件信封（03 §4 字段定稿）；token 预算累计（B-07，默认关）。"""

    def __init__(self, match_token_budget: int | None = None) -> None:
        self._budget = match_token_budget
        self._spent = 0

    @property
    def spent_tokens(self) -> int:
        return self._spent

    @property
    def budget_exceeded(self) -> bool:
        return self._budget is not None and self._spent >= self._budget

    def build_envelope(
        self,
        *,
        provider: str,
        model: str,
        latency_ms: int,
        usage: dict[str, int],
        thinking_text: str | None,
        parse_retries: int,
        self_check_retries: int,
        degrade_reason: str | None = None,
    ) -> dict[str, Any]:
        """03 §4 信封定稿：provider/model/latency/usage/thinking/重试计数/降级原因。"""
        self._spent += sum(usage.values())
        return {
            "provider": provider,
            "model": model,
            "latency_ms": latency_ms,
            "usage": dict(usage),
            "thinking_text": thinking_text,
            "parse_retries": parse_retries,
            "self_check_retries": self_check_retries,
            "degrade_reason": degrade_reason,
        }

    @staticmethod
    def as_attachment(envelope: dict[str, Any]) -> dict[str, str]:
        """信封 → 引擎 Decision.attachments 形态（Mapping[str, str]，原样存档）。

        信封整体 JSON 序列化为单键——引擎不解析（02 §4.1），评测工具从
        stream.jsonl 评测层原样取回（05 §6）。
        """
        return {"adapter_envelope": json.dumps(envelope, ensure_ascii=False, sort_keys=True)}
