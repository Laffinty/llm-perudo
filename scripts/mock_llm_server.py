"""开发验证用 mock OpenAI 兼容服务器（W1 内心戏/气泡浏览器验证）。

从请求的 user 消息中抓取动作块（enumerate 呈现）回第一个合法动作，
并附 thinking 正文——驱动引擎的 ThinkingObserved 观战投影。
非生产代码：仅供浏览器全链路验收（scripts/ 属开发辅助，计划 §2.2）。
用法：uv run python scripts/mock_llm_server.py 8901
"""

from __future__ import annotations

import json
import re
import sys

from fastapi import FastAPI, Request

app = FastAPI()
_ACTION = re.compile(r'\{"t":"(?:bid|challenge|response)"[^}]*\}')


@app.post("/chat/completions")
async def completions(request: Request) -> dict:
    body = await request.json()
    user_text = next((m["content"] for m in reversed(body["messages"]) if m["role"] == "user"), "")
    payloads = _ACTION.findall(user_text)
    thinking = "（mock 思考）我看了局面，从合法集里取第一个动作。"
    if payloads:
        action = json.loads(payloads[0])
    else:
        action = {"t": "bid", "kind": "normal", "count": 6, "face": 3}
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {"action": action, "quote": "mock 台词：看我的"}, ensure_ascii=False
                    ),
                    "reasoning_content": thinking,
                }
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 40},
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(sys.argv[1]) if len(sys.argv) > 1 else 8901,
        log_level="warning",
    )
