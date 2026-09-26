"""斗鱼直播弹幕协议直连引擎（阶段 3a，独立门禁）"""

import asyncio
import json
import time
from typing import Any, Dict

import websockets
from loguru import logger

from danmaku_listener.contract.models import GapReason
from danmaku_listener.engines.base import BaseEngine
from danmaku_listener.engines.protocol import douyu_codec as codec

PROTOCOL_VERSION = "douyu-1"


class DouyuProtocolEngine(BaseEngine):
    """斗鱼协议直连引擎（复用阶段 1 骨架模式；独立门禁不与虎牙绑驾）"""

    platform = "douyu"

    def __init__(self, state_store=None):
        super().__init__(state_store=state_store)
        self._room_tasks: Dict[str, asyncio.Task] = {}
        self._stop_flags: Dict[str, bool] = {}

    @property
    def engine_id(self) -> str:
        return "protocol:douyu"

    async def start(self, room_id: str) -> None:
        if room_id in self._room_tasks and not self._room_tasks[room_id].done():
            return
        self._stop_flags[room_id] = False
        self._room_tasks[room_id] = asyncio.create_task(self._run_room(room_id), name=f"douyu-room-{room_id}")

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
        logger.info(f"[douyu] room {room_id} connecting")
        while not self._stop_flags.get(room_id):
            try:
                async with websockets.connect(codec.WS_URL) as ws:
                    await ws.send(codec.build_login(room_id))
                    await ws.send(codec.build_join_group(room_id))
                    logger.info(f"[douyu] room {room_id} login+join sent")
                    self._set_status(self.status.__class__.RUNNING)
                    hb_task = asyncio.create_task(self._heartbeat(room_id, ws))
                    try:
                        await self._read_loop(room_id, ws)
                    finally:
                        hb_task.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[douyu] room {room_id} error: {e}")
                self._set_status(self.status.__class__.ERROR)
                self.mark_gap_start(room_id)
                gap = self.build_gap_message(room_id, GapReason.NETWORK)
                if gap:
                    await self._emit_system(gap)
                if self._stop_flags.get(room_id):
                    return
                # 慢速重试（契约 O：指数退避封顶 15 分钟）
                await asyncio.sleep(15)

    async def _heartbeat(self, room_id: str, ws) -> None:
        try:
            while True:
                await ws.send(codec.build_heartbeat())
                await asyncio.sleep(codec.HEARTBEAT_INTERVAL)
        except asyncio.CancelledError:
            pass

    async def _read_loop(self, room_id: str, ws) -> None:
        async for raw in ws:
            data = raw if isinstance(raw, bytes) else raw.encode("utf-8")
            try:
                packets = codec.decode_packets(data)
            except codec.DouyuFrameError as e:
                logger.warning(f"[douyu] room {room_id} frame error: {e}")
                continue
            ts = int(time.time())
            for fields in packets:
                self.mark_received(room_id, ts)
                mapped = codec.map_upstream(fields, self.next_seq(room_id), ts)
                if mapped:
                    await self._emit_message({
                        "contract_version": "1.0.0",
                        "category": mapped["category"],
                        "type": mapped["type"],
                        "platform": "douyu",
                        "room_id": room_id,
                        "seq": mapped["seq"],
                        "timestamp": mapped["timestamp"],
                        "engine": self.engine_id,
                        "protocol_version": PROTOCOL_VERSION,
                        "payload": mapped["payload"],
                    })
                if fields.get("type") == "pingreq":
                    # 服务器心跳请求：响应业务心跳
                    await ws.send(codec.encode_packet(codec.encode_body({"type": "heartbeat"})))
                if fields.get("type") == "killuser" or fields.get("type") == "sysalert":
                    logger.warning(f"[douyu] room {room_id} server alert: {fields}")
                    await self._emit_system(self._system_factory.route_failed(
                        room_id=room_id,
                        seq=self.next_seq(room_id),
                        ts=int(time.time()),
                        reason_code=f"douyu.{fields.get('type', 'alert')}",
                        fix_hint="平台下发风控/系统消息，查看斗鱼风控手册",
                        docs_anchor="docs/platforms/douyu/runbook.md",
                    ))
