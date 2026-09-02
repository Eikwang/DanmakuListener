"""代理引擎

基于 mitmproxy 实现流量拦截，监听抖音直播间弹幕。
使用 Master 编程模式与 asyncio 事件循环共存。
"""

import asyncio
import os
import subprocess
from typing import Any, Set

from loguru import logger

from mitmproxy.options import Options
from mitmproxy.master import Master

from danmaku_listener.engines.base import BaseEngine, EngineStatus
from danmaku_listener.engines.danmaku_addon import DanmakuAddon
from danmaku_listener.managers.system_proxy_manager import SystemProxyManager


class ProxyStartError(Exception):
    """代理启动失败异常"""
    pass


class ProxyEngine(BaseEngine):
    """代理引擎

    通过系统代理拦截抖音 WebSocket 流量，解析弹幕消息。
    使用 mitmproxy Master 编程模式，与 asyncio 事件循环共存。
    多个房间共享同一 mitmproxy 实例（单例模式）。
    """

    def __init__(self, settings: Any = None):
        """初始化代理引擎

        Args:
            settings: Settings 配置实例（可选，默认使用 get_settings()）
        """
        super().__init__()

        if settings is None:
            from danmaku_listener.config.settings import get_settings
            settings = get_settings()

        self._settings = settings

        # 系统代理管理器
        used_proxy = getattr(settings, "used_proxy", True)
        self._system_proxy = SystemProxyManager(enabled=used_proxy)

        # DanmakuAddon 实例
        self._addon = DanmakuAddon(
            message_callback=self._on_addon_message,
            settings=settings,
        )

        # mitmproxy Master 实例
        self._master: Any = None

        # 代理启动标记（单例）
        self._started: bool = False

        # 活跃房间 ID 集合
        self._room_ids: Set[str] = set()

        # 代理任务引用
        self._proxy_task: Any = None

    @property
    def platform(self) -> str:
        """返回平台标识"""
        return "douyin"

    async def start(self, room_id: str) -> None:
        """启动代理监听

        Args:
            room_id: 房间 ID
        """
        logger.info(f"ProxyEngine starting for room: {room_id}")

        # 记录房间
        self._room_ids.add(room_id)

        # 如果代理已启动，仅记录房间
        if self._started:
            logger.debug(f"Proxy already running, room {room_id} added")
            self._set_status(EngineStatus.RUNNING)
            return

        # 首次启动
        self._set_status(EngineStatus.STARTING)
        try:
            await self._start_proxy(room_id)
            self._set_status(EngineStatus.RUNNING)
        except ProxyStartError:
            self._room_ids.discard(room_id)
            self._set_status(EngineStatus.STOPPED)
            raise

    async def stop(self, room_id: str) -> None:
        """停止代理监听

        Args:
            room_id: 房间 ID
        """
        logger.info(f"ProxyEngine stopping for room: {room_id}")

        # 移除房间
        self._room_ids.discard(room_id)

        # 如果还有其他房间在监听，不停止代理
        if self._room_ids:
            logger.debug(f"Other rooms still active ({self._room_ids}), proxy keeps running")
            return

        # 最后一个房间停止，关闭代理
        try:
            await self._stop_proxy(room_id)
        finally:
            # 确保系统代理恢复 → AC-013
            self._system_proxy.close()

        self._set_status(EngineStatus.STOPPED)

    async def restart(self, room_id: str) -> None:
        """重启代理监听

        Args:
            room_id: 房间 ID
        """
        logger.info(f"ProxyEngine restarting for room: {room_id}")
        await self.stop(room_id)
        await self.start(room_id)

    async def _start_proxy(self, room_id: str) -> None:
        """启动 mitmproxy 代理服务

        Args:
            room_id: 房间 ID

        Raises:
            ProxyStartError: 端口冲突或启动失败
        """
        if self._started:
            return

        # 1. 注册系统代理
        proxy_host = getattr(self._settings, "proxy_host", "127.0.0.1")
        proxy_port = getattr(self._settings, "proxy_port", 8827)
        self._system_proxy.register(proxy_host, proxy_port)

        # 2. 信任证书（失败仅警告）→ AC-009
        self._trust_certificate()

        # 3. 创建 mitmproxy Master
        try:
            cert_dir = os.path.expanduser(
                getattr(self._settings, "cert_dir", "~/.mitmproxy")
            )

            opts = Options(
                listen_host=proxy_host,
                listen_port=proxy_port,
                confdir=cert_dir,
            )

            self._master = Master(opts)
            self._master.addons.add(self._addon)

            # 4. 启动 mitmproxy 事件循环
            self._proxy_task = asyncio.create_task(self._master.run())

            self._started = True
            logger.info(f"Proxy started on {proxy_host}:{proxy_port}")

        except OSError as e:
            logger.error(f"Proxy start failed: {e}")
            raise ProxyStartError(f"Failed to start proxy: {e}") from e
        except Exception as e:
            logger.error(f"Proxy start failed: {e}")
            raise ProxyStartError(f"Failed to start proxy: {e}") from e

    async def _stop_proxy(self, room_id: str) -> None:
        """停止 mitmproxy 代理服务

        Args:
            room_id: 房间 ID
        """
        try:
            if self._master:
                self._master.shutdown()
                logger.info("Proxy master shutdown requested")
        except Exception as e:
            logger.warning(f"Error shutting down proxy master: {e}")
        finally:
            self._master = None
            self._started = False
            self._proxy_task = None

    def _trust_certificate(self) -> bool:
        """信任 mitmproxy 根证书

        调用 certutil 将根证书添加到系统信任存储。
        失败仅记录警告，不阻止启动 → AC-009

        Returns:
            True 如果成功，False 如果失败
        """
        cert_dir = os.path.expanduser(
            getattr(self._settings, "cert_dir", "~/.mitmproxy")
        )
        cert_path = os.path.join(cert_dir, "mitmproxy-ca-cert.cer")

        if not os.path.exists(cert_path):
            logger.debug(f"Certificate not found at {cert_path}, will be generated on first start")
            return True

        try:
            result = subprocess.run(
                ["certutil", "-addstore", "Root", cert_path],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                logger.info("Certificate trusted successfully")
                return True
            else:
                logger.warning(f"Certificate trust failed: {result.stderr}")
                return False
        except Exception as e:
            logger.warning(f"Certificate trust failed: {e}")
            return False

    async def _on_addon_message(self, data: dict) -> None:
        """DanmakuAddon 消息回调

        将 addon 的消息转发到引擎的消息回调系统。
        对 ws_disconnect 消息触发重连逻辑。

        Args:
            data: 消息数据字典
        """
        msg_type = data.get("type", "")

        if msg_type == "ws_disconnect":
            # WebSocket 断线 → 触发重连 → AC-012
            room_id = data.get("room_id", "")
            error = ConnectionError(f"WebSocket disconnected for room {room_id}")
            await self._handle_error_with_reconnect(room_id, error)
            return

        # 其他消息正常转发
        await self._emit_message(data)
