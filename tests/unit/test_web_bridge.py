"""Task-02: DanmakuBridge 骨架 测试

验证 DanmakuBridge 可实例化、WS 客户端管理、广播功能、房间状态跟踪。
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from danmaku_listener.web.bridge import DanmakuBridge

@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    """rooms.json 为 cwd 相对路径（R3 持久化）——chdir 隔离，
    防止本机真实注册表（用户正在监听的房间）污染测试"""
    monkeypatch.chdir(tmp_path)
    for mod_path in ("danmaku_listener.engines.bilibili_login",
                     "danmaku_listener.engines.kuaishou_login",
                     "danmaku_listener.engines.douyin_login"):
        monkeypatch.setattr(f"{mod_path}.has_login_cookie", lambda p: True)


class TestDanmakuBridgeInitialization:
    """验证 DanmakuBridge 初始化"""

    def test_bridge_instantiable(self):
        """DanmakuBridge() 可实例化"""
        bridge = DanmakuBridge()
        assert isinstance(bridge, DanmakuBridge)

    def test_listener_is_danmaku_listener(self):
        """listener property 返回 DanmakuListener 实例"""
        bridge = DanmakuBridge()
        from danmaku_listener import DanmakuListener
        assert isinstance(bridge.listener, DanmakuListener)

    def test_rooms_empty_dict_initially(self):
        """_rooms 初始为空字典"""
        bridge = DanmakuBridge()
        assert bridge._rooms == {}

    def test_ws_clients_empty_set_initially(self):
        """_ws_clients 初始为空集合"""
        bridge = DanmakuBridge()
        assert bridge._ws_clients == set()
        assert len(bridge._ws_clients) == 0


class TestWebSocketClientManagement:
    """验证 WebSocket 客户端管理"""

    @pytest.mark.asyncio
    async def test_add_ws_client(self):
        """add_ws_client 后客户端在集合中"""
        bridge = DanmakuBridge()
        mock_ws = MagicMock()
        await bridge.add_ws_client(mock_ws)
        assert mock_ws in bridge._ws_clients

    @pytest.mark.asyncio
    async def test_remove_ws_client(self):
        """remove_ws_client 后客户端不在集合中"""
        bridge = DanmakuBridge()
        mock_ws = MagicMock()
        await bridge.add_ws_client(mock_ws)
        await bridge.remove_ws_client(mock_ws)
        assert mock_ws not in bridge._ws_clients

    @pytest.mark.asyncio
    async def test_remove_nonexistent_ws_client_no_error(self):
        """移除不存在的客户端不报错"""
        bridge = DanmakuBridge()
        mock_ws = MagicMock()
        # 未添加直接移除，不应抛异常
        await bridge.remove_ws_client(mock_ws)
        assert mock_ws not in bridge._ws_clients


class TestBroadcast:
    """验证广播功能"""

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all_clients(self):
        """_broadcast 向所有客户端发送消息"""
        bridge = DanmakuBridge()
        ws1 = MagicMock()
        ws1.send_str = AsyncMock()
        ws2 = MagicMock()
        ws2.send_str = AsyncMock()
        await bridge.add_ws_client(ws1)
        await bridge.add_ws_client(ws2)

        await bridge._broadcast({"type": "test"})

        expected_msg = json.dumps({"type": "test"}, ensure_ascii=False)
        ws1.send_str.assert_called_once_with(expected_msg)
        ws2.send_str.assert_called_once_with(expected_msg)

    @pytest.mark.asyncio
    async def test_broadcast_empty_clients_no_error(self):
        """_broadcast 无客户端时不报错"""
        bridge = DanmakuBridge()
        # 无客户端，不应抛异常
        await bridge._broadcast({"type": "test"})

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_client(self):
        """发送失败的客户端被移除，不阻塞其他客户端"""
        bridge = DanmakuBridge()
        # ws1 发送会抛异常
        ws1 = MagicMock()
        ws1.send_str = AsyncMock(side_effect=Exception("connection closed"))
        # ws2 正常
        ws2 = MagicMock()
        ws2.send_str = AsyncMock()
        await bridge.add_ws_client(ws1)
        await bridge.add_ws_client(ws2)

        await bridge._broadcast({"type": "test"})

        # ws1 应被移除
        assert ws1 not in bridge._ws_clients
        # ws2 仍应收到消息
        expected_msg = json.dumps({"type": "test"}, ensure_ascii=False)
        ws2.send_str.assert_called_once_with(expected_msg)

    @pytest.mark.asyncio
    async def test_broadcast_removes_multiple_dead_clients(self):
        """多个发送失败的客户端都被移除"""
        bridge = DanmakuBridge()
        ws1 = MagicMock()
        ws1.send_str = AsyncMock(side_effect=Exception("error1"))
        ws2 = MagicMock()
        ws2.send_str = AsyncMock(side_effect=Exception("error2"))
        ws3 = MagicMock()
        ws3.send_str = AsyncMock()
        await bridge.add_ws_client(ws1)
        await bridge.add_ws_client(ws2)
        await bridge.add_ws_client(ws3)

        await bridge._broadcast({"type": "test"})

        assert ws1 not in bridge._ws_clients
        assert ws2 not in bridge._ws_clients
        assert ws3 in bridge._ws_clients


class TestRoomManagementSkeleton:
    """验证房间管理方法骨架存在"""

    def test_add_room_method_exists(self):
        """add_room 方法存在"""
        bridge = DanmakuBridge()
        assert hasattr(bridge, "add_room")
        assert callable(bridge.add_room)

    def test_remove_room_method_exists(self):
        """remove_room 方法存在"""
        bridge = DanmakuBridge()
        assert hasattr(bridge, "remove_room")
        assert callable(bridge.remove_room)

    def test_stop_all_method_exists(self):
        """stop_all 方法存在"""
        bridge = DanmakuBridge()
        assert hasattr(bridge, "stop_all")
        assert callable(bridge.stop_all)

    def test_get_status_method_exists(self):
        """get_status 方法存在"""
        bridge = DanmakuBridge()
        assert hasattr(bridge, "get_status")
        assert callable(bridge.get_status)


class TestCallbackRegistration:
    """验证回调注册方法存在"""

    def test_callbacks_setup_on_init(self):
        """初始化后回调已注册（_setup_callbacks 或等效逻辑）"""
        bridge = DanmakuBridge()
        # 应有内部回调处理器属性
        assert hasattr(bridge, "_setup_callbacks") or hasattr(bridge, "_on_danmaku_handler")

    def test_on_danmaku_handler_exists(self):
        """on_danmaku 回调处理器存在"""
        bridge = DanmakuBridge()
        assert hasattr(bridge, "_on_danmaku_handler")
        assert callable(bridge._on_danmaku_handler)

    def test_on_error_handler_exists(self):
        """on_error 回调处理器存在"""
        bridge = DanmakuBridge()
        assert hasattr(bridge, "_on_error_handler")
        assert callable(bridge._on_error_handler)

    def test_on_reconnect_handler_exists(self):
        """on_reconnect 回调处理器存在"""
        bridge = DanmakuBridge()
        assert hasattr(bridge, "_on_reconnect_handler")
        assert callable(bridge._on_reconnect_handler)
