"""DanmakuBridge — 前后端桥接层

持有 DanmakuListener 实例，桥接 EventBus 事件到 WebSocket 客户端。
"""

import json
from typing import Any, Dict, List, Set

from aiohttp import web
from loguru import logger


class RoomError(Exception):
    """房间操作错误（带 HTTP 状态码）"""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class DanmakuBridge:
    """前后端桥接层

    职责：
    - 持有 DanmakuListener 实例
    - 管理 WebSocket 客户端连接
    - 广播弹幕消息到前端
    - 关键词过滤
    - 系统代理控制
    """

    def __init__(self) -> None:
        """初始化桥接器"""
        # DanmakuListener 实例（延迟初始化，避免 import 循环）
        self._listener: Any = None

        # WebSocket 客户端集合
        self._ws_clients: Set[web.WebSocketResponse] = set()

        # 房间状态跟踪
        self._rooms: Dict[str, Dict[str, Any]] = {}

        # 关键词屏蔽
        self._blocked_keywords: List[str] = []
        self._keyword_filter_enabled: bool = True
        self._load_blocked_keywords()

        # 设置回调
        self._setup_callbacks()

    def _setup_callbacks(self) -> None:
        """注册 DanmakuListener 事件回调

        回调在 listener.start() 时才真正订阅到 EventBus。
        这里通过 listener.on_danmaku() 等方法注册回调函数。
        """
        try:
            self.listener.on_danmaku(self._on_danmaku_handler)
            self.listener.on_error(self._on_error_handler)
            self.listener.on_reconnect(self._on_reconnect_handler)
            self.listener.on_status_change(self._on_status_change_handler)
        except Exception as e:
            logger.warning(f"Failed to register callbacks (listener not ready): {e}")

    @property
    def listener(self) -> Any:
        """获取 DanmakuListener 实例（延迟初始化）"""
        if self._listener is None:
            from danmaku_listener import DanmakuListener
            self._listener = DanmakuListener()
        return self._listener

    async def add_ws_client(self, ws: web.WebSocketResponse) -> None:
        """添加 WebSocket 客户端"""
        self._ws_clients.add(ws)
        logger.debug(f"WS client added, total: {len(self._ws_clients)}")

    async def remove_ws_client(self, ws: web.WebSocketResponse) -> None:
        """移除 WebSocket 客户端"""
        self._ws_clients.discard(ws)
        logger.debug(f"WS client removed, total: {len(self._ws_clients)}")

    async def _broadcast(self, message: dict) -> None:
        """广播消息到所有 WebSocket 客户端

        发送失败的客户端会被自动移除。
        """
        msg_str = json.dumps(message, ensure_ascii=False)
        dead_clients: Set[web.WebSocketResponse] = set()

        for client in self._ws_clients:
            try:
                await client.send_str(msg_str)
            except Exception:
                dead_clients.add(client)

        if dead_clients:
            self._ws_clients -= dead_clients
            logger.debug(f"Removed {len(dead_clients)} dead WS clients")

    def _load_blocked_keywords(self) -> None:
        """从文件加载屏蔽关键词"""
        import os
        kw_file = os.path.join(os.path.dirname(__file__), "blocked_keywords.json")
        try:
            with open(kw_file, "r", encoding="utf-8") as f:
                self._blocked_keywords = json.load(f)
            logger.info(f"Loaded {len(self._blocked_keywords)} blocked keywords")
        except (FileNotFoundError, json.JSONDecodeError):
            self._blocked_keywords = []
            logger.info("No blocked keywords loaded (file not found or empty)")

    def _save_blocked_keywords(self) -> None:
        """保存屏蔽关键词到文件"""
        import os
        kw_file = os.path.join(os.path.dirname(__file__), "blocked_keywords.json")
        with open(kw_file, "w", encoding="utf-8") as f:
            json.dump(self._blocked_keywords, f, indent=2, ensure_ascii=False)

    def get_keywords(self) -> dict:
        """获取关键词列表和过滤状态 → AC-007"""
        return {
            "keywords": list(self._blocked_keywords),
            "enabled": self._keyword_filter_enabled,
        }

    def add_keyword(self, keyword: str) -> dict:
        """添加屏蔽关键词 → AC-007

        Args:
            keyword: 关键词文本

        Returns:
            操作结果字典

        Raises:
            ValueError: 关键词长度超过 50 字符
        """
        if len(keyword) > 50:
            raise ValueError("Keyword length exceeds 50 characters")

        if keyword not in self._blocked_keywords:
            self._blocked_keywords.append(keyword)
            self._save_blocked_keywords()
            logger.info(f"Keyword added: {keyword}")

        return {"success": True, "keywords": list(self._blocked_keywords)}

    def remove_keyword(self, keyword: str) -> dict:
        """删除屏蔽关键词 → AC-018

        Args:
            keyword: 要删除的关键词

        Returns:
            操作结果字典
        """
        if keyword in self._blocked_keywords:
            self._blocked_keywords.remove(keyword)
            self._save_blocked_keywords()
            logger.info(f"Keyword removed: {keyword}")

        return {"success": True, "keywords": list(self._blocked_keywords)}

    def toggle_keyword_filter(self, enabled: bool) -> dict:
        """开启/关闭关键词过滤 → AC-018

        Args:
            enabled: 是否启用过滤

        Returns:
            操作结果字典
        """
        self._keyword_filter_enabled = enabled
        logger.info(f"Keyword filter {'enabled' if enabled else 'disabled'}")
        return {"success": True, "enabled": self._keyword_filter_enabled}

    def get_status(self) -> dict:
        """获取系统整体状态"""
        return {
            "backend_connected": True,
            "rooms_count": len(self._rooms),
            "proxy": self._get_proxy_status(),
            "keyword_filter": {
                "enabled": self._keyword_filter_enabled,
                "count": len(self._blocked_keywords),
            },
        }

    def _get_proxy_status(self) -> dict:
        """获取代理状态（读取注册表）"""
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0,
                winreg.KEY_READ,
            )
            enabled = winreg.QueryValueEx(key, "ProxyEnable")[0] == 1
            server = ""
            if enabled:
                try:
                    server = winreg.QueryValueEx(key, "ProxyServer")[0]
                except Exception:
                    server = ""
            winreg.CloseKey(key)

            if enabled and server:
                parts = server.split(":")
                return {
                    "enabled": True,
                    "host": parts[0],
                    "port": int(parts[1]) if len(parts) > 1 else 8827,
                }
            return {"enabled": False, "host": "", "port": 0}
        except Exception:
            return {"enabled": False, "host": "", "port": 0}

    def _get_system_proxy_manager(self):
        """获取 SystemProxyManager 实例"""
        from danmaku_listener.managers.system_proxy_manager import SystemProxyManager
        return SystemProxyManager(enabled=True)

    def _get_proxy_host(self) -> str:
        """获取配置的代理地址"""
        try:
            from danmaku_listener.config.settings import get_settings
            settings = get_settings()
            return getattr(settings, "proxy_host", "127.0.0.1")
        except Exception:
            return "127.0.0.1"

    def _get_proxy_port(self) -> int:
        """获取配置的代理端口"""
        try:
            from danmaku_listener.config.settings import get_settings
            settings = get_settings()
            return getattr(settings, "proxy_port", 8827)
        except Exception:
            return 8827

    async def enable_proxy(self) -> dict:
        """开启系统代理 → AC-004

        Returns:
            操作结果字典
        """
        host = self._get_proxy_host()
        port = self._get_proxy_port()
        spm = self._get_system_proxy_manager()

        success = spm.register(host, port)
        if success:
            return {"success": True, "enabled": True, "host": host, "port": port}
        else:
            return {"success": False, "error": "Failed to set system proxy, check permissions"}

    async def disable_proxy(self) -> dict:
        """关闭系统代理 → AC-011

        Returns:
            操作结果字典
        """
        spm = self._get_system_proxy_manager()

        success = spm.close()
        if success:
            return {"success": True, "enabled": False, "host": "", "port": 0}
        else:
            return {"success": False, "error": "Failed to disable system proxy"}

    async def add_room(self, room_spec: str) -> dict:
        """添加房间并启动监听

        Args:
            room_spec: 房间规格，格式为 "platform:room_id"

        Returns:
            操作结果字典，包含 room 信息

        Raises:
            RoomError: 格式错误(400)、平台不支持(400)、重复(409)、启动失败(500)
        """
        from danmaku_listener.utils.platform_parser import parse_room_spec, get_default_engine
        from danmaku_listener.engines.proxy_engine import ProxyStartError

        # 1. 校验格式
        try:
            spec = parse_room_spec(room_spec)
        except ValueError as e:
            raise RoomError(str(e), status=400)

        # 2. 检查重复 → AC-013
        room_key = f"{spec.platform}:{spec.room_id}"
        if room_key in self._rooms:
            raise RoomError(f"Room already exists: {room_key}", status=409)

        # 3. 启动监听
        try:
            await self.listener.start([room_spec])
        except ProxyStartError as e:
            raise RoomError(str(e), status=500)
        except ValueError as e:
            raise RoomError(str(e), status=400)

        # 4. 记录房间状态
        engine_type = get_default_engine(spec.platform)
        self._rooms[room_key] = {
            "platform": spec.platform,
            "room_id": spec.room_id,
            "status": "running",
            "engine_type": engine_type,
        }

        logger.info(f"*Room added: {room_key} ({engine_type})")

        return {
            "success": True,
            "room": self._rooms[room_key],
        }

    async def remove_room(self, platform: str, room_id: str) -> dict:
        """停止并移除房间

        Args:
            platform: 平台标识
            room_id: 房间 ID

        Returns:
            操作结果字典

        Raises:
            RoomError: 房间不存在(404)
        """
        room_key = f"{platform}:{room_id}"

        if room_key not in self._rooms:
            raise RoomError(f"Room not found: {room_key}", status=404)

        # 从状态中移除
        self._rooms.pop(room_key)

        # 停止监听
        try:
            await self.listener.stop()
        except Exception as e:
            logger.error(f"Error stopping listener for {room_key}: {e}")

        logger.info(f"Room removed: {room_key}")

        return {
            "success": True,
            "message": f"Room {room_key} stopped and removed",
        }

    async def stop_all(self) -> dict:
        """停止所有房间监听并恢复系统代理 → AC-006, BR-006

        Returns:
            操作结果字典
        """
        if not self._rooms:
            return {"success": True, "message": "No rooms to stop"}

        room_count = len(self._rooms)
        self._rooms.clear()

        # 停止所有监听（DanmakuListener.stop 会处理引擎停止和系统代理恢复）
        try:
            await self.listener.stop()
        except Exception as e:
            logger.error(f"Error stopping all rooms: {e}")

        logger.info(f"All rooms stopped ({room_count}), proxy restored")

        return {
            "success": True,
            "message": f"All rooms stopped ({room_count}), proxy restored",
        }

    async def _on_danmaku_handler(self, msg: Any) -> None:
        """弹幕事件回调处理器

        接收 DanmakuMessage，执行关键词过滤后广播到前端。
        → AC-005, AC-007, AC-014, AC-015, BR-005
        """
        # 关键词过滤（仅普通弹幕）→ BR-005
        if self._keyword_filter_enabled and msg.message_type == "normal":
            if any(kw in msg.content for kw in self._blocked_keywords):
                logger.debug(f"Danmaku filtered by keyword: {msg.content[:30]}")
                return

        # 转换为前端格式并广播
        await self._broadcast({"type": "danmaku", "data": msg.to_dict()})

    async def _on_error_handler(self, error: Exception) -> None:
        """错误事件回调处理器

        广播错误消息到所有 WS 客户端。
        """
        await self._broadcast({
            "type": "error",
            "data": {"message": str(error)},
        })

    async def _on_reconnect_handler(self, room_id: str) -> None:
        """重连事件回调处理器

        广播重连状态到所有 WS 客户端。→ AC-012
        """
        await self._broadcast({
            "type": "reconnect",
            "data": {"room_id": room_id, "status": "reconnecting"},
        })

    async def _on_status_change_handler(self, room_id: str, status: str) -> None:
        """状态变化回调处理器

        更新房间状态并广播到前端。
        """
        room_key = f"douyin:{room_id}"  # 默认平台为 douyin
        # 尝试匹配已记录的房间
        for key in self._rooms:
            if key.endswith(f":{room_id}"):
                room_key = key
                break

        if room_key in self._rooms:
            self._rooms[room_key]["status"] = status

        await self._broadcast({
            "type": "status_change",
            "data": {"room_id": room_id, "status": status},
        })

    async def shutdown(self) -> None:
        """关闭桥接器，释放资源"""
        if self._listener is not None:
            try:
                await self._listener.stop()
            except Exception as e:
                logger.error(f"Error stopping listener: {e}")
            self._listener = None

        # 关闭所有 WebSocket 客户端
        for client in list(self._ws_clients):
            try:
                await client.close()
            except Exception:
                pass
        self._ws_clients.clear()
