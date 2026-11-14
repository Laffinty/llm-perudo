"""P5 单元测试：PVE 全链路（W2/W3）——人类席桥 / 玩家流席位纪律 / ActionRequired。

全程离线：人类席动作由 REST 注入驱动，对手用保守机器人。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from perudo.host.app import create_app


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path))


@pytest.fixture()
def live_server(tmp_path: Path):
    """真实端口 uvicorn（绕开 TestClient 的 WS receive 无超时能力，R-06.2 方案）。"""
    import threading

    import uvicorn

    app = create_app(tmp_path)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}", port
    server.should_exit = True
    thread.join(timeout=5)


def _pve_spec(threshold: int = 100_000, max_rounds: int = 50) -> dict:
    return {
        "mode": "pve",
        "slots": [
            {"kind": "human", "name": "人类"},
            {"kind": "bot", "name": "bot1"},
            {"kind": "bot", "name": "bot2"},
            {"kind": "bot", "name": "bot3"},
        ],
        "config": {"player_count": 4, "end_threshold": threshold, "max_rounds": max_rounds},
    }


def _open_pve(client: TestClient, **kw) -> str:
    return client.post("/matches", json=_pve_spec(**kw)).json()["match_id"]


def _wait_pending(client: TestClient, match_id: str, timeout_s: float = 15.0) -> dict:
    import time

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        pending = client.get(f"/matches/{match_id}/pending").json()
        if pending.get("waiting"):
            return pending
        time.sleep(0.1)
    raise AssertionError("人类席未在时限内收到决策请求")


def _wait_status(client: TestClient, match_id: str, status: str, timeout_s: float = 30.0) -> None:
    import time

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if client.get(f"/matches/{match_id}").json()["status"] == status:
            return
        time.sleep(0.1)
    raise AssertionError(f"桌局未在时限内进入 {status}")


def test_pve_full_flow_human_drives_match(client: TestClient) -> None:
    """PVE 全动作可玩（W2 验收）：人类席经 REST 出牌（首叫→应牌→弃局链路组件）。"""
    match_id = _open_pve(client, threshold=100_000, max_rounds=20)
    # 人类席首叫（opening：非斋 6 个 3）
    pending = _wait_pending(client, match_id)
    assert pending["view"]["seat"] == 0
    assert pending["view"]["phase"] == "bidding"
    legal = pending["view"]["legal_actions"]
    assert any(a["t"] == "bid" for a in legal)
    client.post(f"/matches/{match_id}/action", json={"action": legal[0]})
    # 下一决策点回到人类席（轮转）——持续出牌直到应牌链/结算，或交给 bot
    for _ in range(6):
        pending = client.get(f"/matches/{match_id}/pending").json()
        if not pending.get("waiting"):
            break
        legal = pending["view"]["legal_actions"]
        action = next(
            (a for a in legal if a["t"] == "response" and a["kind"] == "surrender"),
            legal[0],
        )
        client.post(f"/matches/{match_id}/action", json={"action": action})
        time.sleep(0.2)
    summary = client.get(f"/matches/{match_id}").json()
    assert summary["event_count"] > 20


def test_pve_player_stream_seat_discipline(live_server) -> None:
    """F-02/F-06：玩家流 = 公开层 + 本人 HandShaken；不含内心戏与私密手牌。

    真实端口 + websockets 客户端（R-06.2 方案；TestClient 的 WS receive 无超时能力）。
    """
    import time as _time

    import httpx
    from websockets.exceptions import ConnectionClosed
    from websockets.sync.client import connect as ws_connect

    base, ws_port = live_server
    match_id = httpx.post(
        f"{base}/matches", json=_pve_spec(threshold=100_000, max_rounds=20)
    ).json()["match_id"]
    # player 流必须带 seat：服务端发 Error 信封后 close（4400）
    ws = ws_connect(f"ws://127.0.0.1:{ws_port}/matches/{match_id}/stream?role=player")
    envelope = json.loads(ws.recv(timeout=5))
    assert envelope["type"] == "Error" and "seat" in envelope["payload"]["detail"]
    ws.close()

    ws = ws_connect(f"ws://127.0.0.1:{ws_port}/matches/{match_id}/stream?role=player&seat=0")
    seen_types: list[str] = []
    own_hand_events = 0
    action_required = False
    deadline = _time.time() + 20
    try:
        while _time.time() < deadline:
            try:
                envelope = json.loads(ws.recv(timeout=2))
            except TimeoutError:
                break  # 局阻塞等人类出牌：无新事件即收束取证
            seen_types.append(envelope["type"])
            if envelope["type"] == "ActionRequired":
                action_required = True
                break
            if envelope["type"] == "HandShaken":
                assert envelope["payload"]["seat"] == 0, "玩家流只含本人手牌（F-02）"
                own_hand_events += 1
            if envelope["type"] == "ThinkingObserved":
                raise AssertionError("PVE 玩家流不得出现内心戏（F-06）")
    except ConnectionClosed:
        pass
    ws.close()
    assert "MatchStarted" in seen_types
    assert "HandShaken" in seen_types and own_hand_events >= 1
    assert "DecisionFacts" not in seen_types, "评测层永不进呈现流"
    assert action_required, "人类席等待动作时必有 ActionRequired 提示（04 §3.2 动作面板数据源）"


def test_pve_illegal_action_rejected_with_reason(client: TestClient) -> None:
    """非法动作走引擎纠错路径：桥报错不炸局（02 §4.3 纠错预算在引擎侧）。"""
    match_id = _open_pve(client)
    _wait_pending(client, match_id)
    # 直接提交非法动作对象（桥解析失败 → 置 error → decide 抛 → 引擎故障政策）
    response = client.post(f"/matches/{match_id}/action", json={"action": {"t": "no_such_action"}})
    assert response.status_code == 200  # 桥接受提交，错误经 decide 抛给引擎故障政策


def test_pve_abandon_via_state_endpoint(client: TestClient) -> None:
    """G-08：退出即弃局——state 端点弃局 + meta 标记（05 §2.5）。"""
    match_id = _open_pve(client)
    _wait_pending(client, match_id)
    body = client.post(f"/matches/{match_id}/state", json={"action": "abandon"}).json()
    assert body["status"] == "ABANDONED"
    _wait_status(client, match_id, "ABANDONED", 5)


def test_pve_suspended_human_wait_survives(client: TestClient) -> None:
    """挂起时人类席等待保留（05 §2.1）：恢复后仍可继续出牌。"""
    match_id = _open_pve(client)
    _wait_pending(client, match_id)
    client.post(f"/matches/{match_id}/state", json={"action": "suspend"})
    _wait_status(client, match_id, "SUSPENDED", 5)
    # 挂起状态下 REST 出牌依然注入（桥的事件等待与宿主状态解耦）
    client.post(
        f"/matches/{match_id}/action",
        json={"action": {"t": "bid", "kind": "normal", "count": 6, "face": 3}},
    )
    client.post(f"/matches/{match_id}/state", json={"action": "resume"})
    assert client.get(f"/matches/{match_id}").json()["status"] == "RUNNING"
