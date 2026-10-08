// tests/js/reconcile-after-abort.test.mjs
// ─────────────────────────────────────────────────────────────────────────────
// 目标：danmaku_listener/web/static/app.js 的
//   async reconcileAfterAbort(resultEl, inputEl, requestId)
// （中止后对账，T4/CEO-5：宽限 2s → 按 request_id 单次 GET /api/send-results →
//   回显真实结果；查不到 / 无 token / 请求失败则回落「发送超时·结果待对账」）。
//
// 提取策略（防漂移）：app.js 为浏览器脚本、无模块导出。本测试从 app.js 源文本按
// 精确签名锚点切出【真实上线方法体】，经 new Function 注入影子依赖
// （fetch / localStorage / setTimeout）与同源提取的 SEND_TIMEOUT_MS、
// SEND_REASON_NAMES 后构造执行。不复制实现、不改任何生产代码；
// 签名、常量锚点、或 sendFromRoom 的两处 AbortError→reconcileAfterAbort 接线
// 发生漂移时，本文件在加载期即整体显式失败（fail-loud），绝不静默跳过。
//
// 运行：node --test "tests/js/*.test.mjs"  （Node ≥21——--test 的 glob 支持需 v21+；旧版逐文件运行；
//   仅内置 test runner，零依赖；glob 形态跨平台稳妥——目录形态会被当作模块路径）
// ─────────────────────────────────────────────────────────────────────────────

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP_JS = path.resolve(HERE, "..", "..", "danmaku_listener", "web", "static", "app.js");

const SIGNATURE = "async reconcileAfterAbort(resultEl, inputEl, requestId) {";
const CALL_SITE = "await this.reconcileAfterAbort(resultEl, inputEl, requestId)";

/** 花括号配平切片：跳过行/块注释、单双引号字符串、模板串（含 ${} 插值）。 */
function extractBracedBody(src, openIdx) {
  const n = src.length;
  let i = openIdx;
  let depth = 0;
  const skipString = (quote) => {
    i += 1;
    while (i < n) {
      if (src[i] === "\\") { i += 2; continue; }
      if (src[i] === quote) { i += 1; return; }
      i += 1;
    }
    throw new Error("extractBracedBody: 字符串未闭合");
  };
  const skipTemplate = () => {
    i += 1;
    while (i < n) {
      if (src[i] === "\\") { i += 2; continue; }
      if (src[i] === "`") { i += 1; return; }
      if (src[i] === "$" && src[i + 1] === "{") {
        i += 2;
        let inner = 1;
        while (i < n && inner > 0) {
          if (src[i] === "'" || src[i] === '"') { skipString(src[i]); continue; }
          if (src[i] === "`") { skipTemplate(); continue; }
          if (src[i] === "{") { inner += 1; i += 1; continue; }
          if (src[i] === "}") { inner -= 1; i += 1; continue; }
          i += 1;
        }
        continue;
      }
      i += 1;
    }
    throw new Error("extractBracedBody: 模板字符串未闭合");
  };
  while (i < n) {
    const c = src[i];
    if (c === "/" && src[i + 1] === "/") {
      const end = src.indexOf("\n", i);
      i = end === -1 ? n : end + 1;
      continue;
    }
    if (c === "/" && src[i + 1] === "*") {
      const end = src.indexOf("*/", i + 2);
      i = end === -1 ? n : end + 2;
      continue;
    }
    if (c === "'" || c === '"') { skipString(c); continue; }
    if (c === "`") { skipTemplate(); continue; }
    if (c === "{") { depth += 1; i += 1; continue; }
    if (c === "}") {
      depth -= 1;
      i += 1;
      if (depth === 0) return src.slice(openIdx, i);
      continue;
    }
    i += 1;
  }
  throw new Error("extractBracedBody: 方法体花括号不平衡");
}

/** 从 app.js 提取真实方法体 + 常量 + AbortError 接线守卫；任一漂移即抛错。 */
function loadShippedMethod() {
  const src = readFileSync(APP_JS, "utf8");

  const sigIdx = src.indexOf(SIGNATURE);
  if (sigIdx === -1) {
    throw new Error(
      `[防漂移] app.js 未找到签名 \`${SIGNATURE}\`：reconcileAfterAbort 已重命名/重构，` +
      "请同步更新 tests/js/reconcile-after-abort.test.mjs 的提取锚点。"
    );
  }
  const body = extractBracedBody(src, sigIdx + SIGNATURE.length - 1);

  const timeoutMatch = src.match(/^const SEND_TIMEOUT_MS = (\d+);/m);
  if (!timeoutMatch) {
    throw new Error("[防漂移] app.js 未找到 `const SEND_TIMEOUT_MS = <n>;`，请更新测试锚点。");
  }
  const sendTimeoutMs = Number(timeoutMatch[1]);

  const graceMatch = src.match(/^const RECONCILE_GRACE_MS = (\d+);/m);
  if (!graceMatch) {
    throw new Error("[防漂移] app.js 未找到 `const RECONCILE_GRACE_MS = <n>;`，请更新测试锚点。");
  }
  const reconcileGraceMs = Number(graceMatch[1]);

  const reasonMatch = src.match(/^const SEND_REASON_NAMES = \{([\s\S]*?)\n\};/m);
  if (!reasonMatch) {
    throw new Error("[防漂移] app.js 未找到 `const SEND_REASON_NAMES = {...};`，请更新测试锚点。");
  }
  const reasonNames = new Function(`return {${reasonMatch[1]}};`)();

  const callSites = src.split(CALL_SITE).length - 1;
  if (callSites !== 2) {
    throw new Error(
      `[防漂移] sendFromRoom 中 AbortError→reconcileAfterAbort 接线期望 2 处` +
      `（fetch 层 + resp.json() 响应读取层），实际 ${callSites} 处；` +
      "中止路径必须都接入对账，若调用契约变更请同步更新本测试。"
    );
  }

  let factory;
  try {
    factory = new Function(
      "SEND_TIMEOUT_MS", "RECONCILE_GRACE_MS", "SEND_REASON_NAMES", "setTimeout", "localStorage", "fetch",
      `return { ${SIGNATURE.slice(0, -1).trim()} ${body} };`
    );
  } catch (e) {
    throw new Error(`[防漂移] 提取的方法体无法构造（切片可能失准）：${e.message}`);
  }
  return { factory, sendTimeoutMs, reconcileGraceMs, reasonNames };
}

const { factory, sendTimeoutMs, reconcileGraceMs, reasonNames } = loadShippedMethod();

// 回落文案与实现同源：秒数由提取出的 SEND_TIMEOUT_MS 推导（常量变更时断言随之联动）
const FALLBACK_TEXT = `✗ 发送超时（超过 ${sendTimeoutMs / 1000}s）· 结果待对账`;
const FALLBACK_TITLE = "结果未即时可得：稍后按 request_id 查询 GET /api/send-results 对账";

const okJson = (body) => ({ ok: true, status: 200, json: async () => body });

/** 影子环境：this 桩（记录 setRoomSendResult）、localStorage/fetch/setTimeout 影子。 */
function makeHarness({ token = "tok-1", respond } = {}) {
  const calls = [];      // setRoomSendResult 调用记录 { text, kind, title }
  const fetchCalls = []; // fetch(url, opts) 调用记录
  const graceMs = [];    // setTimeout 收到的宽限毫秒值
  const self = {
    setRoomSendResult(resultEl, text, kind, title = "") {
      calls.push({ text, kind, title });
    },
  };
  const localStorageStub = {
    getItem: (key) => (key === "send_token" && token != null ? token : null),
  };
  const setTimeoutStub = (fn, ms) => { graceMs.push(ms); fn(); return 0; };
  const fetchStub = async (url, opts) => {
    fetchCalls.push({ url, opts });
    return respond ? respond(url, opts) : okJson({ found: false });
  };
  // 用本 harness 的影子依赖完整构造方法（真实方法体 + 影子 fetch/localStorage/setTimeout）
  const method = factory(sendTimeoutMs, reconcileGraceMs, reasonNames, setTimeoutStub, localStorageStub, fetchStub)
    .reconcileAfterAbort;
  const run = (inputEl, requestId) => method.call(self, {}, inputEl, requestId);
  return { calls, fetchCalls, graceMs, run };
}

const newInput = (value = "旧内容") => ({
  value,
  focused: false,
  focus() { this.focused = true; },
});

test("① 中止对账主链路：宽限 2s → 带 Bearer 单次 GET → sent 回显 + 清空输入 + 焦点回位", async () => {
  // Value: protects=中止对账主链路：宽限2s→带Bearer单次GET /api/send-results，sent按HH:MM回显并清空输入+焦点回位; fails_when=宽限值/URL编码/Bearer头/回显文案/清空+focus任一回归; why_new=app.js无导出且仓库此前零JS测试，该分支从未被自动化覆盖; seam=none
  const sentAt = 1791532800; // 固定秒级时间戳；期望 HH:MM 由同源本地换算得出（时区无关）
  const h = makeHarness({
    respond: () => okJson({ found: true, result: { status: "sent", sent_at: sentAt } }),
  });
  const inputEl = newInput("旧内容");
  await h.run(inputEl, "ui-1 abc");

  assert.deepEqual(h.graceMs, [2000], "宽限必须恰为 2000ms");
  assert.equal(h.fetchCalls.length, 1, "对账只允许单次查询（CEO-5 兜底语义）");
  assert.equal(
    h.fetchCalls[0].url,
    "/api/send-results?request_id=ui-1%20abc",
    "request_id 须经 encodeURIComponent 拼接"
  );
  assert.equal(
    h.fetchCalls[0].opts.headers.Authorization,
    "Bearer tok-1",
    "对账请求必须携带 Bearer token"
  );

  const d = new Date(sentAt * 1000);
  const hhmm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  assert.deepEqual(h.calls, [{ text: `✓ 已发送 ${hhmm}（对账回显）`, kind: "success", title: "" }]);
  assert.equal(inputEl.value, "", "sent 回显后必须清空输入框");
  assert.equal(inputEl.focused, true, "sent 回显后焦点必须回位（连续发送）");
});

test("② found+failed：reason_code 经映射中文回显（title=原码·对账注记）；dry_run 分支", async () => {
  // Value: protects=found+failed的reason_code经SEND_REASON_NAMES映射中文回显且title=原码+对账注记；dry_run分支文案与kind=dryrun; fails_when=映射丢码回退原码/dry_run回归/fix_hint误入title/失败误清空输入; why_new=拒绝码中文文案直接面向用户，此前无任何测试锁定; seam=none
  const failed = makeHarness({
    respond: () => okJson({
      found: true,
      result: { status: "failed", reason_code: "DUPLICATE", fix_hint: "修改内容后重试" },
    }),
  });
  const input1 = newInput("旧内容");
  await failed.run(input1, "ui-2");
  assert.deepEqual(failed.calls, [{
    text: `✗ ${reasonNames.DUPLICATE}（对账回显）`,
    kind: "error",
    title: "DUPLICATE · 修改内容后重试 · 发送中止后的对账回显",
  }], "DUPLICATE 必须映射为中文文案；title 含原码+fix_hint（redteam#5 上下文入对账面）+注记");
  assert.equal(input1.value, "旧内容", "失败回显不清空输入");
  assert.equal(input1.focused, false, "失败回显不触发 focus");

  const dry = makeHarness({
    respond: () => okJson({ found: true, result: { status: "dry_run" } }),
  });
  await dry.run(newInput(), "ui-3");
  assert.deepEqual(dry.calls, [{ text: "○ dry-run 已记录（对账回显）", kind: "dryrun", title: "" }]);
});

test("③ 回落分支：found=false → 「发送超时·结果待对账」+ title 指引", async () => {
  // Value: protects=found=false回落：固定文案「发送超时（超过60s）·结果待对账」与title对账指引（秒数随SEND_TIMEOUT_MS联动）; fails_when=秒数与常量脱钩/文案或title回归/not-found误走成功分支; why_new=CEO-5兜底文案是中止场景最终用户可见结果，此前零覆盖; seam=none
  const h = makeHarness({ respond: () => okJson({ found: false }) });
  await h.run(newInput(), "ui-4");
  assert.deepEqual(h.calls, [{ text: FALLBACK_TEXT, kind: "error", title: FALLBACK_TITLE }]);
  assert.equal(h.fetchCalls.length, 1, "not-found 前已发出且仅发出一次对账请求");
});

test("④ 回落分支：无 token（localStorage 返回 null）→ 不发请求，直接回落统一文案", async () => {
  // Value: protects=无token（getItem null）时不发出对账请求、宽限先于token判断、仍回落统一文案; fails_when=无token误发未授权请求/漏回显/宽限与判断顺序倒置; why_new=守卫分支决定是否发出无凭据请求，此前无测试; seam=none
  const h = makeHarness({
    token: null,
    respond: () => { throw new Error("无 token 时不得发起对账请求"); },
  });
  await h.run(newInput(), "ui-5");
  assert.deepEqual(h.graceMs, [2000], "宽限等待先于 token 判断执行");
  assert.equal(h.fetchCalls.length, 0, "无 token 时不得发起对账请求");
  assert.deepEqual(h.calls, [{ text: FALLBACK_TEXT, kind: "error", title: FALLBACK_TITLE }]);
});

test("⑤ 回落分支：fetch 网络抛错 / HTTP 500 → 统一兜底回显，不向上抛", async () => {
  // Value: protects=fetch网络抛错与HTTP非2xx两条异常路径都收敛到同一兜底回显（不向上抛）; fails_when=异常向上逃逸成unhandled rejection/两条路径兜底文案分叉; why_new=异常收敛是中止场景最后一道防线，此前零覆盖; seam=none
  const netErr = makeHarness({
    respond: () => { throw new TypeError("fetch failed"); },
  });
  await netErr.run(newInput(), "ui-6");
  assert.equal(netErr.fetchCalls.length, 1);
  assert.deepEqual(netErr.calls, [{ text: FALLBACK_TEXT, kind: "error", title: FALLBACK_TITLE }]);

  const http500 = makeHarness({
    respond: () => ({ ok: false, status: 500, json: async () => ({}) }),
  });
  await http500.run(newInput(), "ui-7");
  assert.equal(http500.fetchCalls.length, 1);
  assert.deepEqual(http500.calls, [{ text: FALLBACK_TEXT, kind: "error", title: FALLBACK_TITLE }]);
});

// Value: protects=对账回显对 UNKNOWN 的 ？第三态渲染（结果未知≠确定失败，防盲重）; fails_when=unknown 被渲染为 ✗ error 诱导重试; why_new=ASK-C 新增第四态，此前无任何测试覆盖; seam=none
test("对账回显：unknown → ？第三态（amber，非 error）", async () => {
  const h = makeHarness({
    respond: async () => ({
      ok: true,
      json: async () => ({ found: true, result: { status: "unknown", reason_code: "SEND_TIMEOUT",
        fix_hint: "页面 mtop 调用未决——重跑 T1 探针核对形态", sent_at: null } }),
    }),
  });
  const input = newInput("");
  await h.run(input, "ui-unk");
  assert.deepEqual(h.calls, [{
    text: "？结果未知（可能已送达，对账回显）——请确认弹幕流后再重试",
    kind: "unknown",
    title: "SEND_TIMEOUT · 页面 mtop 调用未决——重跑 T1 探针核对形态 · 发送中止后的对账回显",
  }], "UNKNOWN 必须渲染为 ？第三态（kind=unknown），不得落入 ✗ error 分支");
  assert.equal(input.value, "", "unknown 不清空输入（可能已送达，重试前先确认）");
});
