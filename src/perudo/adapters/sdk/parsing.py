"""响应解析（03 §1.1 ResponseParser）：LLM 输出 → 动作 / 台词 / 思考文本。

剥离纪律（03 §5.6 / 02 §4.2）：思考文本**绝不**混入台词或动作字段——
剥离结果只进评测附件与 Decision.thinking。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from perudo.core.types import BidAction, ChallengeAction, ResponseKind
from perudo.engine.events import action_from_payload

__all__ = ["ParseError", "ParsedOutput", "ResponseParser", "strip_think_blocks"]

_THINK_BLOCK = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)


class ParseError(Exception):
    """输出无法解析为动作 JSON（带人类可读原因，供内部重试回喂）。"""


@dataclass
class ParsedOutput:
    """一次成功解析的结果。"""

    action: BidAction | ChallengeAction | ResponseKind
    quote: str
    thinking: str | None


def strip_think_blocks(text: str) -> tuple[str, str | None]:
    """剥离正文中的交错思考块（MiniMax M 系形态，03 §5.6）。

    返回 ``(正文, 思考文本)``；无思考块时思考文本为 ``None``。
    """
    blocks = _THINK_BLOCK.findall(text)
    if not blocks:
        return text, None
    cleaned = _THINK_BLOCK.sub("", text).strip()
    return cleaned, "\n".join(blocks).strip() or None


class ResponseParser:
    """正文 → 决策；JSON 提取宽容（容忍前后缀文本），字段缺失即 ParseError。"""

    def parse(
        self,
        content: str,
        reasoning: str | None = None,
        *,
        expect_response_kind: bool = False,
    ) -> ParsedOutput:
        """解析一次模型输出。

        ``expect_response_kind``：应牌阶段允许动作对象直接给 kind 字符串
        （部分模型会把 {t:response,...} 简写成 "surrender"）。
        """
        body, inline_thinking = strip_think_blocks(content)
        payload = self._extract_json_object(body)
        if "action" not in payload:
            raise ParseError("缺少 action 字段")
        action_payload = payload["action"]
        if expect_response_kind and isinstance(action_payload, str):
            action_payload = {"t": "response", "kind": str(action_payload)}
        if not isinstance(action_payload, dict):
            raise ParseError("action 字段不是对象")
        try:
            action = action_from_payload(dict(action_payload))
        except (KeyError, ValueError, TypeError) as error:
            raise ParseError(f"动作对象非法：{error}") from error
        quote = payload.get("quote", "")
        if not isinstance(quote, str):
            raise ParseError("quote 字段必须是字符串")
        thinking = (reasoning or inline_thinking) or None
        return ParsedOutput(action=action, quote=quote.strip(), thinking=thinking)

    def _extract_json_object(self, text: str) -> dict[str, object]:
        """从文本中提取第一个完整 JSON 对象（括号配对扫描，容忍前后缀）。"""
        start = text.find("{")
        if start == -1:
            raise ParseError("输出中未找到 JSON 对象")
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : index + 1]
                    try:
                        loaded = json.loads(candidate)
                    except json.JSONDecodeError as error:
                        raise ParseError(f"JSON 解析失败：{error}") from error
                    if not isinstance(loaded, dict):
                        raise ParseError("JSON 顶层不是对象")
                    return loaded
        raise ParseError("JSON 对象未闭合")
