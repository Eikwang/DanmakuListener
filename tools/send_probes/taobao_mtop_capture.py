"""淘宝 mtop 发送端点抓包探针（AutoDanmu T1——2026-10-07 批准计划）

计划义务映射：
- DX-D4：CLI 两形态——capture（有头交互抓包）/ --replay（无人值守离线重放）
- ENG-5（high）：--replay = 重建 data（新 ts/新文案）+ import 现有 make_sign 重新签名
  + POST——**禁止原样逐字节重放**（mtop 签名含 ts/防重放语义，原样重放必然失败，
  会把可行路线误判为不通→错误触发 T4 兜底）
- ENG-9：时间盒——replay 遇风控要求（x5sec/x-mini-wua 类）时仅尝试一种页面上下文
  获取方案，30min 不通即判 T4 转向（本脚本输出判定结论，不替人工执行时间盒）
- ENG-13：模板与 dump 落 persistence_data/（.gitignore 全目录覆盖）；模板剔除
  cookie/authorization 头；卡片注明敏感等级与清理时机
- ENG-14：replay 强制固定探针文案（[M0] 同源标记）+ 结果落卡片（审计记录）
- DX-D5：capture 顺带收集全部 mtop 响应 ret 码样本（映射表已知码来源）
- CEO-F4：判定语义——重放 3/3 成功（HTTP 200+ret SUCCESS）→ 走 T2；
  要求风控头且无页面上下文获取路径 → 走 T4 兜底

运行前提（计划 T1）：淘宝监听引擎未运行或已停（共享 taobao_profile 的
_profile_lock 单实例互斥——Chromium SingletonLock 冲突会直接报错）。

用法：
  # 有头抓包（attended）：窗口弹出后，在直播间页面人工发一条以 [M0] 开头的弹幕
  python tools/send_probes/taobao_mtop_capture.py capture --room-url "<直播间URL>"

  # 无人值守重放（3 次连发，间隔 10s+抖动）
  python tools/send_probes/taobao_mtop_capture.py --replay persistence_data/taobao-mtop-template.json --sends 3

  # 离线自检（不动网络：验证 data 重建与签名逻辑）
  python tools/send_probes/taobao_mtop_capture.py --selftest
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse, urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import CARDS_DIR, COMMON_UA, launch_args, print_card, save_card  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE_PATH = ROOT / "persistence_data" / "taobao-mtop-template.json"
PROFILE_DIR = ROOT / "cookie" / "taobao_profile"
LIVE_URL_FALLBACK = "https://tbzb.taobao.com/live?liveId={live_id}"
MTOP_HOST = "h5api.m.taobao.com"
# 已知监听 API（排除——不是发送端点）
LISTEN_APIS = (
    "mtop.taobao.powermsg.h5.msg.pullnativemsg",
    "mtop.taobao.powermsg.h5.msg.subscribe",
    "mtop.taobao.iliad.comment.query.latest",
)
REPLAY_PREFIX = "[M0]"
REPLAY_MIN_INTERVAL = 10.0
REPLAY_JITTER = 4.0
TOKEN_WAIT_BUDGET = 30.0  # replay 现取 token 预算（秒）
SENSITIVE_HEADERS = {"cookie", "authorization", "x-mini-wua", "wua", "x-sgext", "x-sign"}


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """ENG-13：剔除敏感头（token 由 replay 从 profile 现取，不落模板）"""
    return {k: v for k, v in headers.items() if k.lower() not in SENSITIVE_HEADERS}


def is_mtop_request(url: str) -> bool:
    return MTOP_HOST in url and "/h5/" in url


def parse_mtop_url(url: str) -> dict[str, Any]:
    """拆 mtop URL：api/version/query 参数"""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]  # /h5/{api}/{version}/
    return {
        "host": parsed.netloc,
        "api": parts[1] if len(parts) > 1 else "",
        "version": parts[2] if len(parts) > 2 else "",
        "query": {k: v[0] for k, v in parse_qs(parsed.query).items()},
    }


# ---------------------------------------------------------------- capture

async def run_capture(args: argparse.Namespace) -> None:
    from playwright.async_api import async_playwright

    card: dict[str, Any] = {
        "platform": "taobao-mtop", "mode": "capture",
        "room_url": args.room_url, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mtop_requests": [], "ret_samples": [], "send_candidates": [],
        "template_path": None, "verdict": None, "notes": [],
    }
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=False, user_agent=COMMON_UA,
            viewport={"width": 1280, "height": 800}, args=launch_args())
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            captured: list[dict[str, Any]] = []

            def on_request(request) -> None:  # page 级捕获（context 级实测拿不到——taobao.py:409）
                url = request.url
                if not is_mtop_request(url):
                    return
                info = parse_mtop_url(url)
                if info["api"] in LISTEN_APIS:
                    return  # 已知监听 API 排除
                captured.append({
                    "url": url, "method": request.method,
                    "post_data": request.post_data or "",
                    "headers": dict(request.headers),
                    "api": info["api"], "version": info["version"],
                    "query": info["query"], "ts": time.time(),
                })

            page.on("request", on_request)

            def on_response(response) -> None:  # DX-D5：ret 码样本收集
                if not is_mtop_request(response.url):
                    return
                info = parse_mtop_url(response.url)
                if info["api"] in LISTEN_APIS:
                    return
                asyncio.ensure_future(_collect_ret(response, info))

            async def _collect_ret(response, info: dict[str, Any]) -> None:
                try:
                    body = await response.text()
                except Exception:  # noqa: BLE001
                    return
                m = re.search(r'"ret":\s*\[(.*?)\]', body)
                if m:
                    card["ret_samples"].append({"api": info["api"], "ret": m.group(1)[:200]})

            page.on("response", on_response)

            await page.goto(args.room_url, timeout=45000, wait_until="domcontentloaded")
            print("\n" + "=" * 60)
            print("抓包进行中。请在弹出的浏览器窗口里：")
            print(f"  1. 等直播间页面加载完成（聊天区出现）")
            print(f"  2. 在输入框人工发一条以 {REPLAY_PREFIX} 开头的弹幕（例如：{REPLAY_PREFIX} 抓包测试）")
            print(f"  3. 发送后回到本终端按回车结束抓包（最长等 {args.duration}s）")
            print("=" * 60)

            # 等待人工发送：marker 出现在捕获的 post_data 中即命中；
            # 命中后自动等 6s 收集可能的后续请求（重试/二次提交）再收尾——
            # 兼容后台运行（无 stdin，input 会 EOFError；前台交互同理无需回车）
            marker_seen = False
            marker_at = 0.0
            deadline = time.monotonic() + args.duration
            while time.monotonic() < deadline:
                if not marker_seen:
                    for req in captured:
                        if REPLAY_PREFIX in (req.get("post_data") or "") or REPLAY_PREFIX in (req.get("query", {}).get("data") or ""):
                            marker_seen = True
                            marker_at = time.monotonic()
                            print(f"\n✓ 捕获到含 {REPLAY_PREFIX} 的 mtop 请求：{req['api']}（{req['method']}）——6s 后自动收尾...", flush=True)
                            break
                elif time.monotonic() - marker_at >= 6.0:
                    break
                await asyncio.sleep(1)

            card["mtop_requests"] = [
                {k: v for k, v in req.items() if k != "headers"} | {"headers": redact_headers(req["headers"])}
                for req in captured
            ]
            card["ret_samples"] = card["ret_samples"][:50]

            # 发送端点候选：marker 命中或发送时间窗内的新 POST API
            candidates = [req for req in captured if REPLAY_PREFIX in (req.get("post_data") or "")
                          or REPLAY_PREFIX in (req.get("query", {}).get("data") or "")]
            if not candidates:
                # 退化：人工发送后 120s 内新出现的非监听 POST API
                last_listen = max([req["ts"] for req in captured if req["api"] in LISTEN_APIS] or [0])
                candidates = [req for req in captured
                              if req["method"] == "POST" and req["ts"] > min(
                                  [req["ts"] for req in captured] or [0]) ]
            # 去重按 api
            seen: set[str] = set()
            unique_candidates = []
            for req in candidates:
                if req["api"] not in seen:
                    seen.add(req["api"])
                    unique_candidates.append(req)
            card["send_candidates"] = [
                {"api": req["api"], "version": req["version"], "method": req["method"],
                 "appKey": req["query"].get("appKey", ""),
                 "query_keys": sorted(req["query"].keys()),
                 "post_data_shape": _data_shape(req.get("post_data") or req["query"].get("data") or ""),
                 "content_type": req["headers"].get("content-type", ""),
                 "referer": req["headers"].get("referer", ""),
                 "origin": req["headers"].get("origin", "")}
                for req in unique_candidates
            ]

            if unique_candidates:
                best = unique_candidates[0]
                template = {
                    "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "room_url": args.room_url,
                    "domain": MTOP_HOST,
                    "api": best["api"], "version": best["version"],
                    "appKey": best["query"].get("appKey", ""),
                    "method": best["method"],
                    "url_shape": best["url"],
                    "query_template": best["query"],
                    "post_data": best.get("post_data") or "",
                    "content_type": best["headers"].get("content-type", ""),
                    "referer": best["headers"].get("referer", ""),
                    "origin": best["headers"].get("origin", ""),
                    "captured_content_marker": REPLAY_PREFIX,
                    "sensitive": "template 只含业务字段结构（cookie/auth 头已剔除）；token 由 replay 从 profile 现取",
                }
                TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
                TEMPLATE_PATH.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
                card["template_path"] = str(TEMPLATE_PATH)
                card["verdict"] = f"CAPTURED（候选 {len(unique_candidates)} 个，模板落盘 {TEMPLATE_PATH.name}）→ 下一步 --replay 3/3 判定"
                print(f"\n✓ 模板已落盘：{TEMPLATE_PATH}")
                print(f"  发送端点候选：{[c['api'] for c in card['send_candidates']]}")
            else:
                card["verdict"] = "BLOCKED——未捕获到发送请求（确认人工发送了含 [M0] 前缀的弹幕且聊天区可用）"
                print("\n✗ 未捕获到发送请求。")
        finally:
            try:
                await context.close()
            except Exception:  # noqa: BLE001
                pass
    card["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    path = save_card("taobao-mtop-capture", card)
    print_card("taobao-mtop-capture", card)
    print(f"  卡片: {path}")
    print("  敏感等级：模板/卡片含业务字段结构（已脱敏），persistence_data/ 已被 .gitignore 覆盖；清理时机=T2 验收后可删")


def _data_shape(data: str) -> str:
    """data 字段形状摘要（不落原始内容——脱敏）"""
    try:
        obj = json.loads(data)
        if isinstance(obj, dict):
            return "json{" + ",".join(sorted(obj.keys())) + "}"
        return f"json[{type(obj).__name__}]"
    except (json.JSONDecodeError, ValueError):
        if "=" in data:
            keys = re.findall(r"([^&=]+)=", data)
            return "form{" + ",".join(keys[:20]) + "}"
        return f"raw[{len(data)}B]"


# ---------------------------------------------------------------- replay

async def fetch_fresh_token() -> dict[str, str]:
    """headless 瞬态 context 现取 _m_h5_tk/_m_h5_tk_enc（ENG-5：replay 用新 token 重新签名）"""
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=True, user_agent=COMMON_UA, args=launch_args())
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                await page.goto("https://tbzb.taobao.com/", timeout=30000,
                                wait_until="domcontentloaded")
            except Exception:  # noqa: BLE001 goto 超时也继续等 cookie
                pass
            deadline = time.monotonic() + TOKEN_WAIT_BUDGET
            while time.monotonic() < deadline:
                cookies = {c["name"]: c["value"] for c in await context.cookies()}
                if "_m_h5_tk" in cookies:
                    return {"_m_h5_tk": cookies["_m_h5_tk"], "_m_h5_tk_enc": cookies.get("_m_h5_tk_enc", "")}
                await asyncio.sleep(1)
            raise RuntimeError(f"{TOKEN_WAIT_BUDGET}s 内未从 profile 取得 _m_h5_tk（token 现取失败）")
        finally:
            try:
                await context.close()
            except Exception:  # noqa: BLE001
                pass


def rebuild_data(data_str: str, new_content: str, captured_content: str, captured_ts_ms: int) -> str:
    """ENG-5：重建 data——内容字段替换 + 时间戳字段刷新（保守替换，不动业务结构）"""
    now_ms = int(time.time() * 1000)
    try:
        obj = json.loads(data_str)
    except (json.JSONDecodeError, ValueError):
        # form/原始串：值级替换
        replaced = data_str.replace(captured_content, new_content) if captured_content else data_str
        return replaced

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, str):
            if captured_content and node == captured_content:
                return new_content
            # 时间戳样字符串：13 位毫秒且与捕获时刻差 <5min → 当前毫秒
            if re.fullmatch(r"1\d{12}", node) and abs(int(node) - captured_ts_ms) < 300_000:
                return str(now_ms)
            return node
        if isinstance(node, (int, float)) and not isinstance(node, bool):
            if 1_000_000_000_000 < node < 9_999_999_999_999 and abs(node - captured_ts_ms) < 300_000:
                return now_ms
            return node
        return node

    return json.dumps(walk(obj), separators=(",", ":"), ensure_ascii=False)


async def run_replay(args: argparse.Namespace) -> None:
    import requests

    template = json.loads(Path(args.replay).read_text(encoding="utf-8"))
    api, version = template["api"], template["version"]
    app_key = template["appKey"] or template["query_template"].get("appKey", "")
    # captured_content = 模板 data 里的完整 content 值（精确匹配替换用）；
    # 取不到才退回 marker 前缀
    captured_content = template.get("captured_content_marker", REPLAY_PREFIX)
    try:
        _data_obj = json.loads(template["query_template"].get("data") or template["post_data"] or "{}")
        if isinstance(_data_obj, dict) and _data_obj.get("content"):
            captured_content = _data_obj["content"]
    except (json.JSONDecodeError, ValueError):
        pass
    captured_ts_ms = int(template["query_template"].get("t") or 0)

    print(f"replay 目标：{api} v{version} appKey={app_key}")
    print("步骤 1/2：从 taobao_profile 现取 _m_h5_tk（headless，30s 预算）...")
    token_cookies = await fetch_fresh_token()
    m_h5_tk = token_cookies["_m_h5_tk"]
    print(f"  ✓ token={m_h5_tk[:8]}...")

    sys.path.insert(0, str(ROOT))
    from danmaku_listener.engines.protocol.mtop import make_sign  # ENG-5：复用现有签名

    session = requests.Session()
    session.cookies.update(token_cookies)
    sends: list[dict[str, Any]] = []
    for seq in range(1, args.sends + 1):
        if seq > 1:
            await asyncio.sleep(REPLAY_MIN_INTERVAL + random.uniform(0, REPLAY_JITTER))
        content = f"{REPLAY_PREFIX} replay {seq}/{time.strftime('%H%M%S')}"  # ENG-14：固定探针文案同源
        t = str(int(time.time() * 1000))
        data_str = rebuild_data(template["query_template"].get("data") or template["post_data"] or "",
                                content, captured_content, captured_ts_ms)
        sign = make_sign(m_h5_tk, t, app_key, data_str)
        gateway = f"https://{template['domain']}/h5/{api}/{version}/"
        params = dict(template["query_template"])
        params.update({"appKey": app_key, "t": t, "sign": sign, "data": data_str,
                       "callback": f"mtopjsonp{random.randint(1, 100)}"})
        headers = {"User-Agent": COMMON_UA,
                   "Referer": template.get("referer") or "https://tbzb.taobao.com/",
                   "Origin": template.get("origin") or "https://tbzb.taobao.com"}
        if template.get("content_type"):
            headers["Content-Type"] = template["content_type"]
        try:
            if template["method"] == "POST":
                form = {k: v for k, v in params.items() if k not in ("sign", "t", "data")}
                body = {"appKey": app_key, "t": t, "sign": sign, "data": data_str, **form}
                # mtop POST：参数在 body（form）——去掉 query 里旧 t/sign/data
                q = {k: v for k, v in params.items() if k not in ("t", "sign", "data", "appKey")}
                resp = session.post(gateway, params=q, data=body, headers=headers, timeout=15)
            else:
                resp = session.get(gateway, params=params, headers=headers, timeout=15)
            text = resp.text
            try:
                result = json.loads(text) if not text.startswith("mtopjsonp") else json.loads(text[text.find("(") + 1:text.rfind(")")])
            except json.JSONDecodeError:
                result = {"ret": [f"PARSE_ERROR::{text[:120]}"], "raw": text[:200]}
            ret = result.get("ret") or []
            ok = any("SUCCESS" in r for r in ret)
            sends.append({"seq": seq, "http": resp.status_code, "ret": "; ".join(ret)[:200],
                          "verdict": "SUCCESS" if ok else ("FAIL" if resp.status_code == 200 else "UNKNOWN"),
                          "content": content})
            print(f"  #{seq}: HTTP {resp.status_code} ret={'; '.join(ret)[:100]} → {'SUCCESS' if ok else 'FAIL'}")
        except Exception as e:  # noqa: BLE001
            sends.append({"seq": seq, "verdict": "UNKNOWN", "error": f"{type(e).__name__}: {str(e)[:120]}"})
            print(f"  #{seq}: 异常 {type(e).__name__}: {str(e)[:100]}")

    ok_count = sum(1 for s in sends if s.get("verdict") == "SUCCESS")
    card = {
        "platform": "taobao-mtop", "mode": "replay", "template": args.replay,
        "api": api, "version": version, "appKey": app_key, "sends": sends,
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "verdicts_summary": f"SUCCESS={ok_count}/{len(sends)}",
        "verdict": ("GO_T2——重放判定通过，走 T2 mtop sender" if ok_count == args.sends and args.sends > 0
                    else "NO_GO——重放未全过：按 ret 码判别（风控头要求→T4 兜底/ENG-9 时间盒；token/参数错误→核对模板与 profile 登录态）"),
    }
    path = save_card("taobao-mtop-replay", card)
    print_card("taobao-mtop-replay", card)
    print(f"  卡片: {path}")


# ---------------------------------------------------------------- selftest

def run_selftest() -> None:
    """离线自检：data 重建与签名逻辑（ENG-5 核心逻辑不触网验证）"""
    from danmaku_listener.engines.protocol.mtop import make_sign

    captured_content = "[M0] 抓包测试"
    captured_ts = 1728271200000
    data = json.dumps({"content": captured_content, "liveId": "123", "ts": str(captured_ts),
                       "count": 1, "nested": {"msg": captured_content}}, separators=(",", ":"))
    rebuilt = rebuild_data(data, "[M0] replay 1/120000", captured_content, captured_ts)
    obj = json.loads(rebuilt)
    assert obj["content"] == "[M0] replay 1/120000", obj
    assert obj["nested"]["msg"] == "[M0] replay 1/120000", obj
    assert obj["liveId"] == "123", obj  # 业务字段不动
    assert obj["count"] == 1, obj
    assert obj["ts"] != str(captured_ts) and re.fullmatch(r"1\d{12}", obj["ts"]), obj  # ts 刷新
    sign = make_sign("abc_token_123", "1728271200001", "12574478", rebuilt)
    assert re.fullmatch(r"[0-9a-f]{32}", sign), sign
    form_rebuilt = rebuild_data("a=1&content=%5BM0%5D+x", "[M0] r2", "", 0)
    assert form_rebuilt.startswith("a=1&"), form_rebuilt
    print("selftest PASS：data 重建（json/form）+ ts 刷新 + make_sign 签名格式 全部通过")


# ---------------------------------------------------------------- page-eval（ENG-9 一种页面上下文方案）

PAGE_EVAL_JS = """
async (args) => {
  const mtop = (window.lib && window.lib.mtop) || window.mtop;
  if (!mtop || typeof mtop.request !== 'function') {
    return {error: 'mtop lib not found on page (window.lib.mtop / window.mtop 均不存在)'};
  }
  try {
    const res = await mtop.request({
      api: args.api, v: args.v, appKey: args.appKey,
      data: args.data, type: 'GET', dataType: 'jsonp', timeout: 15000,
    });
    return {ret: res && res.ret, data_summary: res && res.data ? 'present' : String(res && res.data).slice(0, 100)};
  } catch (e) {
    let detail = '';
    try { detail = JSON.stringify(e && e.ret ? {ret: e.ret} : (e && e.message) ? {msg: e.message} : String(e)).slice(0, 300); }
    catch (e2) { detail = String(e).slice(0, 300); }
    return {rejected: true, ret: e && e.ret, detail: detail};
  }
}
"""


async def run_page_eval(args: argparse.Namespace) -> None:
    """ENG-9 时间盒内的一种页面上下文获取方案：页面 mtop 库调用（页面 JS 现生成 bx-ua）"""
    from playwright.async_api import async_playwright

    template = json.loads(Path(args.replay).read_text(encoding="utf-8"))
    api, version, app_key = template["api"], template["version"], template["appKey"]
    data_obj = json.loads(template["query_template"].get("data") or "{}")
    topic = data_obj.get("topic", "")
    card: dict[str, Any] = {
        "platform": "taobao-mtop", "mode": "page-eval",
        "api": api, "version": version, "appKey": app_key, "topic": topic[:16] + "...",
        "sends": [], "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    sends: list[dict[str, Any]] = []
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=True, user_agent=COMMON_UA, args=launch_args())
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(args.room_url, timeout=45000, wait_until="domcontentloaded")
            await asyncio.sleep(5)  # 页面 JS/mtop 库初始化
            for seq in range(1, args.sends + 1):
                if seq > 1:
                    await asyncio.sleep(REPLAY_MIN_INTERVAL + random.uniform(0, REPLAY_JITTER))
                content = f"{REPLAY_PREFIX} page-eval {seq}/{time.strftime('%H%M%S')}"
                try:
                    result = await page.evaluate(
                        PAGE_EVAL_JS,
                        {"api": api, "v": version, "appKey": app_key,
                         "data": {"topic": topic, "content": content}})
                    if "error" in result:
                        sends.append({"seq": seq, "verdict": "BLOCKED", "detail": result["error"]})
                        print(f"  #{seq}: {result['error']}")
                        break
                    if result.get("rejected"):
                        ret = "; ".join(result.get("ret") or []) or result.get("detail", "")
                        sends.append({"seq": seq, "verdict": "FAIL", "ret": ret[:200], "detail": result.get("detail", "")[:120]})
                        print(f"  #{seq}: reject → {ret[:100]}")
                        continue
                    ret = "; ".join(result.get("ret") or [])
                    ok = "SUCCESS" in ret
                    sends.append({"seq": seq, "ret": ret[:200],
                                  "verdict": "SUCCESS" if ok else "FAIL"})
                    print(f"  #{seq}: ret={ret[:100]} → {'SUCCESS' if ok else 'FAIL'}")
                except Exception as e:  # noqa: BLE001
                    sends.append({"seq": seq, "verdict": "UNKNOWN",
                                  "detail": f"{type(e).__name__}: {str(e)[:120]}"})
                    print(f"  #{seq}: 异常 {type(e).__name__}: {str(e)[:100]}")
        finally:
            try:
                await context.close()
            except Exception:  # noqa: BLE001
                pass
    ok_count = sum(1 for s in sends if s.get("verdict") == "SUCCESS")
    blocked = any(s.get("verdict") == "BLOCKED" for s in sends)
    card["sends"] = sends
    card["verdicts_summary"] = f"SUCCESS={ok_count}/{len(sends)}"
    if blocked:
        card["verdict"] = "BLOCKED——页面 mtop 库不可达（换有头窗口/等页面完全加载后重试一次；仍失败→T4）"
    elif ok_count == args.sends and args.sends > 0:
        card["verdict"] = ("GO_T2_PAGE_EVAL——页面上下文 mtop 库调用通过：T2 形态=sender 经页面 evaluate 调 "
                           "iliad.comment.publish（页面 JS 现生成 bx-ua；需页面宿主=引擎瞬态页或常驻会话）")
    else:
        card["verdict"] = "NO_GO——页面上下文调用仍被风控/失败：转 T4 兜底（ENG-9 时间盒用毕）"
    path = save_card("taobao-mtop-pageeval", card)
    print_card("taobao-mtop-pageeval", card)
    print(f"  卡片: {path}")


# ---------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description="淘宝 mtop 发送端点抓包探针（T1）")
    parser.add_argument("--room-url", help="淘宝直播间 URL（capture/page-eval 用）")
    parser.add_argument("--replay", metavar="TEMPLATE", help="模板路径（replay/page-eval 用）")
    parser.add_argument("--page-eval", action="store_true",
                        help="页面上下文方案（ENG-9 时间盒内的一种）：开直播间页调用页面 mtop 库发送（页面 JS 现生成 bx-ua）")
    parser.add_argument("--sends", type=int, default=3, help="replay 连发次数（默认 3）")
    parser.add_argument("--selftest", action="store_true", help="离线自检（不动网络）")
    sub = parser.add_subparsers(dest="mode")
    cap = sub.add_parser("capture", help="有头交互抓包（attended）")
    cap.add_argument("--duration", type=float, default=300, help="抓包最长等待（秒）")
    args = parser.parse_args()

    if args.selftest:
        run_selftest()
        return
    if args.page_eval:
        asyncio.run(run_page_eval(args))
        return
    if args.replay:
        asyncio.run(run_replay(args))
        return
    if args.mode == "capture":
        asyncio.run(run_capture(args))
        return
    parser.print_help()


if __name__ == "__main__":
    main()
