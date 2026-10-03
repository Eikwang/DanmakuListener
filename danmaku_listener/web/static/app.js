/**
 * DanmakuListener 测试控制台 v2 — 契约 v1 前端
 *
 * 消息处理：category 分流（business 八类徽章 / system 八种告警与指示）
 * 统计：按类型计数、msg/s（10s 滚动窗口）、按房间分组、引擎标识
 * 观测：TTHW、消息 timestamp 与本地时钟差
 */

// 九类徽章色板（与 style.css 变量对应）
const TYPE_COLORS = {
  DANMU: "var(--type-danmu)",
  GIFT: "var(--type-gift)",
  SUPER_CHAT: "var(--type-super-chat)",
  ENTER_ROOM: "var(--type-enter)",
  LIKE: "var(--type-like)",
  LIVE_STATUS_CHANGE: "var(--type-live)",
  ROOM_STATS: "var(--type-stats)",
  SOCIAL: "var(--type-social)",
};

const BUSINESS_TYPES = Object.keys(TYPE_COLORS);
const SYSTEM_TYPES = [
  "HEARTBEAT", "ROOM_STATUS", "GAP", "NEEDS_LOGIN",
  "ENGINE_STATUS", "BACKPRESSURE", "ROUTE_FAILED", "RECOVERED",
];

class DanmakuApp {
  constructor() {
    this.ws = null;
    this.reconnectTimer = null;
    this.reconnectDelay = 3000;
    this.autoScroll = true;
    this.maxDanmakuItems = 500;

    // 契约统计
    this.typeCounts = {};        // type -> count（business）
    this.roomCounts = {};        // room_id -> count
    this.roomSeq = {};           // room_id -> last seq（连续性观察）
    this.rateWindow = [];        // 最近 10s 时间戳
    this.currentEngine = "—";
    this.typeFilter = new Set(); // 空集合=全部显示

    this.init();
  }

  init() {
    this.connectWebSocket();
    this.bindEvents();
    this.loadInitialState();
    this.renderTypeFilter();
    // msg/s 滚动窗口刷新（10s 窗口，每秒重算）
    setInterval(() => this.updateRate(), 1000);
  }

  connectWebSocket() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${location.host}/ws`;
    try {
      this.ws = new WebSocket(wsUrl);
      this.ws.onopen = () => this.setStatus("connected");
      this.ws.onmessage = (event) => this.handleMessage(JSON.parse(event.data));
      this.ws.onclose = () => {
        this.setStatus("disconnected");
        this.reconnectTimer = setTimeout(() => this.connectWebSocket(), this.reconnectDelay);
      };
      this.ws.onerror = () => this.setStatus("error");
    } catch (e) {
      this.setStatus("error");
    }
  }

  setStatus(state) {
    const dot = document.getElementById("status-indicator");
    const text = document.getElementById("status-text");
    dot.className = "status-dot " + (state === "connected" ? "connected" : state === "error" ? "error" : "disconnected");
    text.textContent = state === "connected" ? "已连接" : state === "error" ? "连接错误" : "未连接（重连中…）";
  }

  // ===== 契约消息处理核心 =====

  handleMessage(msg) {
    if (!msg || !msg.category) return; // additive-only：无 category 的未知消息忽略

    if (msg.category === "business") {
      this.handleBusiness(msg);
    } else if (msg.category === "system") {
      this.handleSystem(msg);
    } else {
      // 未知 category：忽略并计数（additive-only 消费语义）
      console.warn("unknown category", msg.category);
    }
    this.updateStats(msg);
  }

  handleBusiness(msg) {
    const type = msg.type;
    this.typeCounts[type] = (this.typeCounts[type] || 0) + 1;
    if (this.typeFilter.size && !this.typeFilter.has(type)) return; // 过滤 chips

    const p = msg.payload || {};
    let content = "";
    let extra = "";
    switch (type) {
      case "DANMU":
        content = `${p.user_name}: ${p.content}`;
        break;
      case "GIFT":
        content = `${p.user_name} 送出 ${p.gift_name} x${p.gift_count}`;
        extra = p.gift_value ? ` (价值 ${p.gift_value})` : "";
        break;
      case "SUPER_CHAT":
        content = `SC ¥${p.price} ${p.user_name}: ${p.content}`;
        break;
      case "ENTER_ROOM":
        content = `${p.user_name} 进入直播间`;
        break;
      case "LIKE":
        content = `${p.user_name || "有人"} 点赞 x${p.count}`;
        break;
      case "LIVE_STATUS_CHANGE":
        content = p.live ? "直播开始" : "直播结束";
        break;
      case "ROOM_STATS":
        content = `观看 ${p.viewer_count ?? "—"} · 点赞 ${p.total_likes ?? "—"}`;
        break;
      case "SOCIAL":
        content = `${p.user_name} ${p.action}`;
        break;
      default:
        content = JSON.stringify(p); // 未知类型透传（additive-only）
    }

    const room = `${msg.platform}:${msg.room_id}`;
    const clockSkew = Math.abs(Math.floor(Date.now() / 1000) - msg.timestamp);
    const skewNote = clockSkew > 5 ? ` (时钟差${clockSkew}s)` : "";
    this.appendDanmaku(`${room} | ${content}${extra}`, type, msg.timestamp, skewNote);
  }

  handleSystem(msg) {
    const type = msg.type;
    const p = msg.payload || {};

    switch (type) {
      case "HEARTBEAT":
        // 心跳只在统计面板体现（不打进弹幕流）
        this.refreshEngineDisplay();
        return;
      case "GAP":
        this.showAlert(
          "warn",
          `数据缺口 ${new Date(p.window_start * 1000).toLocaleTimeString()} ~ ` +
          `${new Date(p.window_end * 1000).toLocaleTimeString()}（${p.reason}${p.approx ? ", 近似" : ""}` +
          `${p.dropped_estimate != null ? `, 疑似丢失 ${p.dropped_estimate} 条` : ""}）`
        );
        this.appendGapMarker(p);
        break;
      case "NEEDS_LOGIN": {
        const f = p.failure || {};
        this.showAlert(
          "login",
          `需要登录：${f.fix_hint || ""}（${f.reason_code}）`,
          f.docs_anchor
        );
        const il = p.interactive_login;
        if (il && il.qr_image_b64) {
          this.showQr(il.qr_image_b64);
        } else if (il && il.login_url) {
          this.showAlert("login", `登录链接：<a href="${il.login_url}" target="_blank">${il.login_url}</a>`);
        }
        break;
      }
      case "ENGINE_STATUS":
        if (p.engine) this.currentEngine = p.engine;
        if (p.detail) this.showAlert("info", `引擎状态：${p.detail}`);
        this.refreshEngineDisplay();
        break;
      case "BACKPRESSURE": {
        const dropped = Object.entries(p.dropped_by_type || {})
          .map(([t, n]) => `${t}:${n}`).join(", ");
        this.showAlert("warn", `背压丢弃（${new Date(p.window_start * 1000).toLocaleTimeString()} 窗口）：${dropped}`);
        break;
      }
      case "ROUTE_FAILED": {
        const f = p.failure || {};
        const link = f.docs_anchor
          ? ` <a href="/static/${f.docs_anchor}" target="_blank">手册</a>`
          : "";
        this.showAlert("route", `路线失效 ${f.reason_code}：${f.fix_hint}.${link}`);
        break;
      }
      case "RECOVERED":
        this.showAlert("ok", `引擎已恢复（故障持续 ${p.after_seconds}s）`);
        break;
      case "LIVE_STATUS_CHANGE":
        // 直播状态变化（开播/下播）——观看/点赞数据由 ROOM_STATS 承载
        this.showAlert(p.live ? "ok" : "info",
                       `直播状态：${p.live ? "直播中" : "未直播"}（raw=${p.raw_status}）`);
        break;
      default:
        this.showAlert("info", `未知系统消息 ${type}（additive-only，已忽略载荷）`);
    }
    this.refreshEngineDisplay();
  }

  // ===== 渲染 =====

  appendDanmaku(text, type, ts, skewNote = "") {
    const container = document.getElementById("danmaku-container");
    document.getElementById("empty-state")?.remove();

    const item = document.createElement("div");
    item.className = "danmaku-item";
    const badge = document.createElement("span");
    badge.className = "type-badge";
    badge.textContent = type;
    badge.style.background = TYPE_COLORS[type] || "var(--text-secondary)";
    const body = document.createElement("span");
    body.className = "danmaku-text";
    body.textContent = text + skewNote;
    item.append(badge, body);

    if (this.autoScroll) container.appendChild(item);
    else container.appendChild(item);

    while (container.children.length > this.maxDanmakuItems) {
      container.removeChild(container.firstChild);
    }
    if (this.autoScroll) container.scrollTop = container.scrollHeight;
  }

  appendGapMarker(gapPayload) {
    const container = document.getElementById("danmaku-container");
    const marker = document.createElement("div");
    marker.className = "gap-marker";
    marker.textContent = `── 缺口 ${gapPayload.reason}（${gapPayload.window_start} ~ ${gapPayload.window_end}）──`;
    container.appendChild(marker);
    if (this.autoScroll) container.scrollTop = container.scrollHeight;
  }

  showAlert(level, html, link = null) {
    const bar = document.getElementById("alert-bar");
    const item = document.createElement("div");
    item.className = `alert alert-${level}`;
    item.innerHTML = `<span>${html}${link ? ` <a href="/static/${link}" target="_blank">手册</a>` : ""}</span>`;
    const close = document.createElement("button");
    close.className = "alert-close";
    close.textContent = "×";
    close.setAttribute("aria-label", "关闭告警");
    close.onclick = () => item.remove();
    item.appendChild(close);
    bar.prepend(item);
    while (bar.children.length > 5) bar.removeChild(bar.lastChild);
  }

  showQr(b64) {
    const bar = document.getElementById("alert-bar");
    const item = document.createElement("div");
    item.className = "alert alert-login qr";
    const img = document.createElement("img");
    img.src = `data:image/png;base64,${b64}`;
    img.alt = "登录二维码";
    img.width = 160;
    item.appendChild(img);
    const note = document.createElement("span");
    note.textContent = "用微信扫码重新登录管理后台";
    item.appendChild(note);
    bar.prepend(item);
  }

  // ===== 统计 =====

  updateStats(msg) {
    this.roomCounts[`${msg.platform}:${msg.room_id}`] =
      (this.roomCounts[`${msg.platform}:${msg.room_id}`] || 0) + 1;
    if (msg.category === "business") {
      this.rateWindow.push(Date.now());
    }
    // seq 连续性观察（按房间）
    if (msg.category === "business" && typeof msg.seq === "number") {
      const key = msg.room_id;
      const last = this.roomSeq[key];
      if (last != null && msg.seq > last + 1) {
        console.warn(`seq gap on ${key}: ${last} -> ${msg.seq}（等待 GAP 确认）`);
      }
      this.roomSeq[key] = msg.seq;
    }
    this.renderStats();
  }

  updateRate() {
    const now = Date.now();
    this.rateWindow = this.rateWindow.filter((t) => now - t < 10000);
    const rate = (this.rateWindow.length / 10).toFixed(1);
    document.getElementById("stats-rate").textContent = `${rate} msg/s`;
    this.refreshEngineDisplay();
  }

  refreshEngineDisplay() {
    document.getElementById("stats-engine").textContent = this.currentEngine;
  }

  renderStats() {
    const typesEl = document.getElementById("stats-types");
    typesEl.innerHTML = "";
    for (const [type, count] of Object.entries(this.typeCounts)) {
      const row = document.createElement("div");
      row.className = "stats-row";
      const dot = document.createElement("span");
      dot.className = "type-badge";
      dot.textContent = type;
      dot.style.background = TYPE_COLORS[type] || "var(--text-secondary)";
      const num = document.createElement("span");
      num.className = "stats-value";
      num.textContent = count;
      row.append(dot, num);
      typesEl.appendChild(row);
    }

    const roomsEl = document.getElementById("stats-rooms");
    roomsEl.innerHTML = "";
    for (const [room, count] of Object.entries(this.roomCounts)) {
      const row = document.createElement("div");
      row.className = "stats-row";
      row.innerHTML = `<span class="stats-label">${room}</span><span class="stats-value">${count}</span>`;
      roomsEl.appendChild(row);
    }
  }

  renderTypeFilter() {
    const filter = document.getElementById("type-filter");
    for (const type of BUSINESS_TYPES) {
      const chip = document.createElement("button");
      chip.className = "filter-chip active";
      chip.textContent = type;
      chip.style.borderColor = TYPE_COLORS[type];
      chip.onclick = () => {
        if (this.typeFilter.has(type)) {
          this.typeFilter.delete(type);
          chip.classList.add("active");
        } else {
          this.typeFilter.add(type);
          chip.classList.remove("active");
        }
      };
      filter.appendChild(chip);
    }
  }

  // ===== 既有交互（房间/代理/关键词，保留） =====

  bindEvents() {
    document.getElementById("add-room-btn")?.addEventListener("click", () => this.addRoom());
    document.getElementById("room-input")?.addEventListener("keypress", (e) => {
      if (e.key === "Enter") this.addRoom();
    });
    document.getElementById("stop-all-btn")?.addEventListener("click", () => this.stopAll());
    document.getElementById("scroll-toggle-btn")?.addEventListener("click", (e) => {
      this.autoScroll = !this.autoScroll;
      e.target.textContent = this.autoScroll ? "暂停滚动" : "恢复滚动";
    });
    document.getElementById("add-keyword-btn")?.addEventListener("click", () => this.addKeyword());
    document.getElementById("settings-toggle-btn")?.addEventListener("click", (e) => {
      const body = document.getElementById("settings-body");
      const hidden = body.classList.toggle("hidden");
      e.target.textContent = hidden ? "展开" : "收起";
      e.target.setAttribute("aria-expanded", String(!hidden));
    });
    document.getElementById("save-config-btn")?.addEventListener("click", () => this.saveConfig());
    document.getElementById("keyword-toggle")?.addEventListener("change", (e) => {
      this.api("/api/keywords/toggle", "PUT", { enabled: e.target.checked }).then(() => this.loadKeywords());
    });
  }

  async api(path, method = "GET", body = null) {
    const opts = { method, headers: { "Content-Type": "application/json" } };
    if (body) opts.body = JSON.stringify(body);
    const resp = await fetch(path, opts);
    return resp.json();
  }

  async addRoom() {
    const input = document.getElementById("room-input");
    const errEl = document.getElementById("room-error");
    errEl.classList.add("hidden");
    try {
      const data = await this.api("/api/rooms", "POST", { room: input.value });
      if (data.status === "login_required") {
        errEl.textContent = data.message || "需要登录：请在弹出的浏览器窗口中登录账号";
        errEl.classList.remove("hidden");
        errEl.classList.add("login-hint");
        return; // 登录完成后引擎自动开始监听
      }
      input.value = "";
      this.loadRooms();
    } catch (e) {
      errEl.textContent = "添加失败";
      errEl.classList.remove("hidden");
    }
  }

  async stopAll() {
    await this.api("/api/rooms/stop-all", "POST");
    this.loadRooms();
  }

  async addKeyword() {
    const input = document.getElementById("keyword-input");
    if (!input.value) return;
    await this.api("/api/keywords", "POST", { keyword: input.value });
    input.value = "";
    this.loadKeywords();
  }

  async loadConfig() {
    try {
      const data = await this.api("/api/config");
      for (const [key, value] of Object.entries(data.config || {})) {
        const input = document.getElementById(`cfg-${key}`);
        if (input) input.value = value;
      }
      const src = document.getElementById("data-source");
      if (src && data.source === "config.local.toml") src.textContent = "配置: config.local.toml";
    } catch (e) { /* config 可选 */ }
  }

  async saveConfig() {
    const msg = document.getElementById("settings-msg");
    const fields = ["ws_port", "web_port", "max_rooms", "fast_retry_max",
                    "slow_retry_cap_seconds", "bus_ring_capacity",
                    "bus_dedup_window_seconds", "session_lifetime_seconds"];
    const config = {};
    for (const f of fields) {
      const el = document.getElementById(`cfg-${f}`);
      if (el && el.value !== "") config[f] = Number(el.value);
    }
    try {
      const resp = await this.api("/api/config", "PUT", { config });
      if (resp.success) {
        msg.textContent = "已保存（需重启服务生效）";
        msg.className = "settings-msg ok";
      } else {
        msg.textContent = resp.error || "保存失败";
        msg.className = "settings-msg err";
      }
    } catch (e) {
      msg.textContent = `保存失败: ${e}`;
      msg.className = "settings-msg err";
    }
    msg.classList.remove("hidden");
  }

  async loadRooms() {
    const data = await this.api("/api/rooms");
    const list = document.getElementById("room-list");
    list.innerHTML = "";
    const rooms = data.rooms || data || [];
    for (const key of Object.keys(rooms)) {
      const li = document.createElement("li");
      li.className = "room-item";
      li.innerHTML = `<span>${key}</span>`;
      const del = document.createElement("button");
      del.textContent = "×";
      del.className = "room-del";
      del.setAttribute("aria-label", `移除 ${key}`);
      const [platform, roomId] = key.split(":");
      del.onclick = async () => {
        await this.api(`/api/rooms/${platform}/${roomId}`, "DELETE");
        this.loadRooms();
      };
      li.appendChild(del);
      list.appendChild(li);
    }
    document.getElementById("stop-all-btn").disabled = Object.keys(rooms).length === 0;
  }

  async loadKeywords() {
    const data = await this.api("/api/keywords");
    const list = document.getElementById("keyword-list");
    list.innerHTML = "";
    for (const kw of data.keywords || []) {
      const li = document.createElement("li");
      li.textContent = kw;
      const del = document.createElement("button");
      del.textContent = "×";
      del.className = "room-del";
      del.onclick = async () => {
        await this.api(`/api/keywords/${encodeURIComponent(kw)}`, "DELETE");
        this.loadKeywords();
      };
      li.appendChild(del);
      list.appendChild(li);
    }
    const toggle = document.getElementById("keyword-toggle");
    if (toggle) toggle.checked = data.enabled !== false;
  }

  async loadInitialState() {
    await this.loadRooms();
    await this.loadKeywords();
    await this.loadConfig();
    try {
      const status = await this.api("/api/status");
      if (status.message_count != null) {
        document.getElementById("stats-rate").textContent = `累计 ${status.message_count} 条`;
      }
    } catch (e) { /* status 可选 */ }
  }
}

window.addEventListener("DOMContentLoaded", () => new DanmakuApp());
