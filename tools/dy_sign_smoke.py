# -*- coding: utf-8 -*-
"""抖音 Web WS 直连冒烟脚本（计划 T0 门禁：真实活跃房间抓 ChatMessage>=3）

用法：
    python tools/dy_sign_smoke.py <web_rid> [--duration 45]

来源：/autoplan 端到端原型（2026-09-28 实测打通）——签名资产 provenance 见
docs/plans/douyin-native-websocket-plan.md 与 danmaku_listener/engines/protocol/
douyin_assets/ 内资产头注释。
"""

import argparse
import asyncio
import gzip
import json
import hashlib
import random
import re
import sys
import time
from urllib.parse import urlencode

sys.path.insert(0, ".")

import quickjs
import requests
import websockets

import danmaku_listener.engines.protocol.douyin_assets.douyin_pb2 as dy_pb2

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

WEB_SOCKET_URIS = [
    "wss://webcast5-ws-web-lq.douyin.com/webcast/im/push/v2/",
    "wss://webcast5-ws-web-lf.douyin.com/webcast/im/push/v2/",
    "wss://webcast5-ws-web-hl.douyin.com/webcast/im/push/v2/",
]

_JS_PATH = "danmaku_listener/engines/protocol/douyin_assets/douyin-webmssdk.js"
_ctx = None


def get_sign(user_agent: str, room_id: str, user_unique_id: str) -> str:
    """签名（quickjs 引擎级单例；仅 loop 线程调用——线程模型见计划 Eng H1）"""
    global _ctx
    if _ctx is None:
        with open(_JS_PATH, encoding="utf-8") as fh:
            js = fh.read()
        env = ' document = {};\nwindow = {};\nnavigator = {\nuserAgent: "%s"\n};\n' % user_agent
        t0 = time.perf_counter()
        _ctx = quickjs.Context()
        _ctx.eval(env + js)
        print(f"[sign] webmssdk eval {time.perf_counter() - t0:.3f}s")
    param = ("live_id=1,aid=6383,version_code=180800,webcast_sdk_version=1.0.14-beta.0,"
             f"room_id={room_id},sub_room_id=,sub_channel_id=,did_rule=3,"
             f"user_unique_id={user_unique_id},device_platform=web,device_type=,ac=,"
             "identity=audience")
    return _ctx.get("get_sign")(hashlib.md5(param.encode()).hexdigest())


def room_init(rid: str):
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": "https://live.douyin.com/"})
    s.get("https://live.douyin.com/", timeout=10)
    ttwid = s.cookies.get("ttwid", "")
    if not ttwid:
        raise RuntimeError("ttwid 获取失败（douyin.room_init.ttwid_failed）")
    ms_token = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789=_", k=116))
    r = s.get(f"https://live.douyin.com/{rid}", timeout=10,
              cookies={"ttwid": ttwid, "msToken": ms_token})
    body = r.text
    uid = (re.search(r'\\"user_unique_id\\":\\"(\d+)\\"', body) or [None, ""])[1]
    real_room = (re.search(r'\\"roomId\\":\\"(\d+)\\"', body) or [None, ""])[1]
    status = (re.search(r'\\"status_str\\":\\"(\d+)\\"', body) or [None, "0"])[1]
    if not real_room or not uid:
        raise RuntimeError(f"房间页解析失败（douyin.room_init.parse_failed）status={status}")
    if status != "2":
        raise RuntimeError(f"房间未开播（douyin.room_init.not_live）status={status}")
    return ttwid, ms_token, real_room, uid


async def main(rid: str, duration: float, dump_all: bool = False) -> int:
    dump_fh = open("douyin_dump.jsonl", "a", encoding="utf-8") if dump_all else None
    n_dump = 0
    ttwid, ms_token, real_room, uid = room_init(rid)
    print(f"real_room={real_room} uid={uid[:14]}...")
    sig = get_sign(UA, real_room, uid)
    qp = [
        ("app_name", "douyin_web"), ("version_code", "180800"),
        ("webcast_sdk_version", "1.0.14-beta.0"), ("update_version_code", "1.0.14-beta.0"),
        ("compress", "gzip"), ("device_platform", "web"), ("cookie_enabled", "true"),
        ("screen_width", "1280"), ("screen_height", "800"), ("browser_language", "zh-CN"),
        ("browser_platform", "Win32"), ("browser_name", "Mozilla"),
        ("browser_version", UA.replace("Mozilla/", "")), ("browser_online", "true"),
        ("tz_name", "Asia/Shanghai"),
        ("cursor", f"t-{int(time.time()*1000)}_r-1_d-1_u-1_fh-743192{random.randint(10**12, 10**13-1)}"),
        ("internal_ext", "internal_src:dim|wss_push_room_id:" + real_room + "|wss_push_did:" + uid +
         "|first_req_ms:" + str(int(time.time()*1000)) + "|fetch_time:" + str(int(time.time()*1000)) +
         "|seq:1|wss_info:0-" + str(int(time.time()*1000)) + "-0-0|wrds_v:743192" +
         "".join(random.choices("0123456789", k=13))),
        ("host", "https://live.douyin.com"), ("aid", "6383"), ("live_id", "1"),
        ("did_rule", "3"), ("endpoint", "live_pc"), ("support_wrds", "1"),
        ("user_unique_id", uid), ("im_path", "/webcast/im/fetch/"), ("identity", "audience"),
        ("need_persist_msg_count", "15"), ("insert_task_id", ""), ("live_reason", ""),
        ("room_id", real_room), ("heartbeatDuration ", "0"),
        ("signature", sig), ("web_rid", rid), ("msToken", ms_token),
    ]
    url = WEB_SOCKET_URIS[0] + "?" + urlencode(qp)
    headers = {"User-Agent": UA,
               "Cookie": f"ttwid={ttwid}; msToken={ms_token}",
               "Origin": "https://live.douyin.com"}

    chat = 0
    n = 0
    async with websockets.connect(url, additional_headers=headers, ping_interval=None) as ws:
        print("WS CONNECTED")
        hb = bytes([58, 2, 104, 98])
        last_hb = time.monotonic()
        end = time.monotonic() + duration
        while time.monotonic() < end:
            try:
                raw = await asyncio.wait_for(ws.recv(), max(0.5, end - time.monotonic()))
            except asyncio.TimeoutError:
                continue
            data = raw if isinstance(raw, bytes) else raw.encode()
            frame = dy_pb2.PushFrame()
            frame.ParseFromString(data)
            if frame.payloadType == "hb":
                continue
            payload = frame.payload
            for h in frame.headersList:
                if h.key == "compress_type" and h.value == "gzip":
                    payload = gzip.decompress(frame.payload)
            resp = dy_pb2.Response()
            resp.ParseFromString(payload)
            if resp.needAck:
                ack = dy_pb2.PushFrame()
                ack.logId = frame.logId
                ack.payloadType = "ack"
                ack.payload = resp.internalExt.encode() if isinstance(resp.internalExt, str) else resp.internalExt
                await ws.send(ack.SerializeToString())
            for msg in resp.messagesList:
                n += 1
                if msg.method == "WebcastChatMessage":
                    c = dy_pb2.ChatMessage()
                    c.ParseFromString(msg.payload)
                    chat += 1
                    print(f"[弹幕{chat}] {c.user.nickName}: {c.content[:30]}")
                    if dump_fh:
                        import base64 as _b64
                        dump_fh.write(json.dumps(
                            {"ts": time.time(), "kind": "raw",
                             "data": {"method": msg.method,
                                      "nick": c.user.nickName,
                                      "content": c.content,
                                      "user_id": c.user.id,
                                      "msg_id": getattr(c, "msgId", None),
                                      "payload_b64": _b64.b64encode(msg.payload).decode()}},
                            ensure_ascii=False, default=str) + "\n")
                        dump_fh.flush()
                        n_dump += 1
                elif msg.method == "WebcastGiftMessage":
                    g = dy_pb2.GiftMessage()
                    g.ParseFromString(msg.payload)
                    print(f"[礼物] {g.user.nickName}: {g.gift.name}")
                    if dump_fh:
                        import base64 as _b64
                        dump_fh.write(json.dumps(
                            {"ts": time.time(), "kind": "raw",
                             "data": {"method": msg.method,
                                      "nick": g.user.nickName,
                                      "gift_name": g.gift.name,
                                      "gift_id": g.gift.id,
                                      "count": g.comboCount,
                                      "payload_b64": _b64.b64encode(msg.payload).decode()}},
                            ensure_ascii=False, default=str) + "\n")
                        dump_fh.flush()
                        n_dump += 1
                elif time.monotonic() - last_hb > 10:
                    pass
            if time.monotonic() - last_hb > 10:
                await ws.send(hb)
                last_hb = time.monotonic()
    if dump_fh:
        dump_fh.close()
    print(f"total={n} chat={chat} dump={n_dump} -> "
          f"{'PASS' if chat >= 3 else 'BELOW_GATE'}")
    return 0 if chat >= 3 else 4


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("web_rid")
    p.add_argument("--duration", type=float, default=45.0)
    p.add_argument("--dump-all", action="store_true",
                   help="弹幕/礼物 protobuf 关键字段+payload 写 douyin_dump.jsonl")
    a = p.parse_args()
    sys.exit(asyncio.run(main(a.web_rid, a.duration, a.dump_all)))
