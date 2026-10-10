"""虎牙后台无感发送探针（2026-10-10——XHS 修复经验移植验证）

背景：huya_login_profile 目录从未存在（发送侧登录从未落盘），用户登录凭证
在监听侧 cookie 文件（yyuid 持久至 2026-10-24——"会话级 cookie"结论同样
被磁盘证据推翻）。本探针验证三件事：
1. 监听侧 yyuid 凭证注入发送 profile 后虎牙是否认可登录态
2. headless=new + STEALTH_JS（7 信号伪装，2026-10-09 备而未接线）能否过
   虎牙风控（10-09 回退结论"headless 被吞"的混杂因素复查）
3. 虎牙同款配方（#pub_msg_input + #msg_send_bt + 节点重建感知回显）在
   后台形态下的回显判定

纪律：一次性 profile（运行中的服务 profile 空闲但避免污染）；卡片输出
cards/huya-bg-<ts>.json。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from danmaku_listener.senders.huya import (  # noqa: E402
    BUTTON_SELECTORS,
    INPUT_SELECTORS,
    STEALTH_JS,
)

PROFILE = r"C:\Users\admin\.claude\jobs\e8b5122b\tmp\huya_probe_bg_profile"
COOKIES_FILE = Path("cookie/huya_login_cookies.json")
CARDS_DIR = Path(__file__).resolve().parent / "cards"
LOGIN_NAMES = ("yyuid", "hicl_imid", "huya_uid")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--room", default="152746")
    ap.add_argument("--content", default=None)
    args = ap.parse_args()
    content = args.content or f"[M0] huya-bg {time.strftime('%H%M%S')}"
    card: dict = {"probe": "huya_bg_send", "room": args.room,
                  "mode": "headless_new+stealth", "ts": time.strftime("%Y-%m-%d %H:%M:%S")}

    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            PROFILE, headless=False, user_agent=UA,
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled",
                  "--disable-setuid-sandbox", "--hide-crash-restore-bubble",
                  "--headless=new", "--mute-audio"])
        try:
            await ctx.add_init_script(f"({STEALTH_JS})()")
            state = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
            cookies = state.get("cookies", state if isinstance(state, list) else [])
            await ctx.add_cookies(cookies)
            card["injected_cookies"] = len(cookies)

            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto(f"https://www.huya.com/{args.room}",
                            timeout=45000, wait_until="domcontentloaded")
            await asyncio.sleep(5)
            cookies_now = {c["name"] for c in await ctx.cookies() if c.get("value")}
            try:
                mask_loc = page.locator("#UDBSdkLgn-mask")
                mask = (await mask_loc.count() > 0
                        and await mask_loc.first.is_visible())
            except Exception:  # noqa: BLE001
                mask = -1
            card["login"] = {"names_hit": sorted(set(LOGIN_NAMES) & cookies_now),
                             "udb_mask": mask,
                             "logged": bool(set(LOGIN_NAMES) & cookies_now) and mask == 0,
                             "title": await page.title()}
            inp = None
            for sel in INPUT_SELECTORS:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        inp = loc
                        break
                except Exception:  # noqa: BLE001
                    continue
            if inp is None:
                card["send"] = "NO_INPUT（未登录/未开播/页面变更）"
                card["screenshot"] = str(await _shot(page, "noinput"))
                return
            await inp.click(timeout=10_000)
            await asyncio.sleep(0.4)
            await inp.press_sequentially(content, delay=40)
            await asyncio.sleep(0.3)
            btn = None
            for sel in BUTTON_SELECTORS:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        btn = loc
                        break
                except Exception:  # noqa: BLE001
                    continue
            try:
                if btn is not None:
                    await btn.click(timeout=5_000)
                else:
                    await inp.press("Enter")
            except Exception:  # noqa: BLE001
                await inp.press("Enter")
            await asyncio.sleep(1)
            post_input = None
            try:
                ta = page.locator("#pub_msg_input").first
                if await ta.count() > 0:
                    post_input = (await ta.input_value()).strip()
            except Exception:  # noqa: BLE001
                post_input = None
            card["post_submit"] = {"input_value": post_input,
                                   "cleared": post_input == ""}
            deadline = time.monotonic() + 12
            hit = False
            hit_src = None
            while time.monotonic() < deadline:
                try:
                    if await page.get_by_text(content).count() > 0:
                        hit, hit_src = True, "get_by_text"
                        break
                    aside = await page.evaluate(
                        "() => { const a = document.querySelector('#js-player-asideMain');"
                        " return a ? a.innerText : ''; }")
                    if content in (aside or ""):
                        i = (aside or "").find(content)
                        hit, hit_src = True, f"aside:...{(aside or '')[max(0,i-40):i+len(content)+20]}..."
                        break
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(1.5)
            card["send"] = {"content": content,
                            "verdict": f"SENT(回显 src={hit_src})" if hit else "无回显"}
            card["screenshot"] = str(await _shot(page, "send"))
        finally:
            try:
                await ctx.close()
            except Exception:  # noqa: BLE001
                pass
    out = CARDS_DIR / f"huya-bg-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(card, ensure_ascii=False, indent=2))
    print(f"卡片: {out}")


async def _shot(page, tag: str) -> str:
    p = CARDS_DIR / f"huya-bg-{tag}-{time.strftime('%H%M%S')}.png"
    try:
        await page.screenshot(path=str(p), full_page=False)
    except Exception:  # noqa: BLE001
        return ""
    return str(p)


if __name__ == "__main__":
    asyncio.run(main())
