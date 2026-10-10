"""虎牙聊天区 DOM 结构取证探针（2026-10-10——输入配方失效诊断 b 支路）

背景：用户 devtools 实测输入面 = #J_RoomChatSpeaker > div > div，引擎按同款
选择器打字后回读为空（audit: 提交前输入=''）。本探针在我们自己的浏览器里
dump 聊天区真实 DOM，逐选择器列出全部匹配（含可见性/几何信息），与用户
devtools 对照——判定"选择器命中错元素"还是"我方 DOM 与用户所见不一致"。

一次性 profile + 真实登录快照注入（用户 2026-10-10 takeover 登录产物）。
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from danmaku_listener.senders.huya import INPUT_SELECTORS, STEALTH_JS  # noqa: E402

PROFILE = r"C:\Users\admin\.claude\jobs\e8b5122b\tmp\huya_dom_probe"
SNAPSHOT = Path("cookie/huya_login_profile_login_state.json")
CARDS_DIR = Path(__file__).resolve().parent / "cards"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

DUMP_JS = """
() => {
  const out = {speaker_exists: false, candidates: [], editables: [], placeholders: []};
  const sp = document.querySelector('#J_RoomChatSpeaker');
  if (sp) {
    out.speaker_exists = true;
    out.speaker_html = sp.outerHTML.slice(0, 2500);
  }
  const sel = (s) => Array.from(document.querySelectorAll(s));
  for (const s of ['#J_RoomChatSpeaker > div > div', '#pub_msg_input',
                   '#msg_send_bt', 'textarea', 'div[contenteditable=true]',
                   'input[placeholder*=弹幕]', 'input[placeholder*=说]']) {
    out.candidates.push({
      sel: s, count: sel(s).length,
      info: sel(s).slice(0, 4).map(el => ({
        tag: el.tagName, cls: (el.className || '').toString().slice(0, 60),
        visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
        rect: (() => { const r = el.getBoundingClientRect();
                       return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; })(),
        placeholder: el.getAttribute && el.getAttribute('placeholder'),
        text: (el.innerText || '').slice(0, 40),
      })),
    });
  }
  for (const el of sel('#J_RoomChatSpeaker [contenteditable=true]')) {
    out.editables.push({cls: (el.className || '').toString().slice(0, 60),
                        text: (el.innerText || '').slice(0, 40)});
  }
  for (const el of sel('input[placeholder], div[placeholder], textarea[placeholder]')) {
    const p = el.getAttribute('placeholder');
    if (p) out.placeholders.push({tag: el.tagName, ph: p.slice(0, 30),
      visible: !!(el.offsetWidth || el.offsetHeight)});
  }
  return out;
}
"""


async def main() -> None:
    room = sys.argv[1] if len(sys.argv) > 1 else "152746"
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            PROFILE, headless=False, user_agent=UA,
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled",
                  "--disable-setuid-sandbox", "--hide-crash-restore-bubble",
                  "--headless=new", "--mute-audio"])
        try:
            await ctx.add_init_script(f"({STEALTH_JS})()")
            if SNAPSHOT.is_file():
                state = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
                await ctx.add_cookies(state.get("cookies", []))
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto(f"https://www.huya.com/{room}",
                            timeout=45000, wait_until="domcontentloaded")
            await asyncio.sleep(8)
            card = {"room": room, "title": await page.title(),
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
            card.update(await page.evaluate(DUMP_JS))
            out = CARDS_DIR / f"huya-dom-{time.strftime('%Y%m%d-%H%M%S')}.json"
            out.write_text(json.dumps(card, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            print(f"卡片: {out}")
            print(json.dumps({k: v for k, v in card.items()
                              if k != "speaker_html"}, ensure_ascii=False)[:1800])
            print("speaker_html 前 1200 字:")
            print(card.get("speaker_html", "(#J_RoomChatSpeaker 不存在)")[:1200])
        finally:
            try:
                await ctx.close()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    asyncio.run(main())
