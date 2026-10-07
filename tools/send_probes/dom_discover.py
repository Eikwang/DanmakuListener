"""DOM 发现模式探针（M0 校准工具——dump 全部输入/按钮候选供选择器定稿）

用途：发送钩子发现到错误输入框（如搜索框）时，跑本工具枚举页面真实
聊天输入候选（含 iframe 与属性），校准平台 SEND_INPUT_SELECTORS。

运行：
  python tools/send_probes/dom_discover.py --platform taobao --room-url "<直播间URL>"
输出：候选清单（stdout）+ 截图 cards/<platform>-discover.png
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.async_api import async_playwright  # noqa: E402

from common import CARDS_DIR, DOM_PLATFORMS, ROOT, common_precheck, launch_args  # noqa: E402

JS_ENUM = """
() => {
  const out = {inputs: [], buttons: [], frames: []};
  const scan = (doc, tag) => {
    doc.querySelectorAll("textarea, input[type=text], input:not([type]), div[contenteditable=true], [contenteditable]").forEach(el => {
      const r = el.getBoundingClientRect();
      out.inputs.push({
        frame: tag,
        tag: el.tagName.toLowerCase(),
        placeholder: el.getAttribute("placeholder") || "",
        cls: (el.className || "").toString().slice(0, 80),
        id: el.id || "",
        visible: r.width > 0 && r.height > 0,
        rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
      });
    });
    doc.querySelectorAll("button, [role=button], .btn, [class*=send], [class*=Send]").forEach(el => {
      const r = el.getBoundingClientRect();
      const text = (el.textContent || "").trim().slice(0, 20);
      if (!text && !(el.className || "").toString()) return;
      out.buttons.push({
        frame: tag,
        tag: el.tagName.toLowerCase(),
        text: text,
        cls: (el.className || "").toString().slice(0, 80),
        visible: r.width > 0 && r.height > 0,
        rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
      });
    });
  };
  scan(document, "main");
  document.querySelectorAll("iframe").forEach((f, i) => {
    try { if (f.contentDocument) scan(f.contentDocument, "iframe-" + i); } catch (e) {}
    out.frames.push({i: i, src: (f.src || "").slice(0, 100)});
  });
  return out;
}
"""


async def run(args: argparse.Namespace) -> None:
    pre = common_precheck(args.platform)
    if not pre["ok"]:
        print(pre["error"] if "error" in pre else pre.get("reason")); return
    cfg = pre["config"]
    profile = cfg.get("profile")
    profile_dir = ROOT / "cookie" / profile if profile else None

    async with async_playwright() as pw:
        if profile_dir and profile_dir.is_dir():
            context = await pw.chromium.launch_persistent_context(
                str(profile_dir), headless=not args.headed, args=launch_args())
        else:
            browser = await pw.chromium.launch(headless=not args.headed, args=launch_args())
            context = await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto(args.room_url, timeout=45000, wait_until="domcontentloaded")
        except Exception as e:  # noqa: BLE001
            print(f"goto warning: {e}")
        await asyncio.sleep(6)  # 直播间 UI 完全展开
        result = await page.evaluate(JS_ENUM)
        CARDS_DIR.mkdir(parents=True, exist_ok=True)
        shot = CARDS_DIR / f"{args.platform}-discover.png"
        await page.screenshot(path=str(shot), full_page=False)
        await context.close()

    print(f"== {args.platform} DOM 发现（{args.room_url}）==")
    print(f"iframe 顶层清单: {json.dumps(result.get('frames', []), ensure_ascii=False)}")
    print("\n-- 输入候选（visible 优先）--")
    inputs = sorted(result["inputs"], key=lambda x: (not x["visible"], -x["rect"][2]))
    for el in inputs[:14]:
        print(f"  [{'V' if el['visible'] else ' '}] {el['frame']:8s} <{el['tag']}> "
              f"ph={el['placeholder']!r} id={el['id']!r} cls={el['cls']!r} rect={el['rect']}")
    print("\n-- 按钮候选（含『发送』文本优先）--")
    buttons = sorted(result["buttons"], key=lambda x: (not x["visible"], "发送" not in x["text"]))
    for el in buttons[:14]:
        print(f"  [{'V' if el['visible'] else ' '}] {el['frame']:8s} <{el['tag']}> "
              f"text={el['text']!r} cls={el['cls']!r} rect={el['rect']}")
    print(f"\n截图: {shot}")


def main() -> None:
    ap = argparse.ArgumentParser(description="DOM 发现模式探针（选择器校准）")
    ap.add_argument("--platform", required=True, choices=sorted(DOM_PLATFORMS))
    ap.add_argument("--room-url", required=True)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
