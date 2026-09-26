"""虎牙直播弹幕协议直连引擎（阶段 3b，独立门禁；协议 draft 见 codec 文档）"""

import asyncio
import time
from typing import Dict, Optional

import websockets
from loguru import logger

from danmaku_listener.contract.models import GapReason
from danmaku_listener.engines.base import BaseEngine
from danmaku_listener.engines.protocol import huya_codec as codec


class HuyaProtocolEngine(BaseEngine):
    """虎牙协议直连引擎（生命周期同构；payload 解析经 parse_hook 注入）"""

    platform = "huya"

    def __init__(self, state_store=None, parse_hook=None):
        super().__init__(state_store=state_store)
        self._parse_hook = parse_hook
        self._room_tasks: Dict[str, asyncio.Task] = {}
        self._stop_flags: Dict[str, bool] = {}

    @property
    def engine_id(self) -> str:
        return "protocol:huya"

    async def start(self, room_id: str) -> None:
        if room_id in self._room_tasks and not self._room_tasks[room_id].done():
            return
        self._stop_flags[room_id] = False
        self._room_tasks[room_id] = asyncio.create_task(self._run_room(room_id), name=f"huya-room-{room_id}")

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
        logger.info(f"[huya] room {room_id} connecting (protocol draft: 抓包校准前 payload 不解析)")
        while not self._stop_flags.get(room_id):
            try:
                async with websockets.connect(codec.WS_URL) as ws:
                    self._set_status(self.status.__class__.RUNNING)
                    hb_task = asyncio.create_task(self._heartbeat(room_id, ws))
                    try:
                        await self._read_loop(room_id, ws)
                    finally:
                        hb_task.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[huya] room {room_id} error: {e}")
                self._set_status(self.status.__class__.ERROR)
                self.mark_gap_start(room_id)
                gap = self.build_gap_message(room_id, GapReason.NETWORK)
                if gap:
                    await self._emit_system(gap)
                if self._stop_flags.get(room_id):
                    return
                await asyncio.sleep(15)

    async def _heartbeat(self, room_id: str, ws) -> None:
        """平台心跳帧（draft：字段布局以抓包校准为准）"""
        try:
            while True:
                await ws.send(codec.encode_frame(b""))
                await asyncio.sleep(codec.HEARTBEAT_INTERVAL)
        except asyncio.CancelledError:
            pass

    async def _read_loop(self, room_id: str, ws) -> None:
        async for raw in ws:
            data = raw if isinstance(raw, bytes) else raw.encode("utf-8")
            try:
                frames = codec.decode_frames(data)
            except codec.HuyaFrameError as e:
                logger.warning(f"[huya] room {room_id} frame error: {e}")
                continue
            ts = int(time.time())
            for _ver, _seq_frame, payload in frames:
                self.mark_received(room_id, ts)
                for mapped in codec.map_payload(payload, self.next_seq(room_id), ts, self._parse_hook):
                    await self._emit_message({
                        "contract_version": "1.0.0",
                        "category": mapped["category"],
                        "type": mapped["type"],
                        "platform": "huya",
                        "room_id": room_id,
                        "seq": mapped["seq"],
                        "timestamp": mapped["timestamp"],
                        "engine": self.engine_id,
                        "protocol_version": codec.PROTOCOL_VERSION,
                        "payload": mapped["payload"],
                    })
