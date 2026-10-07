"""M0 受控页面 DOM 发送探针（计划 T2——覆盖 9 平台，R17/R22/F5）

纪律：
- 探针账号环境与实发一致（R17）：profile platforms 直接用 cookie/ 既有 profile；
  cookie-file 平台注入既有登录态；未登录=探针报 NEEDS_LOGIN（不代登录）
- 连续 N 次发送（默认 3）+ 每次间隔最小 10s+抖动 + 风控信号观察
- 成功判定（F5）：marker 回显于聊天流=SUCCESS；显式错误信号=FAIL；无回显无错误=UNKNOWN
- 选择器=发现模式：先试平台候选，失败即 dump 全部输入框/按钮候选（探针即发现工具）
- 所有发送内容带 [M0] 前缀 + 序号（回环识别，F8）

运行（attended，弹可见窗口）：
  python tools/send_probes/dom_send_probe.py --platform taobao --room-url "<直播间URL>"
  python tools/send_probes/dom_send_probe.py --platform douyu --room-url "https://www.douyu.com/12345" --sends 3
输出：tools/send_probes/cards/<platform>-<ts>.json + stdout 卡片
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

from playwright.async_api import async_playwright  # noqa: E402

from common import (CARDS_DIR, COMMON_UA, DOM_PLATFORMS, ROOT,  # noqa: E402
                    common_precheck, launch_args, marker_content, observe_risk_signals,
                    paced_sends, print_card, save_card, verdict_summary)

# 平台 → 输入框/按钮候选（优先级序；失败自动 dump 全部候选）
INPUT_CANDIDATES = {
    "douyu": [".ChatSend-input", "textarea.chat-input", "input[placeholder*=弹幕]"],
    "huya": ["#pub_msg_input", "input[placeholder*=弹幕]", "input[placeholder*=说点]"],
    "douyin": ["div[contenteditable=true]", "textarea[placeholder*=弹幕]", "input[placeholder*=说点什么]"],
    "kuaishou": ["input[placeholder*=弹幕]", "input[placeholder*=说点]", "div[contenteditable=true]"],
    "taobao": ["textarea", "input[placeholder*=说]", "div[contenteditable=true]"],
    "1688": ["textarea", "input[placeholder*=说]", "div[contenteditable=true]"],
    "xiaohongshu": ["textarea", "input[placeholder*=说]", "div[contenteditable=true]"],
    "jd": ["textarea", "input[placeholder*=说]", "div[contenteditable=true]"],
    "wechat_channels": ["textarea", "div[contenteditable=true]", "input[placeholder*=说]"],
}
BUTTON_CANDIDATES = {
    "douyu": [".ChatSend-button", 'button:has-text("发送")'],
    "huya": [".send-btn", 'button:has-text("发送")', 'text=发送'],
    "douyin": ['button:has-text("发送")', 'div[role=button]:has-text("发送")'],
    "kuaishou": ['button:has-text("发送")', 'text=发送'],
}
GENERIC_BUTTONS = ['button:has-text("发送")', 'text=发送', '[class*=send]']
GENERIC_INPUTS = ["textarea", "input[placeholder]", "div[contenteditable=true]"]

# 显式错误信号（FAIL 判定）
FAIL_SIGNALS = ["text=被禁言", "text=禁言", "text=验证码", "text=登录", "text=失败"]


async def discover(page, candidates: list[str], generic: list[str], kind: str) -> tuple[str | None, list[str]]:
    """按候选序找可见元素；失败返回 None + dump 候选清单"""
    tried: list[str] = []
    for sel in candidates + generic:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                return sel, tried
            tried.append(f"{sel}(不可见/不存在)")
        except Exception as e:  # noqa: BLE001
            tried.append(f"{sel}({type(e).__name__})")
    return None, tried


async def find_echo(page, marker: str, timeout_s: float = 12.0) -> bool:
    """F5 判定：marker 回显于页面聊天流（轮询 content 搜索——虚拟列表低成本首查）"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            content = await page.content()
            if marker in content:
                return True
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(0.8)
    return False


async def run(args: argparse.Namespace) -> None:
    pre = common_precheck(args.platform)
    if not pre["ok"]:
        print(pre["reason"]); return
    cfg = pre["config"]
    card: dict = {
        "platform": args.platform, "room_url": args.room_url,
        "sends_planned": args.sends, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "route": "DOM（R22 探针）", "sends": [], "risk_signals": [],
        "selector_notes": {}, "verdicts_summary": None, "blocked_reason": None,
    }
    profile = cfg.get("profile")
    profile_dir = ROOT / "cookie" / profile if profile else None

    async with async_playwright() as pw:
        if profile_dir and profile_dir.is_dir():
            context = await pw.chromium.launch_persistent_context(
                str(profile_dir), headless=not args.headed, args=launch_args(), user_agent=COMMON_UA)
        else:
            browser = await pw.chromium.launch(headless=not args.headed, args=launch_args())
            context = await browser.new_context(user_agent=COMMON_UA)
            # cookie-file 平台注入既有登录态（douyin 平面 dict / douyu {cookies:[]} / kuaishou storage_state）
            injected = await try_inject_cookies(context, args.platform)
            card["cookie_injection"] = injected
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto(args.room_url, timeout=45000, wait_until="domcontentloaded")
        except Exception as e:  # noqa: BLE001
            card["blocked_reason"] = f"goto 失败: {type(e).__name__}: {str(e)[:120]}"
        if not card["blocked_reason"]:
            await asyncio.sleep(3)
            input_sel, in_tried = await discover(page, INPUT_CANDIDATES.get(args.platform, []), GENERIC_INPUTS, "输入框")
            card["selector_notes"]["input"] = {"found": input_sel, "tried": in_tried[:8]}
            btn_sel, btn_tried = await discover(page, BUTTON_CANDIDATES.get(args.platform, []), GENERIC_BUTTONS, "按钮")
            card["selector_notes"]["button"] = {"found": btn_sel, "tried": btn_tried[:8]}
            if not input_sel:
                card["blocked_reason"] = "未发现可用输入框——选择器候选已 dump（selector_notes.input.tried）"
            for i, gap in enumerate(await paced_sends(args.sends), 1):
                if i > 1:
                    await asyncio.sleep(gap)
                if card["blocked_reason"]:
                    break
                marker = (args.custom_messages[i - 1] if getattr(args, "custom_messages", None)
                          else marker_content(i))
                entry: dict = {"seq": i, "marker": marker, "verdict": "UNKNOWN", "detail": ""}
                try:
                    loc = page.locator(input_sel).first
                    if args.platform == "1688":
                        # 1688 实证：fill 的 DOM 值不进框架 state、发送 div 点击不可靠——
                        # 唯一可靠配方 = click 聚焦 + 逐键输入 + Enter 提交
                        await loc.click()
                        await loc.press_sequentially(marker, delay=40)
                        await loc.press("Enter")
                    else:
                        await loc.fill(marker)
                        if btn_sel:
                            await page.locator(btn_sel).first.click()
                        else:
                            await loc.press("Enter")
                    await asyncio.sleep(1.5)
                    risk = await observe_risk_signals(page)
                    if risk:
                        entry["verdict"] = "FAIL"; entry["detail"] = f"风控信号: {risk}"
                        card["risk_signals"].extend(risk)
                    elif await find_echo(page, marker):
                        entry["verdict"] = "SUCCESS"; entry["detail"] = "marker 回显于聊天流"
                    else:
                        entry["verdict"] = "UNKNOWN"; entry["detail"] = "无回显且无显式错误（虚拟列表/慢渲染可能）"
                        try:
                            await page.screenshot(path=str(CARDS_DIR / f"{args.platform}-unknown-{i}.png"))
                        except Exception:  # noqa: BLE001
                            pass
                except Exception as e:  # noqa: BLE001
                    entry["verdict"] = "FAIL"; entry["detail"] = f"{type(e).__name__}: {str(e)[:120]}"
                card["sends"].append(entry)
                print(f"  [{args.platform} #{i}] {entry['verdict']}: {entry['detail']}")
        try:
            await context.close()
        except Exception:  # noqa: BLE001
            pass
    card["verdicts_summary"] = verdict_summary(card["sends"])
    if card["risk_signals"]:
        card["feasibility_note"] = "出现风控信号——按 R17 记录，M1 决策须评估频率/反检测策略"
    path = save_card(args.platform, card)
    print_card(args.platform, card)
    print(f"  card: {path}")


async def try_inject_cookies(context, platform: str) -> str:
    """注入既有登录态（douyin 平面 dict / douyu-huya {cookies:[]} / kuaishou storage_state）"""
    mapping = {"douyin": ROOT / "cookie" / "douyin_cookies.json",
               "douyu": ROOT / "cookie" / "douyu_login_cookies.json",
               "huya": ROOT / "cookie" / "huya_login_cookies.json",
               "kuaishou": ROOT / "cookie" / "kuaishou_storage_state.json"}
    path = mapping.get(platform)
    if not path or not path.is_file():
        return f"无存档文件（{platform}）——未登录态探针"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        items = raw.get("cookies", []) if isinstance(raw, dict) and "cookies" in raw else \
            raw if isinstance(raw, list) else \
            [{"name": k, "value": v, "domain": _domain(platform)} for k, v in raw.items()]
        items = [c for c in items if c.get("name") and c.get("domain")]
        if not items:
            return "存档无可注入 cookie（缺 domain 字段）"
        await context.add_cookies(items)
        return f"已注入 {len(items)} 条 cookie"
    except Exception as e:  # noqa: BLE001
        return f"注入失败: {type(e).__name__}: {str(e)[:80]}"


def _domain(platform: str) -> str:
    return {"douyin": ".douyin.com", "douyu": ".douyu.com", "huya": ".huya.com",
            "kuaishou": ".kuaishou.com"}.get(platform, "")


def main() -> None:
    ap = argparse.ArgumentParser(description="M0 DOM 发送探针（attended）")
    ap.add_argument("--platform", required=True, choices=sorted(DOM_PLATFORMS))
    ap.add_argument("--room-url", required=True, help=DOM_PLATFORMS.get("", {}).get("room_url_hint", "直播间 URL"))
    ap.add_argument("--sends", type=int, default=3, help="连续发送次数（默认 3，R17）")
    ap.add_argument("--messages", default=None,
                    help="自定义内容列表（分号分隔），如 --messages '甲；乙；丙'——提供时覆盖自动 marker")
    ap.add_argument("--headed", action="store_true", help="可见窗口（默认 attended 可见）")
    args = ap.parse_args()
    args.custom_messages = [m.strip() for m in args.messages.split("；") if m.strip()] if args.messages else None
    if args.custom_messages:
        args.sends = len(args.custom_messages)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
