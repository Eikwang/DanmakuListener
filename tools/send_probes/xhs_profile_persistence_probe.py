"""小红书 profile 保存逻辑专项探针（2026-10-10 用户裁定重测）

背景：2026-10-09 验收 16:06 两次 SENT 后登录态全失，磁盘 Cookies 库无 id_token
痕迹且 web_session 创建时间早于登录——登录 cookie 从未落盘。用户实证推翻
"小红书 cookie 会话级"旧结论（Edge 跨浏览器重启/跨机重启均保持登录）。

本探针把 profile 保存链路逐环变成可观测证据：
- singleton：同 profile 双 persistent context 实况（架构冲突实证）
- state：当前 profile 登录态快照（预期游客）
- login：可见窗口等待用户登录 → **磁盘提交时刻测量**（每 5s 拷贝 Cookies 库
  查 id_token——登录 cookie 何时/是否写盘）+ storage_state 快照落盘
- send：引擎同款 #input-area 配方实发（给定在播房间）
- repersist：干净关闭后重开进程 → 登录态是否存活（profile 保存终判）

纪律：与 ControlledPageEngine 同款 launch 形态（UA/viewport/反检测参数），
探针结论可直接迁移引擎代码。卡片输出 cards/xhs-persist-<ts>.json。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sqlite3
import time
from pathlib import Path

from playwright.async_api import async_playwright

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import launch_args, COMMON_UA, CARDS_DIR  # noqa: E402

PROFILE = Path("./cookie/xhs_profile").resolve()
STATE_SNAPSHOT = Path("./cookie/xhs_send_state.json")
ROOM_URL = ("https://www.xiaohongshu.com/livestream/570489920606526827"
            "?track_id=live_rtag_chat%406ac993d178396a001509b2c7&source=web_feed"
            "&xsec_token=ABLwIcGF8_P0crb2KuSH9D7posLirsaEQ3C51TA1acPPF8KjjzlqnW7k6rvQf76BA6")
LOGIN_COOKIE = "id_token"
VIEWPORT = {"width": 1280, "height": 800}
LOGIN_WAIT_S = 420          # 等用户扫码上限
POST_LOGIN_GRACE_S = 30     # 登录后保窗（滑块/安全验证）——与 LOGIN_POST_GRACE_S 对齐
DB_POLL_S = 5               # 磁盘 Cookies 库轮询间隔


def db_xhs_cookies() -> list[dict]:
    """拷贝磁盘 Cookies 库 → 小红书 cookie 行（name/persistent/创建/过期）"""
    tmp = CARDS_DIR / "_cookies_snapshot.db"
    src = PROFILE / "Default" / "Network" / "Cookies"
    if not src.is_file():
        return []
    try:
        shutil.copy2(src, tmp)
        con = sqlite3.connect(str(tmp))
        rows = con.execute(
            "SELECT name, is_persistent, "
            "datetime(creation_utc/1000000-11644473600,'unixepoch','localtime'), "
            "datetime(expires_utc/1000000-11644473600,'unixepoch','localtime') "
            "FROM cookies WHERE host_key LIKE '%xiaohongshu%'").fetchall()
        con.close()
        return [{"name": r[0], "persistent": r[1], "created": r[2], "expires": r[3]}
                for r in rows]
    except Exception as e:  # noqa: BLE001
        return [{"error": f"{type(e).__name__}: {e}"}]
    finally:
        tmp.unlink(missing_ok=True)


def disk_has_login() -> tuple[bool, list[dict]]:
    rows = db_xhs_cookies()
    hit = any(r.get("name") == LOGIN_COOKIE and r.get("persistent") for r in rows)
    return hit, rows


async def launch_ctx(pw, headless: bool = False, profile: str | None = None,
                     extra_args: list[str] | None = None):
    """引擎同款 launch 形态（controlled_base._launch 对齐——headed）"""
    return await pw.chromium.launch_persistent_context(
        profile or str(PROFILE), headless=headless, user_agent=COMMON_UA,
        viewport=VIEWPORT, args=launch_args() + (extra_args or []))


async def page_login_state(page, context) -> dict:
    cookies = {c["name"] for c in await context.cookies() if c.get("value")}
    state = {"memory_id_token": LOGIN_COOKIE in cookies,
             "memory_web_session": "web_session" in cookies}
    for sel in ("#input-area", "text=登录", "text=扫码"):
        try:
            loc = page.locator(sel).first
            state[f"visible:{sel}"] = (await loc.count() > 0
                                       and await loc.is_visible())
        except Exception:  # noqa: BLE001
            state[f"visible:{sel}"] = False
    return state


async def stage_singleton(card: dict) -> None:
    """同 profile 双 persistent context 实况（E5 冲突实证——引擎监听+发送双开）"""
    async with async_playwright() as pw:
        ctx_a = await launch_ctx(pw)
        try:
            await asyncio.sleep(2)
            try:
                ctx_b = await launch_ctx(pw)
                try:
                    await ctx_b.close()
                    card["singleton"] = ("SECOND_LAUNCH_OK——同 profile 双开未报错"
                                         "（需进一步查 cookie 互写）")
                except Exception as e:  # noqa: BLE001
                    card["singleton"] = f"second closed with {type(e).__name__}"
            except Exception as e:  # noqa: BLE001
                card["singleton"] = (f"SECOND_LAUNCH_BLOCKED: {type(e).__name__}: "
                                     f"{str(e)[:160]}")
        finally:
            try:
                await ctx_a.close()
            except Exception:  # noqa: BLE001
                pass


async def stage_state(card: dict) -> None:
    """当前 profile 登录态快照 + 干净关闭前后磁盘库对照（基线）"""
    before = disk_has_login()
    card["state_disk_before"] = {"login_on_disk": before[0], "cookies": before[1]}
    async with async_playwright() as pw:
        ctx = await launch_ctx(pw)
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto(ROOM_URL, timeout=45000, wait_until="domcontentloaded")
            await asyncio.sleep(6)
            card["state_page"] = await page_login_state(page, ctx)
            card["state_screenshot"] = str(await _shot(page, "state"))
        finally:
            try:
                await ctx.close()   # 干净关闭
            except Exception:  # noqa: BLE001
                pass
    after = disk_has_login()
    card["state_disk_after_clean_close"] = {"login_on_disk": after[0],
                                            "cookies": after[1]}


async def stage_login(card: dict) -> None:
    """等待用户在可见窗口登录 → 测量登录 cookie 磁盘提交时刻（核心环）"""
    async with async_playwright() as pw:
        ctx = await launch_ctx(pw)
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto(ROOM_URL, timeout=45000, wait_until="domcontentloaded")
            await asyncio.sleep(4)
            card["login_page_before"] = await page_login_state(page, ctx)
            print(f"[login] 窗口已打开（{PROFILE}），请在窗口内完成小红书登录"
                  f"（最长 {LOGIN_WAIT_S}s）……", flush=True)
            t0 = time.monotonic()
            login_at = None
            disk_commit_at = None
            disk_polls: list[dict] = []
            next_db_poll = 0.0
            while time.monotonic() - t0 < LOGIN_WAIT_S:
                await asyncio.sleep(2)
                try:
                    cookies = {c["name"] for c in await ctx.cookies() if c.get("value")}
                except Exception as e:  # noqa: BLE001  窗口被关
                    card["login_interrupted"] = f"{type(e).__name__}（窗口被用户关闭）"
                    break
                now = time.monotonic()
                if LOGIN_COOKIE in cookies and login_at is None:
                    login_at = round(now - t0, 1)
                    print(f"[login] 内存检测到 {LOGIN_COOKIE}（t+{login_at}s）"
                          "——开始保窗宽限+磁盘提交观测", flush=True)
                if login_at is not None and now >= next_db_poll:
                    next_db_poll = now + DB_POLL_S
                    hit, rows = disk_has_login()
                    disk_polls.append({"t": round(now - t0, 1), "login_on_disk": hit,
                                       "web_session_created": next(
                                           (r.get("created") for r in rows
                                            if r.get("name") == "web_session"), None)})
                    if hit and disk_commit_at is None:
                        disk_commit_at = round(now - t0, 1)
                        print(f"[login] ★ 登录 cookie 落盘（t+{disk_commit_at}s）",
                              flush=True)
                if login_at is not None and now - login_at >= POST_LOGIN_GRACE_S:
                    break
            card["login"] = {"memory_login_at_s": login_at,
                             "disk_commit_at_s": disk_commit_at,
                             "disk_polls": disk_polls}
            if login_at is not None:
                await asyncio.sleep(2)
                state = await ctx.storage_state()
                STATE_SNAPSHOT.write_text(json.dumps(state, ensure_ascii=False),
                                          encoding="utf-8")
                card["storage_state_snapshot"] = str(STATE_SNAPSHOT)
                card["storage_state_cookie_count"] = len(state.get("cookies", []))
            card["login_page_after"] = await page_login_state(page, ctx)
            card["login_screenshot"] = str(await _shot(page, "login"))
        finally:
            try:
                await ctx.close()   # 干净关闭——Chromium 应在此时 flush
            except Exception:  # noqa: BLE001
                pass
    hit, rows = disk_has_login()
    card["login_disk_after_clean_close"] = {"login_on_disk": hit,
                                            "cookies": rows}


async def stage_send(card: dict, *, bg: bool = False,
                     profile: str | None = None,
                     restore: str | None = None) -> None:
    """引擎同款 #input-area 配方实发 + WS 帧回环验证

    bg=True：headless=new 后台形态（无感模式预演——登录态 + 完整指纹实测）
    restore：F1 快照 JSON 注入（一次性 profile + add_cookies——引擎
    _restore_login_state 同款机制野外验证）
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from danmaku_listener.engines.protocol.xiaohongshu import parse_ws_frame
    content = f"[M0] profile重测 {time.strftime('%H%M%S')}"
    card["send_mode"] = ("headless_new_bg" if bg else "headed")
    if restore:
        card["restore_snapshot"] = restore
    async with async_playwright() as pw:
        extra = ["--headless=new", "--mute-audio"] if bg else None
        ctx = await launch_ctx(pw, headless=False, profile=profile,
                               extra_args=extra)
        try:
            if restore:
                state = json.loads(Path(restore).read_text(encoding="utf-8"))
                await ctx.add_cookies(state.get("cookies", []))
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            # WS 收集必须先于 goto（已有连接不触发 websocket 事件——F3 实证）
            ws_frames: list = []

            def _on_ws(ws):
                ws.on("framereceived",
                      lambda p: ws_frames.append(p.get("payload")
                                                 if isinstance(p, dict) else p))

            page.on("websocket", _on_ws)
            await page.goto(ROOM_URL, timeout=45000, wait_until="domcontentloaded")
            await asyncio.sleep(4)
            card["send_login_state"] = await page_login_state(page, ctx)
            inp = None
            for sel in ("#input-area", "#input-area div[contenteditable=true]",
                        "#input-area textarea", "textarea",
                        "div[contenteditable=true]"):
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        inp = loc
                        break
                except Exception:  # noqa: BLE001
                    continue
            if inp is None:
                card["send"] = "NO_INPUT（未登录/页面结构变更）"
                return
            await inp.click()
            await inp.press_sequentially(content, delay=50)
            await inp.press("Enter")
            btn = page.locator("#input-area button").first
            if await btn.count() > 0 and await btn.is_visible():
                try:
                    await btn.click(timeout=3000)
                except Exception:  # noqa: BLE001
                    pass
            echo_deadline = time.monotonic() + 15
            hit = False
            ws_hit = False
            ws_text_total = 0
            while time.monotonic() < echo_deadline:
                # WS 帧解析（引擎 parse_ws_frame 同款）——服务端回环=真回显
                for raw in list(ws_frames):
                    for cd in parse_ws_frame(raw):
                        if cd.get("type") == "text":
                            ws_text_total += 1
                            if (cd.get("desc") or "").strip() == content:
                                ws_hit = True
                if ws_hit:
                    break
                txt = await page.evaluate(
                    "(m) => { const el = document.querySelector('#input-area');"
                    " const main = el ? (el.closest('.main-comment') || el.parentElement) : null;"
                    " if (!main) return '';"
                    " const area = main.querySelector('#input-area');"
                    " const base = area ? area.innerText : '';"
                    " return main.innerText.replace(base, '').slice(-400); }", content)
                if content in (txt or ""):
                    hit = True
                    break
                await asyncio.sleep(1.5)
            card["send"] = {"content": content,
                            "verdict": ("SENT(WS服务端回环)" if ws_hit
                                        else "SENT(仅DOM列表)" if hit
                                        else "无回显"),
                            "ws_text_frames": ws_text_total}
            card["send_screenshot"] = str(await _shot(page, "send"))
        finally:
            try:
                await ctx.close()
            except Exception:  # noqa: BLE001
                pass


async def stage_repersist(card: dict) -> None:
    """全新进程重开 profile → 登录态存活判定（profile 保存终判）"""
    async with async_playwright() as pw:
        ctx = await launch_ctx(pw)
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto(ROOM_URL, timeout=45000, wait_until="domcontentloaded")
            await asyncio.sleep(6)
            card["repersist"] = await page_login_state(page, ctx)
            card["repersist_disk"] = {"login_on_disk": disk_has_login()[0]}
            card["repersist_screenshot"] = str(await _shot(page, "repersist"))
        finally:
            try:
                await ctx.close()
            except Exception:  # noqa: BLE001
                pass


async def _shot(page, tag: str) -> str:
    p = CARDS_DIR / f"xhs-persist-{tag}-{time.strftime('%H%M%S')}.png"
    try:
        await page.screenshot(path=str(p), full_page=False)
    except Exception:  # noqa: BLE001
        return ""
    return str(p)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="state",
                    choices=["singleton", "state", "login", "send", "repersist"])
    ap.add_argument("--bg", action="store_true",
                    help="send 阶段：headless=new 后台形态（无感模式预演）")
    ap.add_argument("--profile", default=None,
                    help="一次性 profile 目录（隔离运行中的服务 profile）")
    ap.add_argument("--restore", default=None,
                    help="F1 快照 JSON——启动后注入登录 cookie")
    args = ap.parse_args()
    card: dict = {"probe": "xhs_profile_persistence", "stage": args.stage,
                  "profile": args.profile or str(PROFILE),
                  "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    if args.stage == "send":
        await stage_send(card, bg=args.bg, profile=args.profile,
                         restore=args.restore)
    else:
        await {"singleton": stage_singleton, "state": stage_state,
               "login": stage_login,
               "repersist": stage_repersist}[args.stage](card)
    out = CARDS_DIR / f"xhs-persist-{args.stage}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(card, ensure_ascii=False, indent=2))
    print(f"卡片: {out}")


if __name__ == "__main__":
    asyncio.run(main())
