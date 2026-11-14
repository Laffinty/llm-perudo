"""Anthropic Messages 协议 Transport（MiMo 双协议第二实现，03 §5.2）。

仅 MiMo 存在此实现（B-08）：官方兼容端点
``https://api.xiaomimimo.com/anthropic/v1/messages``（03 §5.7.1 核对）。

与 OpenAI 兼容层的差异：system 为**顶层字段**（不在 messages 里——稳定前缀
装配规范因此天然满足前缀缓存）；``max_tokens`` 为必填；思考参数经
``thinking`` 顶层结构传递。
"""

from __future__ import annotations

from typing import Any

import httpx

from perudo.adapters.sdk.transport import (
    CompletionRequest,
    CompletionResponse,
    TransportError,
)

__all__ = ["build_anthropic_payload", "AnthropicMessagesTransport"]

_ANTHROPIC_VERSION = "2023-06-01"


def build_anthropic_payload(request: CompletionRequest) -> dict[str, Any]:
    """CompletionRequest → Anthropic Messages 载荷（纯函数，离线可测）。

    稳定前缀装配：messages 中 role=system 的内容提升为顶层 ``system``
    （Anthropic 无 system 角色消息），其余 user/assistant 保持顺序。
    """
    system_parts = [m["content"] for m in request.messages if m["role"] == "system"]
    dialogue = [m for m in request.messages if m["role"] != "system"]
    payload: dict[str, Any] = {
        "model": request.model,
        "max_tokens": request.max_tokens,
        "messages": [{"role": m["role"], "content": m["content"]} for m in dialogue],
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.top_p is not None:
        payload["top_p"] = request.top_p
    payload.update(request.extra_payload)
    return payload


class AnthropicMessagesTransport:
    """Anthropic Messages 协议传输（MiMo 双协议第二实现，03 §5.2 / B-08）。"""

    def __init__(self, timeout_ms: int = 30_000) -> None:
        self._timeout_ms = timeout_ms

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        anthropic_base = request.base_url.rstrip("/")
        if not anthropic_base.endswith("/anthropic"):
            anthropic_base += "/anthropic"
        url = anthropic_base + "/v1/messages"
        payload = build_anthropic_payload(request)
        headers = {
            "x-api-key": request.api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
        }
        try:
            with httpx.Client(timeout=self._timeout_ms / 1000) as client:
                response = client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as error:
            raise TransportError(f"网络失败：{error}") from error
        if response.status_code >= 500 or response.status_code == 429:
            raise TransportError(f"服务端暂时不可用：HTTP {response.status_code}")
        if response.status_code != 200:
            raise RuntimeError(f"请求被拒绝：HTTP {response.status_code} {response.text[:300]}")
        body = response.json()
        try:
            content = str(body["content"][0]["text"])
            usage_raw = dict(body.get("usage", {}))
        except (KeyError, IndexError, TypeError) as error:
            raise TransportError(f"响应形态异常：{error}") from error
        return CompletionResponse(
            content=content,
            reasoning=body.get("reasoning_content"),
            usage={k: int(v) for k, v in usage_raw.items() if isinstance(v, int)},
        )
