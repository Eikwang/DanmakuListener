"""淘宝登录闭环 T0 spike 三臂实验（2026-10-06 平台登录计划 T5）

实验目的：淘宝降级会话帧形态未实证——三臂实验结论决定切片 2 重登触发器
分支（taobao.py `RELOGIN_MODE`）。结论请写入 taobao.py 登录段注释。

用法（需 attended 会话，浏览器窗口可见）：

    # 臂 1 + 臂 3（全自动，~1 分钟）：
    python tools/login_spike_taobao.py guest

    # 臂 2（需配合：脚本启动监听后，按提示在手机/网页作废登录会话）：
    python tools/login_spike_taobao.py degrade --live-id <在播直播间 liveId>

任一手段成功即达成 spike（CEO F4）：账号改密踢会话 > 服务端踢下线 >
本地删 token cookie 模拟。

观测输出落 tools/spike_taobao_results.json + 控制台摘要；
结论回填：danmaku_listener/engines/protocol/taobao.py 的 RELOGIN_MODE 与本文件头部。
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from danmaku_listener.engines.protocol.taobao import (  # noqa: E402
    _has_login_cookie,
    UA,
    LIVE_URL_TEMPLATE,
)
from danmaku_listener.engines.protocol.mtop import extract_live_id  # noqa: E402

RESULTS_PATH = Path(__file__).parent / "spike_taobao_results.json"


def _save(results: dict) -> None:
    RESULTS_PATH.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[spike] results saved -> {RESULTS_PATH}")


async def arm1_and_3() -> dict:
    """臂 1（guest 归因）：全新 guest profile 首次提凭证——topic_failed
    到底是登录门还是滑块门。臂 3（游客 unb 存在性）：guest 态 unb 是否存在。"""
    from playwright.async_api import async_playwright

    out = {"arm1_topic_ok": False, "arm1_error": "", "arm3_guest_unb": None,
           "arm3_all_cookies": []}
    tmp_profile = Path(__file__).parent / "_spike_guest_profile"
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            str(tmp_profile), headless=True, user_agent=UA,
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled"])
        try:
            await context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            page = context.pages[0] if context.pages else await context.new_page()
            # 用一个公开在播直播间链接（运行时替换为当前在播 liveId）
            live_id = input("臂 1：输入一个在播淘宝直播间 liveId（页面公开可访问）: ").strip()
            url = LIVE_URL_TEMPLATE.format(live_id=extract_live_id(live_id))
            try:
                await page.goto(url, timeout=30000)
            except Exception as e:  # noqa: BLE001
                print(f"[spike] goto warning: {e}")
            await asyncio.sleep(45)  # 与引擎 wait_limit=45s 对齐
            cookies = await context.cookies()
            out["arm3_all_cookies"] = sorted({c.get("name", "") for c in cookies})
            out["arm3_guest_unb"] = _has_login_cookie(cookies)
            topic = await page.evaluate(
                "window.__spike_topic || null")  # 事件捕获不在本脚本——观测控制台
            out["arm1_topic_ok"] = bool(topic)
            out["arm1_note"] = (
                "arm1_topic_ok 依赖页内捕获；若为 False，请结合控制台日志判断 "
                "topic_failed 归因：出现滑块/验证页=滑块门；页面正常但接口空=登录门。")
            screenshot = Path(__file__).parent / "_spike_arm1.png"
            await page.screenshot(path=str(screenshot))
            out["arm1_screenshot"] = str(screenshot)
            print(f"[spike] 臂 1 截图（判断滑块门/登录门）: {screenshot}")
        finally:
            await context.close()
    return out


async def arm2(live_id: str) -> dict:
    """臂 2（降级帧形态）：登录态监听中作废会话——观测帧类停推/存活、
    统计帧行为、status==3 是否推送；增补观测（Eng F5）：死会话+冷清房间。"""
    from danmaku_listener.engines.protocol.taobao import TaobaoWebProtocolEngine

    eng = TaobaoWebProtocolEngine()
    seen = {"danmu": 0, "gift": 0, "enter": 0, "stats": 0, "like": 0, "control": 0}
    orig_emit = eng._emit_message

    async def counting_emit(msg):
        try:
            t = msg.get("type") if isinstance(msg, dict) else None
            mapping = {"DANMU": "danmu", "GIFT": "gift", "ENTER_ROOM": "enter",
                       "ROOM_STATS": "stats", "LIKE": "like",
                       "LIVE_STATUS_CHANGE": "control"}
            if t in mapping:
                seen[mapping[t]] += 1
        except Exception:
            pass
        return await orig_emit(msg)

    eng._emit_message = counting_emit
    print("[spike] 臂 2：开始监听（登录态 profile）。等待 60s 基线后，")
    print("        请立即在手机/网页作废该账号登录会话（改密/踢下线），然后回到这里。")
    task = asyncio.create_task(eng._run_room(live_id))
    await asyncio.sleep(60)
    baseline = dict(seen)
    print(f"[spike] 基线 60s: {baseline}\n[spike] 现在请作废登录会话，然后等待 180s 观测…")
    await asyncio.sleep(180)
    after = {k: seen[k] - baseline[k] for k in seen}
    print(f"[spike] 作废后 180s: {after}")
    await eng.stop(live_id)
    verdict = {
        "arm2_baseline_60s": baseline,
        "arm2_after_180s": after,
        "arm2_enter_alive": after["enter"] > 0,
        "arm2_stats_alive": after["stats"] > 0,
        "arm2_business_stopped": after["danmu"] == 0 and after["gift"] == 0,
        "arm2_note": "enter_alive=True 且 business_stopped=True → RELOGIN_MODE='enter_alive'；"
                     "全 0 → 需重验（可能下播）→ RELOGIN_MODE='all_stopped'。",
    }
    return verdict


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arm", choices=["guest", "degrade"])
    parser.add_argument("--live-id", default="")
    args = parser.parse_args()

    results = {}
    if args.arm == "guest":
        results = asyncio.run(arm1_and_3())
    else:
        if not args.live_id:
            sys.exit("臂 2 需要 --live-id <在播直播间 liveId>")
        results = asyncio.run(arm2(extract_live_id(args.live_id)))
    _save(results)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
