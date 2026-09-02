/**
 * DanmakuListener Web - 前端应用
 *
 * 负责页面交互、WebSocket 通信、API 调用。
 */

class DanmakuApp {
    constructor() {
        this.ws = null;
        this.reconnectTimer = null;
        this.reconnectDelay = 3000;  // 3秒重连 → AC-012
        this.autoScroll = true;
        this.maxDanmakuItems = 500;

        this.init();
    }

    /** 初始化应用 */
    init() {
        this.connectWebSocket();
        this.bindEvents();
        this.loadInitialState();
    }

    /** 建立 WebSocket 连接 */
    connectWebSocket() {
        const protocol = location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${protocol}//${location.host}/ws`;

        try {
            this.ws = new WebSocket(wsUrl);
        } catch (e) {
            this.updateConnectionStatus(false);
            this.scheduleReconnect();
            return;
        }

        this.ws.onopen = () => {
            this.updateConnectionStatus(true);
        };

        this.ws.onclose = () => {
            this.updateConnectionStatus(false);
            this.scheduleReconnect();
        };

        this.ws.onerror = () => {
            this.updateConnectionStatus(false);
        };

        this.ws.onmessage = (event) => {
            this.handleMessage(event.data);
        };
    }

    /** 安排重连 */
    scheduleReconnect() {
        if (this.reconnectTimer) return;
        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            this.connectWebSocket();
        }, this.reconnectDelay);
    }

    /** 更新连接状态显示 */
    updateConnectionStatus(connected) {
        const indicator = document.getElementById("status-indicator");
        const text = document.getElementById("status-text");
        if (indicator) {
            indicator.className = `status-dot ${connected ? "connected" : "disconnected"}`;
        }
        if (text) {
            text.textContent = connected ? "已连接" : "未连接";
        }
    }

    /** 处理收到的消息 */
    handleMessage(rawData) {
        try {
            const msg = JSON.parse(rawData);
            switch (msg.type) {
                case "danmaku":
                    this.addDanmaku(msg.data);
                    break;
                case "status":
                    this.handleStatusMessage(msg.data);
                    break;
                case "reconnect":
                    this.handleReconnectMessage(msg.data);
                    break;
            }
        } catch (e) {
            console.error("Failed to parse message:", e);
        }
    }

    /** 添加弹幕到显示区 */
    addDanmaku(data) {
        const container = document.getElementById("danmaku-container");
        if (!container) return;

        const item = document.createElement("div");
        item.className = `danmaku-item ${data.message_type || "normal"}`;

        const timestamp = data.timestamp
            ? new Date(data.timestamp * 1000).toLocaleTimeString()
            : "";

        item.innerHTML = `
            <span class="user-name">${this.escapeHtml(data.user_name || "")}</span>
            <span class="content">${this.escapeHtml(data.content || "")}</span>
            <span class="timestamp">${timestamp}</span>
        `;

        container.appendChild(item);

        // 限制最大条目数
        while (container.children.length > this.maxDanmakuItems) {
            container.removeChild(container.firstChild);
        }

        // 自动滚动
        if (this.autoScroll) {
            container.scrollTop = container.scrollHeight;
        }
    }

    /** 处理状态消息 */
    handleStatusMessage(data) {
        if (data.rooms_count !== undefined) {
            // 初始状态消息，可能包含房间信息
        }
    }

    /** 处理重连消息 */
    handleReconnectMessage(data) {
        // 更新房间状态显示
        this.loadRooms();
    }

    /** 加载初始状态 */
    async loadInitialState() {
        await this.loadRooms();
        await this.loadProxyStatus();
        await this.loadKeywords();
    }

    /** 加载房间列表 */
    async loadRooms() {
        try {
            const data = await this.apiRequest("GET", "/api/rooms");
            this.renderRoomList(data.rooms || []);
        } catch (e) {
            console.error("Failed to load rooms:", e);
        }
    }

    /** 渲染房间列表 */
    renderRoomList(rooms) {
        const list = document.getElementById("room-list");
        if (!list) return;

        list.innerHTML = "";
        for (const room of rooms) {
            const li = document.createElement("li");
            li.className = "room-item";
            li.innerHTML = `
                <div>
                    <span class="platform-tag">${this.escapeHtml(room.platform)}</span>
                    <span class="room-id">${this.escapeHtml(room.room_id)}</span>
                </div>
                <div>
                    <span class="status-badge ${room.status}">${room.status === "running" ? "运行中" : "已停止"}</span>
                    <button class="stop-room-btn" data-platform="${this.escapeHtml(room.platform)}" data-room-id="${this.escapeHtml(room.room_id)}">停止</button>
                </div>
            `;
            list.appendChild(li);
        }

        // 更新全部停止按钮状态
        const stopAllBtn = document.getElementById("stop-all-btn");
        if (stopAllBtn) {
            stopAllBtn.disabled = rooms.length === 0;
        }
    }

    /** 加载代理状态 */
    async loadProxyStatus() {
        try {
            const data = await this.apiRequest("GET", "/api/proxy/status");
            this.updateProxyUI(data);
        } catch (e) {
            console.error("Failed to load proxy status:", e);
        }
    }

    /** 更新代理 UI */
    updateProxyUI(data) {
        const toggle = document.getElementById("proxy-toggle");
        const statusText = document.getElementById("proxy-status-text");
        const address = document.getElementById("proxy-address");

        if (toggle) {
            toggle.checked = data.enabled || false;
        }
        if (statusText) {
            statusText.textContent = data.enabled ? "已启用" : "已禁用";
        }
        if (address) {
            address.textContent = data.enabled ? `${data.host}:${data.port}` : "";
        }
    }

    /** 加载关键词列表 */
    async loadKeywords() {
        try {
            const data = await this.apiRequest("GET", "/api/keywords");
            this.renderKeywordList(data.keywords || []);
            const toggle = document.getElementById("keyword-filter-toggle");
            if (toggle) {
                toggle.checked = data.enabled !== false;
            }
        } catch (e) {
            console.error("Failed to load keywords:", e);
        }
    }

    /** 渲染关键词列表 */
    renderKeywordList(keywords) {
        const list = document.getElementById("keyword-list");
        if (!list) return;

        list.innerHTML = "";
        for (const kw of keywords) {
            const tag = document.createElement("span");
            tag.className = "keyword-tag";
            tag.innerHTML = `
                ${this.escapeHtml(kw)}
                <span class="remove-btn" data-keyword="${this.escapeHtml(kw)}">&times;</span>
            `;
            list.appendChild(tag);
        }
    }

    /** 绑定事件 */
    bindEvents() {
        // 添加房间按钮
        const addRoomBtn = document.getElementById("add-room-btn");
        const roomInput = document.getElementById("room-input");
        if (addRoomBtn) {
            addRoomBtn.addEventListener("click", () => this.handleAddRoom());
        }
        if (roomInput) {
            roomInput.addEventListener("keypress", (e) => {
                if (e.key === "Enter") this.handleAddRoom();
            });
            // 失焦时校验格式
            roomInput.addEventListener("blur", () => this.validateRoomInput());
        }

        // 全部停止按钮
        const stopAllBtn = document.getElementById("stop-all-btn");
        if (stopAllBtn) {
            stopAllBtn.addEventListener("click", () => this.handleStopAll());
        }

        // 房间列表中的停止按钮（事件委托）
        const roomList = document.getElementById("room-list");
        if (roomList) {
            roomList.addEventListener("click", (e) => {
                const btn = e.target.closest(".stop-room-btn");
                if (btn) {
                    this.handleRemoveRoom(btn.dataset.platform, btn.dataset.roomId);
                }
            });
        }

        // 代理开关
        const proxyToggle = document.getElementById("proxy-toggle");
        if (proxyToggle) {
            proxyToggle.addEventListener("change", () => this.handleProxyToggle());
        }

        // 关键词添加
        const addKwBtn = document.getElementById("add-keyword-btn");
        const kwInput = document.getElementById("keyword-input");
        if (addKwBtn) {
            addKwBtn.addEventListener("click", () => this.handleAddKeyword());
        }
        if (kwInput) {
            kwInput.addEventListener("keypress", (e) => {
                if (e.key === "Enter") this.handleAddKeyword();
            });
        }

        // 关键词删除（事件委托）
        const kwList = document.getElementById("keyword-list");
        if (kwList) {
            kwList.addEventListener("click", (e) => {
                const btn = e.target.closest(".remove-btn");
                if (btn) {
                    this.handleRemoveKeyword(btn.dataset.keyword);
                }
            });
        }

        // 关键词过滤开关
        const kwToggle = document.getElementById("keyword-filter-toggle");
        if (kwToggle) {
            kwToggle.addEventListener("change", () => this.handleKeywordToggle());
        }

        // 弹幕滚动控制
        const scrollBtn = document.getElementById("scroll-toggle-btn");
        if (scrollBtn) {
            scrollBtn.addEventListener("click", () => {
                this.autoScroll = !this.autoScroll;
                scrollBtn.textContent = this.autoScroll ? "暂停滚动" : "恢复滚动";
            });
        }
    }

    /** 校验房间输入格式 */
    validateRoomInput() {
        const input = document.getElementById("room-input");
        const error = document.getElementById("room-error");
        if (!input || !error) return;

        const val = input.value.trim();
        if (!val) {
            error.classList.add("hidden");
            return;
        }

        // 格式：platform:room_id
        if (!val.includes(":")) {
            error.textContent = "格式不正确，应为 platform:room_id";
            error.classList.remove("hidden");
        } else {
            error.classList.add("hidden");
        }
    }

    /** 处理添加房间 */
    async handleAddRoom() {
        const input = document.getElementById("room-input");
        const error = document.getElementById("room-error");
        const addBtn = document.getElementById("add-room-btn");
        if (!input) return;

        const room = input.value.trim();
        if (!room) return;

        // 置灰防重复提交
        if (addBtn) addBtn.disabled = true;

        try {
            const resp = await fetch("/api/rooms", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ room }),
            });
            const data = await resp.json();

            if (resp.ok) {
                input.value = "";
                if (error) error.classList.add("hidden");
                await this.loadRooms();
            } else {
                // 显示错误
                if (error) {
                    if (resp.status === 409) {
                        error.textContent = "该房间已存在";
                    } else {
                        error.textContent = data.error || "添加失败";
                    }
                    error.classList.remove("hidden");
                }
            }
        } catch (e) {
            if (error) {
                error.textContent = "请求失败，请检查网络连接";
                error.classList.remove("hidden");
            }
        } finally {
            if (addBtn) addBtn.disabled = false;
        }
    }

    /** 处理移除房间 */
    async handleRemoveRoom(platform, roomId) {
        try {
            await this.apiRequest("DELETE", `/api/rooms/${platform}/${roomId}`);
            await this.loadRooms();
        } catch (e) {
            console.error("Failed to remove room:", e);
        }
    }

    /** 处理全部停止 */
    async handleStopAll() {
        const btn = document.getElementById("stop-all-btn");
        if (btn) btn.disabled = true;

        try {
            await this.apiRequest("POST", "/api/rooms/stop-all");
            await this.loadRooms();
            await this.loadProxyStatus();
        } catch (e) {
            console.error("Failed to stop all:", e);
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    /** 处理代理开关 */
    async handleProxyToggle() {
        const toggle = document.getElementById("proxy-toggle");
        if (!toggle) return;

        const endpoint = toggle.checked ? "/api/proxy/enable" : "/api/proxy/disable";
        try {
            const data = await this.apiRequest("POST", endpoint);
            this.updateProxyUI(data);
        } catch (e) {
            console.error("Failed to toggle proxy:", e);
            // 恢复原状态
            toggle.checked = !toggle.checked;
        }
    }

    /** 处理添加关键词 */
    async handleAddKeyword() {
        const input = document.getElementById("keyword-input");
        if (!input) return;

        const keyword = input.value.trim();
        if (!keyword || keyword.length > 50) return;

        try {
            await this.apiRequest("POST", "/api/keywords", { keyword });
            input.value = "";
            await this.loadKeywords();
        } catch (e) {
            console.error("Failed to add keyword:", e);
        }
    }

    /** 处理删除关键词 */
    async handleRemoveKeyword(keyword) {
        try {
            await this.apiRequest("DELETE", `/api/keywords/${encodeURIComponent(keyword)}`);
            await this.loadKeywords();
        } catch (e) {
            console.error("Failed to remove keyword:", e);
        }
    }

    /** 处理关键词过滤开关 */
    async handleKeywordToggle() {
        const toggle = document.getElementById("keyword-filter-toggle");
        if (!toggle) return;

        try {
            await this.apiRequest("PUT", "/api/keywords/toggle", { enabled: toggle.checked });
        } catch (e) {
            console.error("Failed to toggle keyword filter:", e);
            toggle.checked = !toggle.checked;
        }
    }

    /** HTML 转义 */
    escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    }

    /** API 请求封装 */
    async apiRequest(method, path, body = null) {
        const opts = {
            method,
            headers: { "Content-Type": "application/json" },
        };
        if (body) {
            opts.body = JSON.stringify(body);
        }
        const resp = await fetch(path, opts);
        return resp.json();
    }
}

// 页面加载完成后初始化
document.addEventListener("DOMContentLoaded", () => {
    window.app = new DanmakuApp();
});
