"""传输层与重试（03 §1.1 Transport / RetryController）。

网络层重试（指数退避 ×net_retries）完全在适配器内部，引擎不可见（03 §8）；
失败耗尽 → ``TransportError`` 上抛 → 引擎故障政策（A-15：代打 + 降级标记）。
适配器层允许三方依赖（httpx），离线测试注入 ``FakeTransport``。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

__all__ = [
    "TransportError",
    "CompletionRequest",
    "CompletionResponse",
    "Transport",
    "OpenAICompatTransport",
    "RetryController",
]


class TransportError(Exception):
    """网络/超时/5xx 等传输失败（重试耗尽后上抛）。"""


@dataclass(frozen=True)
class CompletionRequest:
    """一次补全请求（OpenAI 兼容形态；思考参数为各家已映射的 JSON 载荷）。"""

    base_url: str
    api_key: str
    model: str
    messages: list[dict[str, str]]
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int = 1024
    response_json: bool = True
    extra_payload: dict[str, Any] = field(default_factory=dict)  # 家映射的思考参数等


@dataclass
class CompletionResponse:
    """一次补全响应：正文 + 剥离出的思考文本 + 用量。"""

    content: str
    reasoning: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


class Transport(Protocol):
    """传输协议（B-03：协议可插拔；测试注入 Fake，生产用 OpenAI 兼容实现）。"""

    def complete(self, request: CompletionRequest) -> CompletionResponse: ...


class OpenAICompatTransport:
    """OpenAI 兼容 HTTP 传输（B-08：六家默认一套；httpx 同步客户端）。"""

    def __init__(self, timeout_ms: int = 30_000) -> None:
        self._timeout_ms = timeout_ms

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": request.messages,
            "max_tokens": request.max_tokens,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.response_json:
            payload["response_format"] = {"type": "json_object"}
        payload.update(request.extra_payload)
        url = request.base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {request.api_key}"}
        try:
            with httpx.Client(timeout=self._timeout_ms / 1000) as client:
                response = client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as error:
            raise TransportError(f"网络失败：{error}") from error
        if response.status_code >= 500 or response.status_code == 429:
            raise TransportError(f"服务端暂时不可用：HTTP {response.status_code}")
        if response.status_code != 200:
            # 4xx 属请求面错误（配置/参数/密钥），重试无意义——直接上抛
            raise RuntimeError(f"请求被拒绝：HTTP {response.status_code} {response.text[:300]}")
        body = response.json()
        try:
            choice = body["choices"][0]["message"]
            content = str(choice.get("content") or "")
            reasoning = choice.get("reasoning_content")
            usage_raw = dict(body.get("usage", {}))
        except (KeyError, IndexError, TypeError) as error:
            raise TransportError(f"响应形态异常：{error}") from error
        usage = {k: int(v) for k, v in usage_raw.items() if isinstance(v, int)}
        return CompletionResponse(
            content=content,
            reasoning=str(reasoning) if reasoning else None,
            usage=usage,
        )


class RetryController:
    """网络层重试（指数退避；独立于引擎纠错预算，03 §8）。"""

    def __init__(self, retries: int = 3, backoff_base: float = 0.5) -> None:
        self._retries = retries
        self._backoff_base = backoff_base

    def call(self, transport: Transport, request: CompletionRequest) -> CompletionResponse:
        last_error: TransportError | None = None
        for attempt in range(self._retries + 1):
            try:
                return transport.complete(request)
            except TransportError as error:
                last_error = error
                if attempt < self._retries:
                    time.sleep(self._backoff_base * (2**attempt))
        raise TransportError(f"网络重试耗尽（{self._retries + 1} 次）：{last_error}")


def serialize_request_payload(request: CompletionRequest) -> str:
    """调试/日志用：请求体的 JSON 文本（密钥不出现在 payload 中——只在 header）。"""
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": request.messages,
        "max_tokens": request.max_tokens,
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    payload.update(request.extra_payload)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
