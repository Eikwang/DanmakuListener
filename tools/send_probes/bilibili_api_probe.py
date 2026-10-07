"""M0 B站 API 发送探针（计划 T2——API 路线，可行性「高」的终判）

两段式：
1. auth 预检（离线可跑，不需要直播中）：读 bilibili_storage_state.json → SESSDATA+bili_jct
   → GET api.bilibili.com/x/web-interface/nav 验证登录态 + GET room API 验证房间参数
2. 实发探针（需直播中）：POST api.live.bilibili.com/msg/send（roomid, content, csrf）

成功判定（F5）：HTTP 200 且 code==0；code==-101 登录失效；code==10030 房间未开播/不可发；
其他 code 按体字段记录（msg 即平台原因）。

运行：
  python tools/send_probes/bilibili_api_probe.py --check                      # 仅 auth 预检（离线）
  python tools/send_probes/bilibili_api_probe.py --room-id 23058 --sends 2    # 实发（需直播中）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import aiohttp  # noqa: E402

from common import (ROOT, marker_content, paced_sends,  # noqa: E402
                    print_card, save_card, verdict_summary)

STATE = ROOT / "cookie" / "bilibili_storage_state.json"
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
SEND_URL = "https://api.live.bilibili.com/msg/send"
ROOM_URL = "https://api.live.bilibili.com/room/v1/Room/get_info"


def load_bili_cookies() -> tuple[dict[str, str], str | None, str | None]:
    """从 storage_state 提取 cookie 对 + SESSDATA + bili_jct（复用三格式解析语义）"""
    raw = json.loads(STATE.read_text(encoding="utf-8"))
    items = raw.get("cookies", []) if isinstance(raw, dict) else raw
    pairs: dict[str, str] = {}
    for c in items:
        if c.get("name") and c.get("value"):
            pairs[c["name"]] = c["value"]
    return pairs, pairs.get("SESSDATA"), pairs.get("bili_jct")


async def auth_check() -> dict:
    """nav API 登录态预检（离线段）"""
    pairs, sessdata, jct = load_bili_cookies()
    out: dict = {"cookies_total": len(pairs), "sessdata": bool(sessdata), "bili_jct": bool(jct)}
    if not (sessdata and jct):
        out["verdict"] = "NEEDS_LOGIN"; return out
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
               "Referer": "https://live.bilibili.com/"}
    async with aiohttp.ClientSession(headers=headers) as http:
        async with http.get(NAV_URL, cookies={"SESSDATA": sessdata, "bili_jct": jct}) as resp:
            text = await resp.text()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            out["verdict"] = "UNKNOWN（非 JSON 响应——风控或网络；前 80 字符: " + text[:80] + "）"
            return out
    out["nav_code"] = data.get("code")
    if data.get("code") == 0:
        d = data.get("data", {})
        out["uname"] = d.get("uname"); out["level"] = d.get("level")
        out["verdict"] = "OK"
    elif data.get("code") == -101:
        out["verdict"] = "NEEDS_LOGIN（cookie 过期）"
    else:
        out["verdict"] = f"UNKNOWN code={data.get('code')}"
    return out


async def send_probe(room_id: int, sends: int) -> dict:
    """实发探针（需直播中）"""
    pairs, sessdata, jct = load_bili_cookies()
    card: dict = {"platform": "bilibili", "route": "API（msg/send）", "room_id": room_id,
                  "sends": [], "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    cookies = {"SESSDATA": sessdata, "bili_jct": jct}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
               "Referer": f"https://live.bilibili.com/{room_id}"}
    async with aiohttp.ClientSession(headers=headers) as http:
        async with http.get(ROOM_URL, params={"room_id": room_id}, cookies=cookies) as resp:
            info = await resp.json(content_type=None)
        card["room_info"] = {"code": info.get("code"), "live_status": (info.get("data") or {}).get("live_status")}
        if (info.get("data") or {}).get("live_status") != 1:
            card["blocked_reason"] = f"房间未开播（live_status={ (info.get('data') or {}).get('live_status') }）——开播后再探"
            return card
        for i, gap in enumerate(await paced_sends(sends), 1):
            if i > 1:
                await asyncio.sleep(gap)
            marker = marker_content(i)
            form = {"bubble": 0, "msg": marker, "color": 16777215, "mode": 1,
                    "fontsize": 25, "rnd": str(int(time.time() * 1e6)), "roomid": room_id, "csrf": jct, "csrf_token": jct}
            async with http.post(SEND_URL, data=form, cookies=cookies) as resp:
                data = await resp.json(content_type=None)
            code = data.get("code")
            verdict = "SUCCESS" if code == 0 else ("FAIL" if code in (-101, 10030) else "UNKNOWN")
            card["sends"].append({"seq": i, "marker": marker, "http": resp.status,
                                  "code": code, "msg": (data.get("message") or "")[:80], "verdict": verdict})
            print(f"  [bilibili #{i}] {verdict} code={code} {(data.get('message') or '')[:60]}")
    card["verdicts_summary"] = verdict_summary(card["sends"])
    return card


def main() -> None:
    ap = argparse.ArgumentParser(description="M0 B站 API 发送探针")
    ap.add_argument("--check", action="store_true", help="仅 auth 预检（离线）")
    ap.add_argument("--room-id", type=int, help="直播间房间号（实发需直播中）")
    ap.add_argument("--sends", type=int, default=2)
    args = ap.parse_args()
    card = asyncio.run(auth_check())
    print("auth 预检:", json.dumps(card, ensure_ascii=False))
    if not args.check:
        if not args.room_id:
            print("实发需 --room-id"); return
        if card.get("verdict") != "OK":
            print("auth 预检未通过——先处理登录态"); return
        send_card = asyncio.run(send_probe(args.room_id, args.sends))
        path = save_card("bilibili", send_card)
        print_card("bilibili", send_card)
        print(f"  card: {path}")


if __name__ == "__main__":
    main()
