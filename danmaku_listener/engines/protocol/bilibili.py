"""B站直播弹幕协议直连引擎（阶段 1）

每房间一条 asyncio 任务 + WS 长连接（进程拓扑见 ADR-001）。
协议编解码见 bilibili_codec.py（纯函数，fixtures 回放测试直接覆盖）。
"""

import asyncio
import json
import time
from typing import Any, Callable, Dict, List, Optional

import websockets
from loguru import logger

from danmaku_listener.contract.models import GapReason
from danmaku_listener.engines.base import BaseEngine
from danmaku_listener.engines.protocol import bilibili_codec as codec
from danmaku_listener.managers.reconnect_manager import ReconnectManager

HEARTBEAT_INTERVAL = 30.0
PROTOCOL_VERSION = "bilibili-1"  # 协议版本元数据（调试三项）


class DanmuInfoFetcher:
    """获取弹幕服务器 token（getDanmuInfo）。游客可访问；注入替代实现便于测试。"""

    async def fetch(self, room_id: int) -> Dict[str, Any]:
        import requests

        def _sync() -> Dict[str, Any]:
            resp = requests.get(codec.DANMU_INFO_URL.format(room_id=room_id), timeout=10,
                                headers={"User-Agent": "Mozilla/5.0 (danmaku-listener)"})
            resp.raise_for_status()
            return resp.json()

        return await asyncio.get_running_loop().run_in_executor(None, _sync)


class BilibiliProtocolEngine(BaseEngine):
    """B站协议直连引擎

    start/stop/restart(room_id) 公开契约不变（restart 仅重启该房间任务）。
    """

    platform = "bilibili"

    def __init__(
        self,
        state_store=None,
        reconnect_manager: Optional[ReconnectManager] = None,
        danmu_info_fetcher: Optional[Callable[[int], Dict[str, Any]]] = None,
    ):
        super().__init__(state_store=state_store)
        if reconnect_manager:
            self.set_reconnect_manager(reconnect_manager)
        self._danmu_info = danmu_info_fetcher or DanmuInfoFetcher()
        self._room_tasks: Dict[str, asyncio.Task] = {}
        self._room_ws: Dict[str, Any] = {}
        self._heartbeats: Dict[str, asyncio.Task] = {}

    @property
    def engine_id(self) -> str:
        return "protocol:bilibili"

    # ---- 公开契约 ----

    async def start(self, room_id: str) -> None:
        if room_id in self._room_tasks and not self._room_tasks[room_id].done():
            return
        self._set_status(self.status if self.status != self.status.__class__.STOPPED else self.status.__class__.STARTING)
        task = asyncio.create_task(self._run_room(room_id), name=f"bilibili-room-{room_id}")
        self._room_tasks[room_id] = task

    async def stop(self, room_id: str) -> None:
        task = self._room_tasks.pop(room_id, None)
        ws = self._room_ws.pop(room_id, None)
        hb = self._heartbeats.pop(room_id, None)
        if hb:
            hb.cancel()
        if ws:
            await ws.close()
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def restart(self, room_id: str) -> None:
        """语义：仅重启该房间的 asyncio 任务（契约 I 项）"""
        await self.stop(room_id)
        await self.start(room_id)

    # ---- 房间任务主循环 ----

    async def _run_room(self, room_id: str) -> None:
        room_id_int = int(room_id)
        logger.info(f"[bilibili] room {room_id} connecting")
        while True:
            try:
                info = await self._danmu_info.fetch(room_id_int)
                token = str(info.get("data", {}).get("token", ""))
                if not token:
                    raise ValueError("getDanmuInfo 未返回 token（房间号错误或风控）")

                async with websockets.connect(codec.WS_URL) as ws:
                    self._room_ws[room_id] = ws
                    await ws.send(codec.encode_packet(codec.OP_AUTH, codec.build_auth_body(room_id_int, token)))
                    logger.info(f"[bilibili] room {room_id} auth sent")

                    hb_task = asyncio.create_task(self._heartbeat(room_id, ws))
                    self._heartbeats[room_id] = hb_task
                    self._set_status(self.status.__class__.RUNNING)
                    try:
                        await self._read_loop(room_id, ws)
                    finally:
                        hb_task.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[bilibili] room {room_id} error: {e}")
                self._set_status(self.status.__class__.ERROR)
                self.mark_gap_start(room_id)
                handled = await self._handle_error_with_reconnect(room_id, e)
                if not handled:
                    # 无重连管理器：按契约 O 走慢速重试（无限，退避封顶）
                    await asyncio.sleep(15)
                else:
                    # 重连成功：补发 GAP（断线窗口）
                    gap = self.build_gap_message(room_id, GapReason.NETWORK)
                    if gap:
                        await self._emit_system(gap)
                    self._set_status(self.status.__class__.RUNNING)

    async def _heartbeat(self, room_id: str, ws) -> None:
        """平台连接心跳（30s，与引擎存活心跳独立）"""
        try:
            while True:
                await ws.send(codec.encode_packet(codec.OP_HEARTBEAT))
                await asyncio.sleep(HEARTBEAT_INTERVAL)
        except asyncio.CancelledError:
            pass

    async def _read_loop(self, room_id: str, ws) -> None:
        """读循环：解帧 → 解压 → op 分发 → 映射发射"""
        async for raw in ws:
            data = raw if isinstance(raw, bytes) else raw.encode("utf-8")
            try:
                packets = codec.decode_packets(data)
            except codec.BilibiliFrameError as e:
                logger.warning(f"[bilibili] room {room_id} frame error: {e}")
                continue
            for proto, op, body in packets:
                if op == codec.OP_HEARTBEAT_REPLY:
                    popularity = codec.parse_heartbeat_reply(body)
                    if popularity is not None:
                        self._emit_stats(room_id, popularity)
                    continue
                if op == 8:  # 服务器关闭帧
                    logger.info(f"[bilibili] room {room_id} closed by server")
                    return
                if op != codec.OP_SEND_MSG_REPLY:
                    continue
                # proto 2/3 为压缩嵌套包；0/1 为裸 JSON
                if proto in (codec.PROTOCOL_ZLIB, codec.PROTOCOL_BROTLI):
                    try:
                        inner_packets = codec.decompress(proto, body)
                    except codec.BilibiliFrameError as e:
                        logger.warning(f"[bilibili] room {room_id} decompress error: {e}")
                        continue
                else:
                    inner_packets = [(proto, body)]
                for _ip, _iop, inner_body in inner_packets:
                    if _iop != codec.OP_SEND_MSG_REPLY:
                        continue
                    try:
                        text = inner_body.decode("utf-8")
                    except UnicodeDecodeError:
                        continue
                    for packet_text in self._iter_json_packets(text):
                        for mapped in self._map_and_envelope(packet_text, room_id):
                            await self._emit_message(mapped)

    def _iter_json_packets(self, text: str) -> List[str]:
        """op=5 的 body 可能含多条 JSON 串接（无分隔）——逐个解码"""
        decoder = json.JSONDecoder()
        results: List[str] = []
        idx = 0
        while idx < len(text):
            while idx < len(text) and text[idx].isspace():
                idx += 1
            if idx >= len(text):
                break
            try:
                obj, end = decoder.raw_decode(text, idx)
                results.append(json.dumps(obj, ensure_ascii=False))
                idx = end
            except json.JSONDecodeError:
                break
        return results

    def _map_and_envelope(self, text: str, room_id: str) -> List[Dict[str, Any]]:
        """上游 JSON → 线格式 dict（协议版本元数据入信封）"""
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            return []
        out: List[Dict[str, Any]] = []
        seq = self.next_seq(room_id)
        ts = int(time.time())
        if isinstance(doc, dict) and doc.get("cmd") == "DANMU_MSG" and isinstance(doc.get("info"), list):
            mapped = codec.map_upstream_message("DANMU_MSG", doc["info"], seq, ts)
        elif isinstance(doc, dict):
            mapped = codec.map_upstream_message(str(doc.get("cmd", "")), doc.get("data"), seq, ts)
        else:
            mapped = None
        if mapped:
            out.append({
                "contract_version": "1.0.0",
                "category": mapped["category"],
                "type": mapped["type"],
                "platform": "bilibili",
                "room_id": room_id,
                "seq": mapped["seq"],
                "timestamp": mapped["timestamp"],
                "engine": self.engine_id,
                "protocol_version": PROTOCOL_VERSION,
                "payload": mapped["payload"],
            })
        self.mark_received(room_id, ts)
        return out

    def _emit_stats(self, room_id: str, popularity: int) -> None:
        """人气值 → ROOM_STATS（fire-and-forget 经回调）"""
        mapped = codec.map_upstream_message(
            "ONLINE_RANK_COUNT", {"count": popularity}, self.next_seq(room_id), int(time.time())
        )
        if mapped:
            import asyncio

            wire = {
                "contract_version": "1.0.0",
                "category": mapped["category"],
                "type": mapped["type"],
                "platform": "bilibili",
                "room_id": room_id,
                "seq": mapped["seq"],
                "timestamp": mapped["timestamp"],
                "engine": self.engine_id,
                "protocol_version": PROTOCOL_VERSION,
                "payload": mapped["payload"],
            }
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._emit_message(wire))
            except RuntimeError:
                pass
