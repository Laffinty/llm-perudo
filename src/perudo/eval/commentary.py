"""AI 赛后评述（05 §6.4）：LLM 生成结构化评述——三禁由输入面结构保证。

三禁（02 §8.1）：不参与对局内任何判定；不覆写任何统计数字；只读公开层 +
已算指标。实现口径：输入 = 公开层文本渲染（无评测层数据、无私密层）+ 已算
指标 JSON → 提示词模板 → 任意 Transport（真实调用持键，离线注入 mock）→
产出强制前缀「【AI 评述】」标注。评述引用的数字与指标层完全同源（渲染
self-contained 指标表），无第二条数字通道。
"""

from __future__ import annotations

import json

from perudo.adapters.sdk.transport import (
    CompletionRequest,
    Transport,
)

__all__ = ["Commentator"]

_SYSTEM_PROMPT = (
    "你是大话骰桌局的赛后评述员。输入是公开层事件流摘要与已算指标表。"
    "请给出：①各玩家牌风画像；②关键局 Top-3 点评（引用局号）；③行为面定性。"
    "禁止改写任何统计数字；禁止参与对局判定；你只是赛后总结者（三禁，02 §8.1）。"
    "输出为纯文本评述，不要输出 JSON。"
)


class Commentator:
    """AI 赛后评述器：只读公开层 + 已算指标 → 评述文本（产出强制标注）。"""

    def __init__(
        self,
        transport: Transport,
        *,
        provider: str = "glm",
        model: str = "glm-5.3-flash",
        api_key: str = "mock",
        base_url: str = "https://open.bigmodel.cn/api/paas/v4",
    ) -> None:
        self._transport = transport
        self._provider = provider
        self._model = model
        self._api_key = api_key
        self._base_url = base_url

    def comment(
        self,
        *,
        match_id: str,
        public_summary: str,
        metrics: dict[str, object],
        max_tokens: int = 2048,
    ) -> str:
        """生成评述。``public_summary`` = 公开层文本渲染（由宿主/调用方提供）；
        ``metrics`` = 指标层已算表（self-contained，评述不触其它数字源）。"""
        metrics_json = json.dumps(metrics, ensure_ascii=False, indent=2)
        user = (
            f"【公开层事件流摘要】\n{public_summary}\n\n"
            f"【已算指标表（程序产出，引用时不得改写）】\n{metrics_json}\n\n"
            "请基于以上信息生成赛后评述。"
        )
        response = self._transport.complete(
            CompletionRequest(
                base_url=self._base_url,
                api_key=self._api_key,
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
            )
        )
        return "【AI 评述】\n" + response.content.strip()
