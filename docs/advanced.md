# DanmakuListener 高级用法指南

## 自定义适配器

### 创建自定义适配器

所有适配器必须继承 `BaseAdapter` 并实现 `can_parse()` 和 `parse()` 方法：

```python
from typing import Any, Dict, Optional
from danmaku_listener.adapters.base import BaseAdapter
from danmaku_listener.bus.message import DanmakuMessage


class MyCustomAdapter(BaseAdapter):
    """自定义平台适配器"""

    @property
    def platform(self) -> str:
        return "my_platform"

    def can_parse(self, data: Any) -> bool:
        """判断是否能处理该数据"""
        return isinstance(data, dict) and "msg_type" in data

    async def parse(
        self, raw_data: Any, context: Optional[Dict] = None
    ) -> Optional[DanmakuMessage]:
        """解析原始数据为标准消息格式"""
        if not self.can_parse(raw_data):
            return None

        return DanmakuMessage(
            platform=context.get("platform", "my_platform") if context else "my_platform",
            room_id=context.get("room_id", "") if context else "",
            user_name=raw_data.get("user", "anonymous"),
            content=raw_data.get("text", ""),
            timestamp=raw_data.get("ts", 0),
            message_type="normal",
        )
```

### 注册自定义适配器到 Listener

修改 `_get_adapter()` 方法或使用 GenericAdapter 的自定义解析器：

```python
from danmaku_listener.adapters.generic import GenericAdapter

adapter = GenericAdapter()

# 注册自定义解析器（按消息类型）
async def my_custom_parser(data, context):
    return DanmakuMessage(
        platform="my_platform",
        room_id=context.get("room_id", ""),
        user_name=data.get("from", ""),
        content=data.get("text", ""),
        timestamp=0,
        message_type="normal",
    )

adapter.register_parser("my_msg_type", my_custom_parser)
```

---

## 自定义监听脚本

### 为平台注册 JS 监听脚本

```python
from danmaku_listener.adapters.generic import GenericAdapter

adapter = GenericAdapter()

# B站弹幕监听脚本
bilibili_script = """
(function() {
    const target = document.querySelector('.danmu-list');
    if (!target) return;

    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            mutation.addedNodes.forEach(function(node) {
                const text = node.textContent?.trim();
                const user = node.querySelector('.user-name')?.textContent?.trim();
                if (text && typeof onDanmaku === 'function') {
                    onDanmaku(JSON.stringify({
                        type: 'dom_mutation',
                        content: text,
                        user: user || 'anonymous',
                        element: node.tagName
                    }));
                }
            });
        });
    });

    observer.observe(target, { childList: true, subtree: true });
})();
"""

adapter.register_script("bilibili", bilibili_script)
```

### 脚本注入到 BrowserEngine

```python
from danmaku_listener.engines.browser_engine import BrowserEngine

engine = BrowserEngine(headless=False)

# 启动后注入脚本
await adapter.inject_to_engine(engine, "room_123", "bilibili")

# 暴露 onDanmaku 回调
await adapter.expose_callback_to_engine(engine, "room_123")
```

---

## 错误处理与重连

### 配置重连策略

```python
from danmaku_listener.managers.reconnect_manager import ReconnectManager

# 自定义重连参数
reconnect_mgr = ReconnectManager(
    max_retries=5,      # 最大重试 5 次
    base_delay=2.0,     # 基础延迟 2 秒
)
# 指数退避序列：2s, 4s, 8s, 16s, 32s

# 设置到引擎
engine.set_reconnect_manager(reconnect_mgr)
```

### 监听重连事件

```python
listener = DanmakuListener()

@listener.on_reconnect
async def on_reconnect(room_id: str):
    print(f"Room {room_id} reconnected!")
```

---

## 心跳监控

### 自定义心跳检查

BrowserEngine 默认使用 `page.evaluate('1')` 作为健康检查。可以自定义：

```python
from danmaku_listener.managers.heartbeat_monitor import HeartbeatMonitor

async def custom_health_check():
    """检查页面中是否存在弹幕容器"""
    try:
        result = await page.evaluate("document.querySelector('.danmu-list') !== null")
        return result
    except:
        return False

async def custom_recovery():
    """自定义恢复逻辑"""
    await page.reload()
    await adapter.inject_to_engine(engine, room_id, "bilibili")

monitor = HeartbeatMonitor(
    room_id="room_123",
    health_check=custom_health_check,
    recovery=custom_recovery,
    interval=15,  # 每 15 秒检查一次
)

await monitor.start()
```

---

## Cookie 管理

### Cookie 持久化

BrowserEngine 自动管理 Cookie：
- 启动时从 `./cookie/{room_id}.json` 加载
- 停止时保存到同一路径

```python
# 自定义 Cookie 目录
engine = BrowserEngine(
    headless=True,
    cookie_dir="./my_cookies",
)
```

### 手动管理 Cookie

```python
from danmaku_listener.managers.cookie_manager import CookieManager

mgr = CookieManager(cookie_dir="./cookie")

# 保存 Cookie
storage_state = await context.storage_state()
mgr.save_cookies("room_123", storage_state)

# 加载 Cookie
cookies = mgr.load_cookies("room_123")
```

---

## 性能指标

### 收集运行时指标

```python
from danmaku_listener.core import MetricsCollector

metrics = MetricsCollector()

# 记录指标
metrics.record_message_received("room_123")
metrics.record_message_published()
metrics.record_message_filtered()

# 获取指标快照
snapshot = metrics.get_metrics()
print(f"Messages: {snapshot['messages_received']}")
print(f"Throughput: {snapshot['messages_per_second']:.1f} msg/s")
print(f"Memory: {snapshot['memory_mb']:.1f} MB")
print(f"Uptime: {snapshot['uptime_seconds']:.0f}s")
```

---

## 结构化日志

### 配置结构化日志输出

```python
from danmaku_listener.utils.logger import setup_structured_logger

# JSON 格式日志 + 文件轮转
setup_structured_logger(
    level="INFO",
    log_file="./logs/danmaku.json",
)
```

### 敏感信息遮蔽

```python
from danmaku_listener.utils.logger import mask_sensitive

data = {
    "cookie": "session=abc123",
    "token": "Bearer xyz789",
    "platform": "douyin",
}

masked = mask_sensitive(data)
# {"cookie": "***MASKED***", "token": "***MASKED***", "platform": "douyin"}
```

遮蔽的敏感字段：`cookie`, `cookies`, `token`, `access_token`, `refresh_token`, `password`, `secret`, `authorization`, `api_key`, `private_key`

---

## 配置

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `PROXY_PORT` | `8827` | 代理服务器端口 |
| `LISTEN_ANY` | `false` | 监听所有网络接口 |
| `MAX_ROOMS` | `10` | 最大房间数 |
| `BROWSER_HEADLESS` | `true` | 浏览器无头模式 |
| `COOKIE_DIR` | `./cookie` | Cookie 存储目录 |
| `RECONNECT_MAX_RETRIES` | `3` | 重连最大重试次数 |
| `RECONNECT_BASE_DELAY` | `1.0` | 重连基础延迟（秒） |
| `HEARTBEAT_INTERVAL` | `30` | 心跳检测间隔（秒） |
| `DEDUP_WINDOW_SIZE` | `300` | 去重窗口大小 |

---

## 架构概览

```
┌─────────────────────────────────────────────┐
│              DanmakuListener                 │
│  (统一 API，上下文管理器)                      │
├──────────────────┬──────────────────────────┤
│   ProxyEngine    │     BrowserEngine        │
│   (mitmproxy)    │     (Playwright)         │
├──────────────────┼──────────────────────────┤
│  DouyinAdapter   │  DouyuAdapter           │
│                  │  BilibiliAdapter         │
│                  │  GenericAdapter         │
├──────────────────┴──────────────────────────┤
│              EventBus (async)               │
│         DedupFilter (滑动窗口)               │
├─────────────────────────────────────────────┤
│  ReconnectManager  │  HeartbeatMonitor      │
│  CookieManager     │  CertificateManager    │
├─────────────────────────────────────────────┤
│           MetricsCollector                  │
│           StructuredLogger                  │
└─────────────────────────────────────────────┘
```

## 登录事件需要人在场（attended 部署声明，2026-10-06 平台登录计划）

taobao / pdd / 1688 / jd / xiaohongshu / douyu / huya / wechat_channels 的登录窗口
（扫码/账号登录）需要**有人在部署机前操作**。无人值守场景（远程服务器/无头机房）：

- 引擎自动降级为游客模式继续监听（受控页面平台）；预算耗尽后每会话提示一次
  `ENGINE_STATUS login.timeout_budget_exhausted`，不会反复弹窗。
- 快手/拼多多/1688/淘宝等强制或强依赖登录的平台，无人值守 = 消息受限或缺失。
- 部署建议：首次部署在有屏幕的环境完成各平台登录（persistent profile /
  cookie 文件随项目目录持久化），之后迁移到无人值守机器可复用登录态。

斗鱼/虎牙登录态的特殊说明：协议直连（TCP），登录 cookie 无注入路径——
登录闭环按 2026-10-06 用户裁定实现（检测+弹窗+存档），消息流不受登录影响；
登录态存档供未来协议支持时使用。
