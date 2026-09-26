"""PushServer 集成测试：token 鉴权 + 广播（契约 v1 通道）"""

import asyncio
import json

import pytest

from danmaku_listener.push.ws_server import PushServer, constant_time_equal, load_token


def test_constant_time_equal():
    assert constant_time_equal("abc", "abc")
    assert not constant_time_equal("abc", "abd")
    assert not constant_time_equal("", "x")


def test_load_token_priority(tmp_path, monkeypatch):
    f = tmp_path / "token.txt"
    f.write_text("file-token", encoding="utf-8")
    monkeypatch.setenv("DANMAKU_TOKEN", "env-token")
    assert load_token(str(f), "env-token") == "env-token"  # 环境变量优先
    monkeypatch.delenv("DANMAKU_TOKEN")
    assert load_token(str(f), None) == "file-token"
    assert load_token(None, None) is None


@pytest.mark.asyncio
async def test_push_server_broadcast_and_auth():
    server = PushServer(host="127.0.0.1", port=18766, token="secret-token")
    await server.start()
    import websockets

    try:
        # 1) 无 token → 拒绝
        with pytest.raises(Exception):
            async with websockets.connect("ws://127.0.0.1:18766/ws") as ws:
                await ws.recv()
        # 2) 错误 token → 拒绝
        with pytest.raises(Exception):
            async with websockets.connect(
                "ws://127.0.0.1:18766/ws",
                additional_headers={"Authorization": "Bearer wrong"},
            ) as ws:
                await ws.recv()
        # 3) 正确 token → 收到广播
        async with websockets.connect(
            "ws://127.0.0.1:18766/ws",
            additional_headers={"Authorization": "Bearer secret-token"},
        ) as ws:
            await server.broadcast({"type": "DANMU", "seq": 1})
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert msg == {"type": "DANMU", "seq": 1}
    finally:
        await server.stop()

