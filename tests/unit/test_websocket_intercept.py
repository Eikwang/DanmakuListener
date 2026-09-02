"""Task-10: WebSocket 弹幕拦截与分发 测试

验证 DanmakuAddon 的 websocket_start 和 websocket_message 钩子：
- websocket_start: 匹配弹幕域名 → callback, 不匹配 → 不 callback
- websocket_message: from_client=True → 忽略, 解码成功 → 分发, 解码失败 → 不崩溃
- 重复 msgId → 去重 (DedupFilter)
- 未知 method → 不分发
- room_id 从 URL 提取
"""

import gzip
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from danmaku_listener.adapters.protocols.proto.wss_pb2 import WssResponse
from danmaku_listener.adapters.protocols.proto.message_pb2 import (
    Response, Message, ChatMessage, GiftMessage, User,
)


def _make_mock_settings(**overrides):
    """构造 mock Settings"""
    defaults = {
        "used_proxy": True,
        "cert_dir": "~/.mitmproxy",
        "process_filter": "chrome,msedge",
        "force_polling": False,
        "auto_pause": False,
        "ssl_decrypt_hostnames": "",
        "process_filter_list": ["chrome", "msedge"],
        "ssl_decrypt_extra_hostnames": [],
        "dedup_window_size": 300,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def _make_ws_flow(
    host="webcast3-ws-web-1.douyin.com",
    url=None,
    client_port=12345,
    ws_messages=None,
):
    """构造 mock WebSocket HTTPFlow"""
    flow = MagicMock()
    flow.request = MagicMock()
    flow.request.host = host
    flow.request.pretty_url = url or f"wss://{host}/webcast/im/push/v2/?room_id=999888"
    flow.request.url = url or f"wss://{host}/webcast/im/push/v2/?room_id=999888"

    flow.client_conn = MagicMock()
    flow.client_conn.peername = ("127.0.0.1", client_port)

    flow.id = "test-flow-id-123"

    if ws_messages is not None:
        flow.websocket = MagicMock()
        flow.websocket.messages = ws_messages
    else:
        flow.websocket = MagicMock()
        flow.websocket.messages = []

    return flow


def _build_wss_response_with_chat(content: str = "你好", nickname: str = "用户", msg_id: int = 123) -> bytes:
    """构造包含 ChatMessage 的完整 WssResponse 序列化字节"""
    chat = ChatMessage(content=content)
    chat.user.nickname = nickname

    msg = Message(method="WebcastChatMessage", msgId=msg_id)
    msg.payload = chat.SerializeToString()

    response = Response()
    response.messages.append(msg)
    response_bytes = response.SerializeToString()

    wss = WssResponse(seqid=1, logid=1, service=1, method=1)
    wss.payload = response_bytes
    return wss.SerializeToString()


def _build_wss_response_with_chat_gzipped(content: str = "hello gzip", nickname: str = "user", msg_id: int = 999) -> bytes:
    """构造 Gzip 压缩的 WssResponse"""
    chat = ChatMessage(content=content)
    chat.user.nickname = nickname

    msg = Message(method="WebcastChatMessage", msgId=msg_id)
    msg.payload = chat.SerializeToString()

    response = Response()
    response.messages.append(msg)
    response_bytes = response.SerializeToString()
    compressed = gzip.compress(response_bytes)

    wss = WssResponse(seqid=1, logid=1, service=1, method=1)
    wss.headers["compress_type"] = "gzip"
    wss.payload = compressed
    return wss.SerializeToString()


def _build_wss_response_unknown_method(msg_id: int = 555) -> bytes:
    """构造包含未知 method 的 WssResponse"""
    msg = Message(method="WebcastUnknownMessage", msgId=msg_id)
    msg.payload = b""

    response = Response()
    response.messages.append(msg)

    wss = WssResponse(seqid=1, logid=1, service=1, method=1)
    wss.payload = response.SerializeToString()
    return wss.SerializeToString()


class TestWebSocketStart:
    """websocket_start 钩子测试 → AC-003"""

    @pytest.mark.asyncio
    async def test_websocket_start_matching_host_calls_callback(self):
        """host 匹配弹幕域名 → 调用 _message_callback → AC-003"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        flow = _make_ws_flow(host="webcast3-ws-web-1.douyin.com")
        addon.websocket_start(flow)

        # callback 应被调用
        cb.assert_called_once()
        call_args = cb.call_args[0][0]
        assert call_args["type"] == "ws_connected"
        assert call_args["room_id"] == "999888"

    @pytest.mark.asyncio
    async def test_websocket_start_amemv_host_calls_callback(self):
        """webcast amemv 域名也匹配"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        flow = _make_ws_flow(host="webcast5-ws-web-abc.amemv.com")
        addon.websocket_start(flow)

        cb.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_start_non_matching_host_no_callback(self):
        """host 不匹配弹幕域名 → 不调用 callback"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        flow = _make_ws_flow(host="www.baidu.com")
        addon.websocket_start(flow)

        cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_websocket_start_tracks_flow(self):
        """websocket_start 记录活跃 flow → room_id 映射"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        flow = _make_ws_flow(host="webcast3-ws-web-1.douyin.com")
        addon.websocket_start(flow)

        assert flow.id in addon._active_ws_flows
        assert addon._active_ws_flows[flow.id] == "999888"

    @pytest.mark.asyncio
    async def test_websocket_start_no_room_id_in_url(self):
        """URL 中无 room_id 参数 → room_id 为空字符串"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        flow = _make_ws_flow(
            host="webcast3-ws-web-1.douyin.com",
            url="wss://webcast3-ws-web-1.douyin.com/webcast/im/push/v2/",
        )
        addon.websocket_start(flow)

        cb.assert_called_once()
        call_args = cb.call_args[0][0]
        assert call_args["room_id"] == ""


class TestWebSocketMessage:
    """websocket_message 钩子测试 → AC-004, AC-010, AC-011, AC-018, AC-019"""

    @pytest.mark.asyncio
    async def test_websocket_message_from_client_ignored(self):
        """from_client=True → 忽略，不调用 callback"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        msg = MagicMock()
        msg.from_client = True
        msg.content = b"test"

        flow = _make_ws_flow(ws_messages=[msg])
        addon.websocket_message(flow)

        cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_websocket_message_server_message_decoded(self):
        """from_client=False + 解码成功 → 调用 callback → AC-004"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        raw_bytes = _build_wss_response_with_chat("你好", "用户", 123)
        msg = MagicMock()
        msg.from_client = False
        msg.content = raw_bytes

        # 将 flow 标记为弹幕流
        flow = _make_ws_flow(ws_messages=[msg])
        addon._active_ws_flows[flow.id] = "999888"

        addon.websocket_message(flow)

        cb.assert_called()
        call_args = cb.call_args[0][0]
        assert call_args["type"] == "danmaku"
        assert call_args["room_id"] == "999888"

    @pytest.mark.asyncio
    async def test_websocket_message_gzip_decoded(self):
        """Gzip 压缩的弹幕消息也能正确解码"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        raw_bytes = _build_wss_response_with_chat_gzipped("hello gzip", "user", 999)
        msg = MagicMock()
        msg.from_client = False
        msg.content = raw_bytes

        flow = _make_ws_flow(ws_messages=[msg])
        addon._active_ws_flows[flow.id] = "999888"

        addon.websocket_message(flow)

        cb.assert_called()

    @pytest.mark.asyncio
    async def test_websocket_message_invalid_bytes_no_crash(self):
        """无效 bytes → 不崩溃 → AC-010"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        msg = MagicMock()
        msg.from_client = False
        msg.content = b"this is not protobuf"

        flow = _make_ws_flow(ws_messages=[msg])
        addon._active_ws_flows[flow.id] = "999888"

        # 不应崩溃
        addon.websocket_message(flow)
        # 不应调用 callback（解码失败）
        cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_websocket_message_unknown_method_not_dispatched(self):
        """未知 method → 不分发 → AC-018"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        raw_bytes = _build_wss_response_unknown_method(555)
        msg = MagicMock()
        msg.from_client = False
        msg.content = raw_bytes

        flow = _make_ws_flow(ws_messages=[msg])
        addon._active_ws_flows[flow.id] = "999888"

        addon.websocket_message(flow)
        # 未知 method 不分发（但可能有 ws_connected 之前的调用，需排除）
        danmaku_calls = [c for c in cb.call_args_list if c[0][0].get("type") == "danmaku"]
        assert len(danmaku_calls) == 0

    @pytest.mark.asyncio
    async def test_websocket_message_dedup(self):
        """相同 msg_id 的消息只分发一次 → AC-019"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        raw_bytes = _build_wss_response_with_chat("你好", "用户", 123)

        # 第一条消息
        msg1 = MagicMock()
        msg1.from_client = False
        msg1.content = raw_bytes

        flow = _make_ws_flow(ws_messages=[msg1])
        addon._active_ws_flows[flow.id] = "999888"
        addon.websocket_message(flow)

        # 第二条相同内容（模拟重复推送）
        msg2 = MagicMock()
        msg2.from_client = False
        msg2.content = raw_bytes

        flow2 = _make_ws_flow(ws_messages=[msg2])
        addon._active_ws_flows[flow2.id] = "999888"
        addon.websocket_message(flow2)

        # 只应分发一次（去重）
        danmaku_calls = [c for c in cb.call_args_list if c[0][0].get("type") == "danmaku"]
        assert len(danmaku_calls) == 1

    @pytest.mark.asyncio
    async def test_websocket_message_non_webcast_flow_ignored(self):
        """非弹幕流 WebSocket 消息 → 忽略"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        raw_bytes = _build_wss_response_with_chat("你好", "用户", 123)
        msg = MagicMock()
        msg.from_client = False
        msg.content = raw_bytes

        # flow 不在 _active_ws_flows 中（非弹幕流）
        flow = _make_ws_flow(host="www.baidu.com", ws_messages=[msg])
        # 不添加到 _active_ws_flows

        addon.websocket_message(flow)
        cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_websocket_message_room_id_from_active_flows(self):
        """room_id 从 _active_ws_flows 获取（而非重新解析 URL）"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        raw_bytes = _build_wss_response_with_chat("你好", "用户", 123)
        msg = MagicMock()
        msg.from_client = False
        msg.content = raw_bytes

        flow = _make_ws_flow(ws_messages=[msg])
        # 手动设置 room_id
        addon._active_ws_flows[flow.id] = "777666"

        addon.websocket_message(flow)

        cb.assert_called()
        call_args = cb.call_args[0][0]
        assert call_args["room_id"] == "777666"
