"""抖音开工前双探针（CEO-F5，2026-10-07 批准计划 T3 前置）

探针① --headless=new：Chromium 新无头模式（完整 Blink 渲染、指纹弱于旧无头）
  下 bd_ticket_guard 会话是否渲染聊天面板——若出现，常驻有头窗口方案降级为备选。
探针② CDP-attach：连接真实 Chrome（--remote-debugging-port）可行性——ENG-16：
  仅作可行性记录，进入实施前需单独小评审，不默认自动切换。

纪律：douyin_profile 真实环境（R17）；卡片落 cards/。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import COMMON_UA, launch_args, print_card, save_card  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
PROFILE = ROOT / "cookie" / "douyin_profile"
INPUT_SEL = "div[contenteditable=true]"


async def probe_headless_new(room_url: str) -> dict:
    """探针①：--headless=new 下聊天面板是否出现"""
    from playwright.async_api import async_playwright

    out: dict = {"mode": "headless=new", "input_found": False, "notes": []}
    async with async_playwright() as pw:
        # 新无头：headless=False + --headless=new flag（Chromium 自己解析；兼容各 playwright 版本）
        context = await pw.chromium.launch_persistent_context(
            str(PROFILE), headless=False,
            user_agent=COMMON_UA, viewport={"width": 1280, "height": 800},
            args=launch_args() + ["--headless=new"])
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                await page.goto(room_url, timeout=45000, wait_until="domcontentloaded")
            except Exception as e:  # noqa: BLE001
                out["notes"].append(f"goto: {type(e).__name__}")
            for wait in (5, 5, 5):  # 三轮共 15s 等渲染
                await asyncio.sleep(wait)
                try:
                    loc = page.locator(INPUT_SEL).first
                    if await loc.count() > 0 and await loc.is_visible():
                        out["input_found"] = True
                        out["notes"].append(f"聊天面板在第 {wait*3//5} 轮可见")
                        break
                except Exception as e:  # noqa: BLE001
                    out["notes"].append(f"probe: {type(e).__name__}")
            try:
                out["title"] = await page.title()
                vis = await page.evaluate("document.visibilityState")
                out["visibilityState"] = vis
            except Exception as e:  # noqa: BLE001
                out["notes"].append(f"eval: {type(e).__name__}")
        finally:
            try:
                await context.close()
            except Exception:  # noqa: BLE001
                pass
    return out


async def probe_cdp(port: int = 9222, timeout_s: float = 5.0) -> dict:
    """探针②：CDP-attach 可行性记录（ENG-16——不默认切换）"""
    import requests as _rq

    out: dict = {"mode": "cdp-attach", "reachable": False, "notes": []}
    try:
        resp = _rq.get(f"http://127.0.0.1:{port}/json/version", timeout=timeout_s)
        info = resp.json()
        out["reachable"] = True
        out["browser"] = info.get("Browser", "unknown")
        tabs = _rq.get(f"http://127.0.0.1:{port}/json", timeout=timeout_s).json()
        out["pages"] = len(tabs)
        out["notes"].append("调试端点可达——实施需单独小评审（profile 冲突/安全面评估，ENG-16）")
    except Exception as e:  # noqa: BLE001
        out["notes"].append(f"端点不可达（{type(e).__name__}）——用户 Chrome 未以 --remote-debugging-port 启动；"
                            "可行性=依赖用户配合启动参数，运维成本高于常驻会话")
    return out


async def main() -> None:
    ap = argparse.ArgumentParser(description="抖音开工前双探针（CEO-F5）")
    ap.add_argument("--room-url", required=True, help="开播中的抖音直播间 URL")
    ap.add_argument("--cdp-port", type=int, default=9222, help="CDP 调试端口（探针②）")
    args = ap.parse_args()

    card: dict = {
        "platform": "douyin", "probe": "CEO-F5 双探针",
        "room_url": args.room_url, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "headless_new": None, "cdp_attach": None, "verdict": None,
    }
    print("探针①：--headless=new 模式（douyin_profile）...")
    card["headless_new"] = await probe_headless_new(args.room_url)
    print(f"  input_found={card['headless_new']['input_found']} "
          f"visibility={card['headless_new'].get('visibilityState')}")
    print("探针②：CDP-attach 可行性...")
    card["cdp_attach"] = await probe_cdp(args.cdp_port)
    print(f"  reachable={card['cdp_attach']['reachable']}")

    if card["headless_new"]["input_found"]:
        card["verdict"] = ("GO_HEADLESS_NEW——新无头模式聊天面板出现：常驻有头窗口方案降级为备选，"
                           "常驻会话可用 headless=new 形态（无桌面要求）")
    else:
        card["verdict"] = ("CONFIRM_HEADED——新无头仍不渲染聊天面板（bd_ticket_guard 会话级判定坐实）："
                           "常驻有头窗口方案确认为唯一路线")
    path = save_card("douyin-ceo-f5-probe", card)
    print_card("douyin-ceo-f5-probe", card)
    print(f"  卡片: {path}")


if __name__ == "__main__":
    asyncio.run(main())
