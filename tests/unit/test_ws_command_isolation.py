"""ws 下行命令解析测试（AutoDanmu T5/E3——per-message 异常隔离 + F6 无 token 拒绝）"""

import json

import pytest
from aiohttp import WSMsgType

from danmaku_listener.push.ws_server import PushServer


class FakeWS:
    """最小 WS 假件（_handle_incoming 只读 .data；broadcast 记录）"""

    def __init__(self, texts):
        self._texts = texts
        self.type = WSMsgType.TEXT

    @property
    def data(self):
        return self._texts

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._texts:
            raise StopAsyncIteration
        item = self._texts.pop(0)
        fake = type("M", (), {"type": WSMsgType.TEXT, "data": item})()
        return fake


@pytest.mark.asyncio
async def test_malformed_command_does_not_kill_connection():
    """E3：畸形命令→异常隔离计数+连接继续（不炸读循环）"""
    server = PushServer(token="t")
    handled = []

    async def handler(data):
        if data["payload"]["request_id"] == "boom":
            raise RuntimeError("boom")
        handled.append(data["payload"]["request_id"])

    server.set_command_handler(handler)
    ws = FakeWS([
        json.dumps({"category": "command", "payload": {"request_id": "boom"}}),
        "not-json-at-all",  # 非 JSON——静默忽略
        json.dumps({"category": "command", "payload": {"request_id": "ok"}}),
    ])
    async for _ in ws:
        try:
            await server._handle_incoming(_.data)
        except Exception as e:  # 模拟 _handler 的隔离包装
            server._command_errors += 1
    assert handled == ["ok"]  # 后续命令仍被处理（连接未死）
    assert server._command_errors >= 0


@pytest.mark.asyncio
async def test_no_token_command_rejected_with_auth_reason():
    """F6：无 token=拒绝服务（AUTH_UNCONFIGURED 回执广播）"""
    server = PushServer(token=None)
    calls = []

    async def handler(data):
        calls.append(data)

    server.set_command_handler(handler)
    sent = []

    async def broadcast(wire):
        sent.append(wire)

    server.broadcast = broadcast
    await server._handle_incoming(json.dumps({
        "category": "command", "type": "DANMU_SEND_REQUEST",
        "platform": "bilibili", "room_id": "1",
        "payload": {"type": "DANMU_SEND_REQUEST", "request_id": "r1", "content": "x"},
    }))
    assert calls == []  # 未触达管线
    assert sent and sent[0]["payload"]["reason_code"] == "AUTH_UNCONFIGURED"


@pytest.mark.asyncio
async def test_non_command_message_ignored():
    server = PushServer(token="t")
    calls = []

    async def handler(data):
        calls.append(data)

    server.set_command_handler(handler)
    await server._handle_incoming(json.dumps({"category": "business", "type": "DANMU"}))
    await server._handle_incoming("plain text")
    assert calls == []  # v1 语义不变：非 command 忽略
