"""京东直播间 DOM 结构取证探针（2026-10-10——发送平台拒绝诊断）

背景：jd 发送审计 3 条全败（busy×1/未发现输入框×1/限速×1）；jd_profile 此前
不存在（无登录）；京东仍走基类旧发送流（headless 瞬态+通用选择器）。本探针
在房间 48511841 上取证：聊天输入面真实结构（含 iframe 枚举——page.locator
不穿 iframe）、登录态、回显容器候选。
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

CARDS_DIR = Path(__file__).resolve().parent / "cards"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

SCAN_JS = """
() => {
  const out = {inputs: [], editables: [], sendButtons: [], frames: []};
  const vis = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const rect = (el) => { const r = el.getBoundingClientRect();
    return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; };
  for (const el of document.querySelectorAll('textarea, input[type=text], input:not([type])')) {
    out.inputs.push({tag: el.tagName, id: el.id, cls: (el.className||'').toString().slice(0,60),
      ph: (el.getAttribute('placeholder')||''), visible: vis(el), rect: rect(el)});
  }
  for (const el of document.querySelectorAll('[contenteditable=true]')) {
    out.editables.push({tag: el.tagName, id: el.id, cls: (el.className||'').toString().slice(0,60),
      visible: vis(el), rect: rect(el)});
  }
  for (const el of document.querySelectorAll('button, [class*=send], [class*=Send]')) {
    const t = (el.innerText || '').trim();
    if (t.includes('发送') || (el.className||'').toString().match(/send/i)) {
      out.sendButtons.push({tag: el.tagName, id: el.id, cls: (el.className||'').toString().slice(0,60),
        text: t.slice(0,20), visible: vis(el), rect: rect(el)});
    }
  }
  return out;
}
"""


async def main() -> None:
    room = sys.argv[1] if len(sys.argv) > 1 else "48511841"
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            r"C:\Users\admin\.claude\jobs\e8b5122b\tmp\jd_dom_probe",
            headless=False, user_agent=UA,
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled",
                  "--disable-setuid-sandbox", "--hide-crash-restore-bubble",
                  "--headless=new", "--mute-audio"])
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto(f"https://zhibo.jd.com/liveroom?liveId={room}",
                            timeout=45000, wait_until="domcontentloaded")
            await asyncio.sleep(10)
            cookies = {c["name"] for c in await ctx.cookies() if c.get("value")}
            card = {"room": room, "title": await page.title(),
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "login_cookies": sorted(n for n in cookies
                                            if n in ("pt_key", "pt_pin")),
                    "main_frame": await page.evaluate(SCAN_JS),
                    "frames": []}
            # iframe 枚举：输入面常嵌子帧（page.locator 不穿 iframe）
            for f in page.frames:
                if f == page.main_frame:
                    continue
                try:
                    hit = await f.evaluate(SCAN_JS)
                    if hit["inputs"] or hit["editables"] or hit["sendButtons"]:
                        card["frames"].append({"url": f.url[:100], **hit})
                except Exception as e:  # noqa: BLE001  跨域/about 帧
                    card["frames"].append({"url": f.url[:80],
                                           "error": f"{type(e).__name__}"})
            out = CARDS_DIR / f"jd-dom-{time.strftime('%Y%m%d-%H%M%S')}.json"
            out.write_text(json.dumps(card, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            print(f"卡片: {out}")
            print(json.dumps(card, ensure_ascii=False)[:2200])
            shot = CARDS_DIR / f"jd-dom-{time.strftime('%H%M%S')}.png"
            await page.screenshot(path=str(shot))
            print(f"截图: {shot}")
        finally:
            try:
                await ctx.close()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    asyncio.run(main())
