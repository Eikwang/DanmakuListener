"""斗鱼登录 cookie 名实证 probe（2026-10-06 用户实测缺口）

弹可见窗口打开 passport.douyu.com，轮询打印 cookie 名集合变化；
用户登录完成后自动 dump 全部 cookies 到 tools/douyu_cookie_probe.json。

运行：python tools/douyu_cookie_probe.py   （需 attended，弹窗后请手动登录）
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.async_api import async_playwright  # noqa: E402

OUT = Path(__file__).parent / "douyu_cookie_probe.json"


async def main() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto("https://passport.douyu.com/", timeout=30000,
                            wait_until="domcontentloaded")
        except Exception as e:  # noqa: BLE001
            print(f"[probe] goto warning: {e}")
        print("[probe] 请在弹出的窗口中登录斗鱼账号（180 秒窗口）")
        baseline = set()
        prev_names = set()
        t0 = time.monotonic()
        last_dump = {}
        while time.monotonic() - t0 < 180:
            try:
                cookies = await context.cookies()
            except Exception as e:  # noqa: BLE001
                print(f"[probe] cookies error: {type(e).__name__}")
                break
            names = {c.get("name", "") for c in cookies}
            new = names - prev_names
            if new:
                print(f"[probe] +{len(new)} cookies @ {time.monotonic()-t0:.0f}s: {sorted(new)}")
                prev_names = names
                last_dump = cookies
            await asyncio.sleep(2)
        if last_dump:
            OUT.write_text(json.dumps(last_dump, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            print(f"[probe] final {len(last_dump)} cookies -> {OUT}")
            for c in last_dump:
                v = str(c.get("value", ""))
                print(f"  {c.get('domain',''):<25} {c.get('name',''):<30} len={len(v)}")
        try:
            await browser.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    asyncio.run(main())
