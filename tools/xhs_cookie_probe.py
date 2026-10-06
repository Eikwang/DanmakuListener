"""小红书登录 cookie 名实证 probe（2026-10-06 用户实测缺口）

弹可见窗口打开小红书直播间页（游客态基线 cookie）→ 用户在页面内登录
→ 抓登录后新增/变化的 cookie → dump 到 tools/xhs_cookie_probe.json。

运行：python tools/xhs_cookie_probe.py --room <直播间id>   （需 attended，弹窗后请在页面内登录）
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.async_api import async_playwright  # noqa: E402

OUT = Path(__file__).parent / "xhs_cookie_probe.json"


async def main(room: str) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"])
        context = await browser.new_context()
        page = await context.new_page()
        url = f"https://www.xiaohongshu.com/livestream/{room}"
        try:
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        except Exception as e:  # noqa: BLE001
            print(f"[probe] goto warning: {e}")
        await asyncio.sleep(3)
        baseline = {c.get("name"): c for c in await context.cookies()}
        print(f"[probe] 游客态基线 {len(baseline)} cookies: {sorted(baseline)}", flush=True)
        print(f"[probe] 请在弹出的直播间页面内登录小红书账号（180 秒窗口）")
        prev = {n: c.get("value") for n, c in baseline.items()}
        t0 = time.monotonic()
        last_cookies = list(baseline.values())
        changed_at = None
        while time.monotonic() - t0 < 300:
            cookies = await context.cookies()
            names = {c.get("name", "") for c in cookies}
            new_names = {n for n in names if n not in baseline}
            changed = {c.get("name") for c in cookies
                       if c.get("name") in baseline
                       and c.get("value") != prev.get(c.get("name"))}
            if new_names or changed:
                print(f"[probe] 变化 @ {time.monotonic()-t0:.0f}s: "
                      f"new={sorted(new_names)} changed={sorted(changed)}", flush=True)
                prev = {c.get("name"): c.get("value") for c in cookies}
                last_cookies = cookies
                changed_at = time.monotonic() - t0
                # 增量落盘（v2）：用户登录完成后无需等进程结束
                OUT.write_text(json.dumps(last_cookies, ensure_ascii=False, indent=2),
                               encoding="utf-8")
                # 登录完成的常见信号：出现 web_session 之外的会话类新 cookie
                # ——继续观察 10s 无新变化则 dump 结束
            await asyncio.sleep(2)
        OUT.write_text(json.dumps(last_cookies, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"\n[probe] final {len(last_cookies)} cookies -> {OUT}")
        base_names = set(baseline)
        added = sorted({c.get("name") for c in last_cookies if c.get("name") not in base_names})
        print(f"[probe] 登录新增 cookie（判定候选）: {added}")
        for c in last_cookies:
            if c.get("name") in added or (c.get("name") in baseline
                                          and c.get("value") != baseline[c.get("name")].get("value")):
                v = str(c.get("value", ""))
                print(f"  {c.get('domain',''):<28} {c.get('name',''):<24} "
                      f"len={len(v)} {'(新增)' if c.get('name') not in base_names else '(值变化)'}")
        try:
            await browser.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--room", required=True)
    asyncio.run(main(**vars(ap.parse_args())))
