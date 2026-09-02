"""监听引擎抽象基类

定义所有监听引擎必须实现的接口，确保代理模式和浏览器模式的统一行为。
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

from loguru import logger

from danmaku_listener.managers.reconnect_manager import ReconnectManager


class EngineStatus(str, Enum):
    """引擎状态枚举"""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"
    RECONNECTING = "reconnecting"


# 回调函数类型
MessageCallback = Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]
ErrorCallback = Callable[[Exception], Coroutine[Any, Any, None]]


class BaseEngine(ABC):
    """监听引擎抽象基类

    所有具体的监听引擎（代理模式、浏览器模式）都必须继承此类并实现抽象方法。
    """

    def __init__(self):
        """初始化引擎"""
        self._status: EngineStatus = EngineStatus.STOPPED
        self._message_callbacks: List[MessageCallback] = []
        self._error_callbacks: List[ErrorCallback] = []
        self._reconnect_manager: Optional[ReconnectManager] = None

    @property
    def status(self) -> EngineStatus:
        """获取当前状态"""
        return self._status

    @abstractmethod
    async def start(self, room_id: str) -> None:
        """启动对指定房间的监听

        Args:
            room_id: 房间 ID
        """
        pass

    @abstractmethod
    async def stop(self, room_id: str) -> None:
        """停止对指定房间的监听

        Args:
            room_id: 房间 ID
        """
        pass

    @abstractmethod
    async def restart(self, room_id: str) -> None:
        """重启对指定房间的监听

        Args:
            room_id: 房间 ID
        """
        pass

    def on_message(self, callback: MessageCallback) -> None:
        """注册消息回调

        Args:
            callback: 异步回调函数
        """
        self._message_callbacks.append(callback)

    def on_error(self, callback: ErrorCallback) -> None:
        """注册错误回调

        Args:
            callback: 异步回调函数
        """
        self._error_callbacks.append(callback)

    async def _emit_message(self, data: Dict[str, Any]) -> None:
        """触发消息事件

        Args:
            data: 消息数据字典
        """
        for callback in self._message_callbacks:
            try:
                await callback(data)
            except Exception as e:
                # 不中断其他回调的执行
                pass

    async def _emit_error(self, error: Exception) -> None:
        """触发错误事件

        Args:
            error: 异常对象
        """
        for callback in self._error_callbacks:
            try:
                await callback(error)
            except Exception:
                pass

    def _set_status(self, status: EngineStatus) -> None:
        """更新状态

        Args:
            status: 新状态
        """
        self._status = status

    def set_reconnect_manager(self, manager: ReconnectManager) -> None:
        """设置重连管理器

        Args:
            manager: ReconnectManager 实例
        """
        self._reconnect_manager = manager
        logger.debug(f"Set reconnect manager for {self.__class__.__name__}")

    async def _handle_error_with_reconnect(self, room_id: str, error: Exception) -> bool:
        """处理错误并尝试重连

        如果设置了重连管理器，尝试通过 restart 重连。
        重连成功后发布 reconnect_success 消息。
        无重连管理器或重连失败时触发错误回调。

        Args:
            room_id: 房间 ID
            error: 原始错误

        Returns:
            True 如果重连成功，False 如果重连失败或无重连管理器
        """
        if self._reconnect_manager is None:
            # 无重连管理器，直接触发错误回调
            await self._emit_error(error)
            return False

        # 尝试重连
        async def reconnect_callback() -> bool:
            try:
                await self.restart(room_id)
                return True
            except Exception as e:
                logger.warning(f"Reconnect restart failed for room {room_id}: {e}")
                return False

        success = await self._reconnect_manager.reconnect(reconnect_callback, room_id)

        if success:
            # 重连成功，发布状态消息
            await self._emit_message({
                "type": "reconnect_success",
                "room_id": room_id,
            })
            return True
        else:
            # 重连失败，触发错误回调
            await self._emit_error(error)
            return False