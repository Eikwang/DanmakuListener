"""虎牙直播弹幕协议直连引擎（阶段 3b，2026-09 完成协议栈实现）

命令流（barrage-fly SDK 对照 + 浏览器真实帧验证）：
1. roomInit：GET www.huya.com/{room} → tid（lChannelId/TT_ROOM_DATA）
2. WS 连接 wss://cdnws.api.huya.com:443
3. doLaunch（op=3 WupReq liveui/doLaunch）
4. registerGroup（op=16，vGroupId=["live:{tid}","chat:{tid}"]）
5. updateUserInfo（op=33）
6. 心跳（op=20 WupReq onlineui/OnUserHeartBeat，25s 周期/首帧 15s）
7. 下推（op=7）→ WSPushMessage.lUri 分发（1400 弹幕/6501 礼物/6110 进场）
"""

import asyncio
import time
from typing import Dict

import websockets
from loguru import logger

from danmaku_listener.contract.models import GapReason
from danmaku_listener.engines.base import BaseEngine
from danmaku_listener.engines.protocol import huya_codec as codec
from danmaku_listener.engines.protocol.huya_tars import TarsError

PROTOCOL_VERSION = codec.PROTOCOL_VERSION
HEARTBEAT_INITIAL_DELAY = 15.0

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://www.huya.com/",
}


class HuyaProtocolEngine(BaseEngine):
    """虎牙协议直连引擎（Tars 栈完整实现）"""

    platform = "huya"

    def __init__(self, state_store=None):
        super().__init__(state_store=state_store)
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

    # ---- 房间初始化 ----

    @staticmethod
    def _fetch_tid_sync(room_id: str) -> int:
        """直播间页面提取 tid（TT_ROOM_DATA.lChannelId/hyPlayerConfig）"""
        import re

        import requests

        resp = requests.get(
            f"https://www.huya.com/{room_id}", headers=HTTP_HEADERS, timeout=10
        )
        resp.raise_for_status()
        body = resp.text
        m = re.search(r'"tid"\s*:\s*(\d+)', body) or re.search(
            r'"lChannelId"\s*:\s*"?(\d+)', body
        )
        if not m:
            raise ValueError("虎牙房间页未找到 tid（房间不存在或页面结构变更）")
        return int(m.group(1))

    async def _fetch_tid(self, room_id: str) -> int:
        return await asyncio.get_running_loop().run_in_executor(
            None, self._fetch_tid_sync, room_id
        )

    # ---- 房间任务主循环 ----

    async def _run_room(self, room_id: str) -> None:
        logger.info(f"[huya] room {room_id} connecting")
        while not self._stop_flags.get(room_id):
            try:
                tid = await self._fetch_tid(room_id)
                async with websockets.connect(codec.WS_URL, ping_interval=None) as ws:
                    # 命令流：doLaunch → registerGroup → updateUserInfo
                    await ws.send(codec.build_do_launch())
                    await ws.send(codec.build_register_group(tid))
                    await ws.send(codec.build_update_user_info())
                    logger.info(f"[huya] room {room_id} doLaunch+registerGroup sent (tid={tid})")
                    self._set_status(self.status.__class__.RUNNING)
                    hb_task = asyncio.create_task(self._heartbeat(room_id, ws, tid))
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

    async def _heartbeat(self, room_id: str, ws, tid: int) -> None:
        """平台心跳（首帧 15s 延迟 + 25s 周期，SDK 默认口径）"""
        try:
            await asyncio.sleep(HEARTBEAT_INITIAL_DELAY)
            while True:
                await ws.send(codec.build_heartbeat(tid))
                await asyncio.sleep(codec.HEARTBEAT_INTERVAL)
        except asyncio.CancelledError:
            pass

    async def _read_loop(self, room_id: str, ws) -> None:
        async for raw in ws:
            data = raw if isinstance(raw, bytes) else raw.encode("utf-8")
            ts = int(time.time())
            try:
                cmd = codec.decode_command(data)
            except (TarsError, Exception) as e:  # noqa: BLE001
                logger.warning(f"[huya] room {room_id} frame error: {e}")
                continue
            op = cmd["operation"]
            v_data = cmd["v_data"]
            if op == codec.OP_WUP_RSP:
                # doLaunch/心跳 Wup 应答（连接存活确认）
                self.mark_received(room_id, ts)
                continue
            if op in (codec.OP_REGISTER_GROUP_RSP, codec.OP_UPDATE_USER_INFO_RSP,
                      codec.OP_HEARTBEAT_RSP):
                self.mark_received(room_id, ts)
                continue
            if op == codec.OP_MSG_PUSH:
                self.mark_received(room_id, ts)
                try:
                    push = codec.decode_push_message(v_data)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[huya] room {room_id} push decode error: {e}")
                    continue
                if not push:
                    continue
                mapped = codec.map_upstream(
                    push["data"], push["uri"], self.next_seq(room_id), ts
                )
                if mapped:
                    await self._emit_message({
                        "contract_version": "1.0.0",
                        "category": mapped["category"],
                        "type": mapped["type"],
                        "platform": "huya",
                        "room_id": room_id,
                        "seq": mapped["seq"],
                        "timestamp": mapped["timestamp"],
                        "engine": self.engine_id,
                        "protocol_version": PROTOCOL_VERSION,
                        "payload": mapped["payload"],
                    })
