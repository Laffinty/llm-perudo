"""Web 宿主（04 §1 / F-05）：FastAPI + WebSocket，宿主是管道不是裁判。

路由 = 05 §4.2 最小集；WS = 视图流网关（G-02 seq 补发）；静态托管 = Vite
构建产物（frontend/dist 存在时挂载，缺省给提示页）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from perudo.engine.events import Event
from perudo.host.manager import MatchManager, MatchNotFoundError

__all__ = ["create_app"]


def create_app(data_root: Path, *, dist_dir: Path | None = None) -> FastAPI:
    """构建宿主应用。``data_root`` 为 05 §3 数据根目录（matches/log/archives）。"""
    data_root.mkdir(parents=True, exist_ok=True)
    manager = MatchManager(data_root)
    app = FastAPI(title="llm-perudo 宿主", version="0.1.0")
    app.state.manager = manager

    # ---------------------------------------------------------------- REST
    @app.exception_handler(MatchNotFoundError)
    async def _not_found(_request: Any, exc: MatchNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": f"桌局不存在：{exc}"})

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/matches")
    def create_match(spec: dict[str, Any]) -> dict[str, Any]:
        try:
            handle = manager.create_match(spec)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return handle.snapshot()

    @app.get("/matches")
    def list_matches() -> list[dict[str, Any]]:
        return manager.list_matches()

    @app.get("/matches/{match_id}")
    def match_summary(match_id: str) -> dict[str, Any]:
        return manager.get(match_id).snapshot()

    @app.post("/matches/{match_id}/state")
    def match_state(match_id: str, body: dict[str, str]) -> dict[str, Any]:
        action = str(body.get("action", ""))
        try:
            return manager.transition(match_id, action)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except AssertionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/matches/{match_id}/action")
    def submit_action(match_id: str, body: dict[str, Any]) -> dict[str, Any]:
        handle = manager.get(match_id)
        if handle.human is None:
            raise HTTPException(status_code=409, detail="本桌无人类席（PVE 专用端点）")
        payload = body.get("action")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="action 必须为动作对象")
        handle.human.submit(payload)
        return {"submitted": True}

    @app.get("/matches/{match_id}/pending")
    def pending_view(match_id: str) -> dict[str, Any]:
        """人类席当前等待动作的视图快照（PVE 动作面板数据源，W2 接线）。"""
        handle = manager.get(match_id)
        if handle.human is None:
            raise HTTPException(status_code=409, detail="本桌无人类席")
        snapshot = handle.human.snapshot_pending()
        if snapshot is None:
            return {"waiting": False}
        return {"waiting": True, "view": snapshot}

    @app.get("/matches/{match_id}/files")
    def match_files(match_id: str) -> dict[str, Any]:
        handle = manager.get(match_id)
        return {
            "log_path": str(handle.log_path) if handle.log_path else None,
            "log_lines": handle.log_writer.lines if handle.log_writer else 0,
            "stream_path": str(
                Path(__file__).resolve().parent.parent.parent
                / "data"
                / "matches"
                / match_id
                / "stream.jsonl"
            ),
        }

    # ---------------------------------------------------------------- WS
    @app.websocket("/matches/{match_id}/stream")
    async def match_stream(websocket: WebSocket, match_id: str, role: str = "spectator", last_seq: int | None = None) -> None:
        await websocket.accept()
        try:
            handle, backlog, wake, unsubscribe = manager.subscribe(match_id, role, last_seq)
        except (MatchNotFoundError, ValueError) as error:
            await websocket.send_text(
                json.dumps({"seq": 0, "type": "Error", "payload": {"detail": str(error)}}, ensure_ascii=False)
            )
            await websocket.close(code=4404)
            return
        try:
            for event in backlog:
                await websocket.send_text(_envelope_json(event))
            latest_seq = handle.events[-1].seq if handle.events else 0
            await websocket.send_text(
                json.dumps({"seq": latest_seq, "type": "BacklogDone", "payload": {}}, default=str)
            )
            while True:
                await asyncio.to_thread(wake.wait, 5.0)
                for event in _drain(handle, wake):
                    await websocket.send_text(_envelope_json(event))
                    # 终局/弃局即服务端收束（A-10b 叙事完结；重连按 last_seq 取历史）
                    if event.type in ("MATCH_ENDED",) or (
                        event.type == "MATCH_STATE_CHANGED"
                        and event.payload.get("status") == "ABANDONED"
                    ):
                        await websocket.close()
                        return
        except WebSocketDisconnect:
            pass
        finally:
            unsubscribe()

    # ---------------------------------------------------------------- 静态
    if dist_dir is not None and (dist_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="spa")
    else:

        @app.get("/")
        def index() -> dict[str, str]:
            return {
                "detail": "前端构建产物缺失：请先执行 frontend 的 npm run build（产物 dist/ 由宿主托管）"
            }

    return app


def _envelope_json(event: Event) -> str:
    return json.dumps(
        {"seq": event.seq, "type": event.type, "payload": event.payload},
        ensure_ascii=False,
        default=str,
    )


def _drain(handle: Any, wake: Any) -> list[Event]:
    """取走本订阅者队列中的全部待推事件并清除唤醒旗标。"""
    drained: list[Event] = []
    for sub in list(handle.subscribers):
        if sub.wake is wake:
            while sub.queue:
                drained.append(sub.queue.pop(0))
            break
    wake.clear()
    return drained
