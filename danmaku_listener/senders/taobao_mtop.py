"""淘宝 mtop page-eval sender（AutoDanmu T2——T1 探针判定定型形态）

T1 判定（cards/taobao-mtop-{capture,replay,pageeval}-20261007-*.json）：
- 发送端点 = mtop.taobao.iliad.comment.publish v1.0（appKey 34675810，data={topic,content}）
- 纯 HTTP 重放 0/3 FAIL（RGV587——query 的 bx-ua/bx_et 行为签名必须页面 JS 现生成，
  make_sign 重建 sign 正确仍被拒）→ **页面上下文调用 window.lib.mtop.request 2/2 SUCCESS**
- 形态定型：sender 经瞬态页 evaluate 调页面 mtop 库（页面 JS 现生成 bx-ua/签名/token）
  ——ENG-2/15 的 token 单实例/single-flight 语义由页面 mtop 库天然管理，无需自建

E5 义务：持监听引擎引用，借引擎 _profile_lock 开瞬态页（persistent context 单实例
串行，taobao.py:165 实证禁止另开无锁 context）；S4-1 锁超时回执 busy。

ret 五路径映射（CEO-F4/DX-D5，已知码样本来自 T1）：
  1. SUCCESS → SENT
  2. RGV587/FAIL_SYS_USER_VALIDATE/x5sec（风控）→ FAIL PLATFORM_REJECTED（勿误导重扫码）
  3. SESSION_EXPIRED/NEED_LOGIN/未登录类 → FAIL NEEDS_LOGIN 语义
  4. FAIL_SYS_PARAM*/ILLEGAL（参数错误）→ FAIL 参数细分
  5. 其它未知 ret → FAIL 保守透传原始 ret 到 detail
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Optional
from urllib.parse import unquote

from loguru import logger
from playwright.async_api import async_playwright  # 模块级：测试注入点（monkeypatch mod.async_playwright）

from danmaku_listener.contract.models import SendRejectReason, SendStatus
from danmaku_listener.senders.base import BaseSender, SendResult

PUBLISH_API = "mtop.taobao.iliad.comment.publish"
PUBLISH_VERSION = "1.0"
PUBLISH_APPKEY = "34675810"
LOCK_TIMEOUT_S = 3.0          # S4-1：监听重登长动作不饿死发送
PAGE_TIMEOUT_MS = 30_000      # ENG-1 同款纪律：单次操作显式超时
MTOP_LIB_WAIT_S = 20.0        # 页面 mtop 库就绪预算
TOPIC_WAIT_S = 20.0           # 页面请求锚定 topic 预算

# 已知 ret 码分类（DX-D5 样本 + 惯例前缀；顺序敏感——先匹配风控再未登录）
RET_RISK_PATTERNS = ("RGV587", "FAIL_SYS_USER_VALIDATE", "x5sec", "P_UNCHECKED")
RET_LOGIN_PATTERNS = ("SESSION_EXPIRED", "NEED_LOGIN", "FAIL_SYS_SESSION", "登录")

EVAL_SEND_JS = """
async (args) => {
  const mtop = (window.lib && window.lib.mtop) || window.mtop;
  if (!mtop || typeof mtop.request !== 'function') {
    return {error: 'mtop lib not found'};
  }
  try {
    const res = await mtop.request({
      api: args.api, v: args.v, appKey: args.appKey,
      data: args.data, type: 'GET', dataType: 'jsonp', timeout: 15000,
    });
    return {ret: res && res.ret};
  } catch (e) {
    return {rejected: true, ret: (e && e.ret) || null, detail: String(e && (e.message || e)).slice(0, 160)};
  }
}
"""

EVAL_LIB_PROBE_JS = "!!((window.lib && window.lib.mtop) || window.mtop) && typeof ((window.lib && window.lib.mtop) || window.mtop).request === 'function'"


class TaobaoMtopSender(BaseSender):
    """淘宝 mtop page-eval 发送器（E5：经由监听引擎实例的锁与 profile 执行）"""

    platform = "taobao"

    def __init__(self, engine: Any):
        self._engine = engine  # TaobaoWebProtocolEngine（_profile_lock/_profile_dir/LIVE_URL_TEMPLATE）

    async def send(self, room_id: str, content: str) -> SendResult:
        try:
            await asyncio.wait_for(self._engine._profile_lock.acquire(), timeout=LOCK_TIMEOUT_S)
        except asyncio.TimeoutError:
            return SendResult(SendStatus.FAILED, SendRejectReason.PLATFORM_REJECTED.value,
                              fix_hint="profile 锁被监听操作占用——稍后重试（busy）")
        try:
            return await self._send_locked(room_id, content)
        finally:
            self._engine._profile_lock.release()

    async def _send_locked(self, room_id: str, content: str) -> SendResult:
        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(
                self._engine._profile_dir(), headless=True,
                user_agent=self._engine_UA(),
                viewport={"width": 1280, "height": 800},
                args=["--disable-blink-features=AutomationControlled",
                      "--disable-setuid-sandbox", "--hide-crash-restore-bubble"])
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                try:
                    await page.goto(self._room_url(room_id), timeout=PAGE_TIMEOUT_MS,
                                    wait_until="domcontentloaded")
                except Exception as e:  # noqa: BLE001
                    return SendResult(SendStatus.UNKNOWN, SendRejectReason.SEND_TIMEOUT.value,
                                      detail=f"goto: {type(e).__name__}")
                topic = await self._wait_topic(page)
                if not topic:
                    return SendResult(SendStatus.FAILED, SendRejectReason.PLATFORM_REJECTED.value,
                                      fix_hint="未能从页面锚定 topic（未开播/未登录/加载慢）——"
                                               "确认房间监听状态后重试；持续失败跑 tools/send_probes/taobao_mtop_capture.py capture",
                                      docs_anchor="docs/testing/m0-send-probe-cards.md")
                if not await self._wait_mtop_lib(page):
                    return SendResult(SendStatus.FAILED, SendRejectReason.ROUTE_UNVERIFIED.value,
                                      fix_hint="页面 mtop 库不可达（window.lib.mtop 缺失）——页面结构变更，重跑 T1 探针",
                                      docs_anchor="docs/testing/m0-send-probe-cards.md")
                result = await page.evaluate(
                    EVAL_SEND_JS,
                    {"api": PUBLISH_API, "v": PUBLISH_VERSION, "appKey": PUBLISH_APPKEY,
                     "data": {"topic": topic, "content": content}})
                return self._map_ret(result)
            finally:
                try:
                    await context.close()
                except Exception:  # noqa: BLE001
                    pass

    def _room_url(self, room_id: str) -> str:
        from danmaku_listener.engines.protocol.mtop import extract_live_id
        live_id = extract_live_id(room_id)
        return self._engine.LIVE_URL_TEMPLATE.format(live_id=live_id)

    @staticmethod
    def _engine_UA() -> str:
        """与 taobao 引擎同源 UA（taobao.py UA 常量——凭证提取/发送一致，R17 纪律）"""
        from danmaku_listener.engines.protocol.taobao import UA
        return UA

    async def _wait_mtop_lib(self, page) -> bool:
        deadline = time.monotonic() + MTOP_LIB_WAIT_S
        while time.monotonic() < deadline:
            try:
                if await page.evaluate(EVAL_LIB_PROBE_JS):
                    return True
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(1)
        return False

    async def _wait_topic(self, page) -> Optional[str]:
        """页面请求锚定 topic（与 taobao.py:409-425 TOPIC_ANCHORS 同构；不引引擎内部闭包）"""
        state = {"topic": None}

        def on_request(request) -> None:
            if state["topic"]:
                return
            u = request.url
            if "iliad" in u or "powermsg" in u:
                m = re.search(r"[?&]data=([^&]+)", u)
                raw = m.group(1) if m else (request.post_data or "")
                if raw:
                    try:
                        data = json.loads(unquote(raw))
                        if data.get("topic"):
                            state["topic"] = data["topic"]
                    except json.JSONDecodeError:
                        pass

        page.on("request", on_request)
        deadline = time.monotonic() + TOPIC_WAIT_S
        while state["topic"] is None and time.monotonic() < deadline:
            await asyncio.sleep(1)
        page.remove_listener("request", on_request)
        return state["topic"]

    @staticmethod
    def _map_ret(result: dict[str, Any]) -> SendResult:
        """ret 五路径映射（CEO-F4/DX-D5——禁止一律落 NEEDS_LOGIN 误导排障）"""
        if result.get("error") == "mtop lib not found":
            return SendResult(SendStatus.FAILED, SendRejectReason.ROUTE_UNVERIFIED.value,
                              fix_hint="页面 mtop 库不可达——页面结构变更，重跑 T1 探针",
                              docs_anchor="docs/testing/m0-send-probe-cards.md")
        ret_list = result.get("ret") or []
        if result.get("rejected") and not ret_list:
            return SendResult(SendStatus.FAILED, SendRejectReason.PLATFORM_REJECTED.value,
                              detail=f"mtop 调用异常: {result.get('detail', '')[:120]}",
                              fix_hint="页面 mtop 调用异常——重跑 T1 探针核对形态")
        ret_str = "; ".join(str(r) for r in ret_list)
        if any("SUCCESS" in r for r in ret_list):
            return SendResult(SendStatus.SENT, sent_at=int(time.time()))
        if any(p in ret_str for p in RET_RISK_PATTERNS):
            return SendResult(SendStatus.FAILED, SendRejectReason.PLATFORM_REJECTED.value,
                              detail=f"ret={ret_str[:160]}",
                              fix_hint="风控拦截（RGV587/x5sec 类）——降低发送频率稍后重试；勿重扫码（登录态未失效）")
        if any(p in ret_str for p in RET_LOGIN_PATTERNS):
            return SendResult(SendStatus.FAILED, SendRejectReason.PLATFORM_REJECTED.value,
                              detail=f"ret={ret_str[:160]}",
                              fix_hint="登录态失效——重跑淘宝登录窗口后重试",
                              docs_anchor="docs/ops/send-runbook.md")
        if any(p in ret_str for p in ("FAIL_SYS_PARAM", "ILLEGAL", "参数")):
            return SendResult(SendStatus.FAILED, SendRejectReason.PLATFORM_REJECTED.value,
                              detail=f"ret={ret_str[:160]}",
                              fix_hint="参数错误——data 结构可能变更，重跑 T1 探针核对")
        # 路径 5：未知 ret 保守 FAIL + 原始码透传（DX-D5）
        return SendResult(SendStatus.FAILED, SendRejectReason.PLATFORM_REJECTED.value,
                          detail=f"未知 ret={ret_str[:160]}",
                          fix_hint="未知返回码——透传详情排障；持续出现重跑 T1 探针")
