"""抖音代理/伴侣直听引擎（阶段 2）

现有 ProxyEngine（mitmproxy + DanmakuAddon + dy.proto protobuf 解析）保持不变，
本模块提供两件事：
1. **统一消息桥接**：现有 DouyinAdapter 产出的旧 DanmakuMessage → 契约 v1
   UnifiedMessage（经 contract.legacy 适配器，向后兼容承诺兑现）
2. hook 子路线参数与版本漂移检测锚点（Eng R：直播伴侣版本不符 → ROUTE_FAILED）

ADR-001：代理引擎默认独立进程经本机 IPC 接总线（线格式即 IPC 协议）；
mitmproxy 嵌入 asyncio spike 为可选回退路径。
"""

from typing import Optional

from loguru import logger

from danmaku_listener.adapters.douyin import DouyinAdapter
from danmaku_listener.bus.message import DanmakuMessage
from danmaku_listener.contract import Category, SystemType
from danmaku_listener.contract.legacy import legacy_to_unified
from danmaku_listener.contract.models import Envelope, FailureInfo, RouteFailedPayload, UnifiedMessage
from danmaku_listener.engines.base import BaseEngine
from danmaku_listener.persistence.room_state_store import RoomStateStore

PROTOCOL_VERSION = "douyin-1"


class DouyinProxyEngine(BaseEngine):
    """抖音代理引擎桥接层

    包装现有 ProxyEngine 的消息流：旧 DanmakuMessage → 契约 UnifiedMessage。
    进程拓扑按 ADR-001：独立进程跑 ProxyEngine，经线格式 IPC 接总线；
    本类在总线侧承接其输出。
    """

    platform = "douyin"

    def __init__(self, state_store: Optional[RoomStateStore] = None, adapter: Optional[DouyinAdapter] = None):
        super().__init__(state_store=state_store)
        self._adapter = adapter or DouyinAdapter()

    @property
    def engine_id(self) -> str:
        return "proxy:douyin"

    async def ingest_legacy(self, msg: DanmakuMessage) -> UnifiedMessage:
        """承接代理进程（或旧管线）的旧格式消息 → 契约统一消息并发射"""
        unified = legacy_to_unified(msg, seq=self.next_seq(msg.room_id), engine=self.engine_id)
        await self._emit_message(unified.to_wire())
        self.mark_received(msg.room_id, msg.timestamp)
        return unified

    async def route_failed(
        self, room_id: str, reason_code: str, fix_hint: str, docs_anchor: str
    ) -> UnifiedMessage:
        """路线失效告警（直播伴侣版本漂移、证书失败等）"""
        import time

        msg = UnifiedMessage(
            envelope=Envelope(
                category=Category.SYSTEM, type=SystemType.ROUTE_FAILED.value,
                platform=self.platform, room_id=room_id, seq=self.next_seq(room_id),
                timestamp=int(time.time()), engine=self.engine_id,
            ),
            payload=RouteFailedPayload(
                failure=FailureInfo(reason_code=reason_code, fix_hint=fix_hint, docs_anchor=docs_anchor)
            ),
        )
        await self._emit_message(msg.to_wire())
        return msg

    async def start(self, room_id: str) -> None:
        """代理进程生命周期由常驻服务管理（ADR-001 独立进程）；本桥接层不做直连"""
        logger.info(
            "[douyin] proxy engine runs as its own process (ADR-001); "
            "use ProxyEngine directly or the IPC bridge"
        )

    async def stop(self, room_id: str) -> None:  # pragma: no cover - 桥接层无直连生命周期
        return None

    async def restart(self, room_id: str) -> None:  # pragma: no cover
        """仅重启该房间任务（契约 I）——桥接层无任务，等同 no-op"""
        return None
