"""快手直播弹幕协议直连引擎（阶段 4）

游客 token 获取方式为**重点验证项**（公开抓包显示需要签名接口），
token 注入点已抽象——实测路径见合规清单与 Open Questions。
"""

import asyncio
import time
from typing import Dict

import websockets
from loguru import logger

from danmaku_listener.contract.models import GapReason
from danmaku_listener.engines.base import BaseEngine
from danmaku_listener.engines.protocol import kuaishou_codec as codec

HEARTBEAT_INTERVAL = 20.0  # 快手心跳口径较短


class KuaishouProtocolEngine(BaseEngine):
    """快手协议直连引擎（复用阶段 1 骨架模式）"""

    platform = "kuaishou"

    def __init__(self, state_store=None, token_provider=None):
        super().__init__(state_store=state_store)
        # token_provider: async (room_id) -> str；游客 token 获取为重点验证项
        self._token_provider = token_provider
        self._room_tasks: Dict[str, asyncio.Task] = {}
        self._stop_flags: Dict[str, bool] = {}

    @property
    def engine_id(self) -> str:
        return "protocol:kuaishou"

    async def start(self, room_id: str) -> None:
        if room_id in self._room_tasks and not self._room_tasks[room_id].done():
            return
        self._stop_flags[room_id] = False
        self._room_tasks[room_id] = asyncio.create_task(self._run_room(room_id), name=f"kuaishou-room-{room_id}")

    async def stop(self, room_id: str) -> None:
        self._stop_flags[room_id] = True
        task = self._room_tasks.pop(room_id, None)
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def restart(self, room_id: str) -> None:
        """仅重启该房间任务（契约 I）"""
        await self.stop(room_id)
        await self.start(room_id)

    async def _run_room(self, room_id: str) -> None:
        logger.info(f"[kuaishou] room {room_id} connecting")
        while not self._stop_flags.get(room_id):
            try:
                if self._token_provider is None:
                    raise ValueError("快手需要游客 token（token_provider 未配置，获取方式为重点验证项）")
                token = await self._token_provider(room_id)

                async with websockets.connect(codec.WS_URL) as ws:
                    await ws.send(codec.build_enter_room(room_id, token))
                    logger.info(f"[kuaishou] room {room_id} enter_room sent")
                    self._set_status(self.status.__class__.RUNNING)
                    hb_task = asyncio.create_task(self._heartbeat(room_id, ws))
                    try:
                        await self._read_loop(room_id, ws)
                    finally:
                        hb_task.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[kuaishou] room {room_id} error: {e}")
                self._set_status(self.status.__class__.ERROR)
                self.mark_gap_start(room_id)
                gap = self.build_gap_message(room_id, GapReason.NETWORK)
                if gap:
                    await self._emit_system(gap)
                if self._stop_flags.get(room_id):
                    return
                await asyncio.sleep(15)

    async def _heartbeat(self, room_id: str, ws) -> None:
        try:
            while True:
                await ws.send(codec.build_heartbeat())
                await asyncio.sleep(HEARTBEAT_INTERVAL)
        except asyncio.CancelledError:
            pass

    async def _read_loop(self, room_id: str, ws) -> None:
        async for raw in ws:
            data = raw if isinstance(raw, bytes) else raw.encode("utf-8")
            ts = int(time.time())
            self.mark_received(room_id, ts)
            mapped_list = codec.map_socket_message(data, self.next_seq(room_id), ts)
            for mapped in mapped_list:
                await self._emit_message({
                    "contract_version": "1.0.0",
                    "category": mapped["category"],
                    "type": mapped["type"],
                    "platform": "kuaishou",
                    "room_id": room_id,
                    "seq": mapped["seq"],
                    "timestamp": mapped["timestamp"],
                    "engine": self.engine_id,
                    "protocol_version": codec.PROTOCOL_VERSION,
                    "msg_id": mapped.get("msg_id"),
                    "payload": mapped["payload"],
                })
