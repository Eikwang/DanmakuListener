# DanmakuListener API 文档

## 核心 API

### DanmakuListener

弹幕监听器主类，提供统一的 API 接口。

```python
from danmaku_listener import DanmakuListener
```

#### 构造函数

```python
DanmakuListener(config: Optional[dict] = None)
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `config` | `dict \| None` | `None` | 可选的配置字典（覆盖默认配置） |

#### 方法

##### `start(rooms: List[str]) -> None`

启动对多个房间的监听。

| 参数 | 类型 | 说明 |
|------|------|------|
| `rooms` | `List[str]` | 房间规格列表，格式为 `["platform:room_id", ...]` |

**异常：**
- `ValueError` — 房间规格格式不正确或超过最大数量（默认 10）

**示例：**
```python
await listener.start(["douyin:123456", "bilibili:789012"])
```

##### `stop() -> None`

停止所有监听。

##### `on_danmaku(callback: DanmakuCallback) -> None`

注册弹幕事件回调。

| 参数 | 类型 | 说明 |
|------|------|------|
| `callback` | `Callable[[DanmakuMessage], Coroutine]` | 异步回调函数 |

##### `on_error(callback: ErrorCallback) -> None`

注册错误事件回调。

| 参数 | 类型 | 说明 |
|------|------|------|
| `callback` | `Callable[[Exception], Coroutine]` | 异步回调函数 |

##### `on_reconnect(callback: ReconnectCallback) -> None`

注册重连事件回调。

| 参数 | 类型 | 说明 |
|------|------|------|
| `callback` | `Callable[[str], Coroutine]` | 异步回调函数，接收 room_id |

##### `on_status_change(callback: StatusCallback) -> None`

注册状态变化事件回调。

| 参数 | 类型 | 说明 |
|------|------|------|
| `callback` | `Callable[[str, str], Coroutine]` | 异步回调函数，接收 (room_id, status) |

#### 上下文管理器

支持 `async with` 语法，退出时自动调用 `stop()`。

```python
async with DanmakuListener() as listener:
    await listener.start(["douyin:123456"])
    # ...
```

---

### DanmakuMessage

标准化的弹幕消息格式。

```python
from danmaku_listener import DanmakuMessage
```

#### 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `platform` | `str` | 平台标识 (douyin, douyu, bilibili, etc.) |
| `room_id` | `str` | 直播间 ID |
| `user_name` | `str` | 发送者昵称 |
| `content` | `str` | 弹幕文本内容 |
| `timestamp` | `int` | 时间戳（秒级） |
| `message_type` | `Literal["normal", "gift", "system"]` | 消息类型 |
| `gift_info` | `GiftInfo \| None` | 礼物信息（仅当 message_type=gift） |

#### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `is_gift` | `bool` | 是否为礼物消息 |
| `formatted_time` | `str` | 格式化的时间字符串 |

#### 方法

##### `to_dict() -> dict`

转换为字典格式。

---

### GiftInfo

礼物信息模型。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `user_name` | `str` | — | 送礼者昵称 |
| `gift_name` | `str` | — | 礼物名称 |
| `gift_count` | `int` | `1` | 礼物数量 |
| `gift_value` | `int \| None` | `None` | 礼物价值 |

---

## 支持的平台

| 平台 | 标识 | 引擎模式 | 适配器 |
|------|------|----------|--------|
| 抖音 | `douyin` | 代理模式 | `DouyinAdapter` |
| 斗鱼 | `douyu` | 浏览器模式 | `DouyuAdapter` |
| B站 | `bilibili` | 浏览器模式 | `BilibiliAdapter` |
| 其他 | — | 浏览器模式 | `GenericAdapter` |

---

## 引擎 API

### BaseEngine（抽象基类）

所有监听引擎的基类。

#### 抽象方法

| 方法 | 说明 |
|------|------|
| `start(room_id: str) -> None` | 启动监听 |
| `stop(room_id: str) -> None` | 停止监听 |
| `restart(room_id: str) -> None` | 重启监听 |

#### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `platform` | `str` | 平台标识 |
| `status` | `EngineStatus` | 引擎状态 |

#### 方法

| 方法 | 说明 |
|------|------|
| `on_message(callback)` | 注册消息回调 |
| `on_error(callback)` | 注册错误回调 |
| `set_reconnect_manager(manager)` | 设置重连管理器 |

### ProxyEngine

代理模式引擎，用于抖音平台。

### BrowserEngine

浏览器模式引擎，基于 Playwright。

| 方法 | 说明 |
|------|------|
| `stop_all() -> None` | 停止所有监听 |
| `get_page(room_id) -> Page \| None` | 获取指定房间的 Page |

---

## 适配器 API

### BaseAdapter（抽象基类）

所有平台适配器的基类。

| 方法 | 说明 |
|------|------|
| `can_parse(data) -> bool` | 判断是否能处理该数据 |
| `parse(raw_data, context) -> DanmakuMessage \| None` | 解析原始数据 |

### GenericAdapter

通用适配器，支持自定义脚本和解析器。

| 方法 | 说明 |
|------|------|
| `get_script(platform) -> str` | 获取监听脚本 |
| `register_script(platform, script)` | 注册自定义脚本 |
| `register_parser(type, parser)` | 注册自定义解析器 |
| `inject_to_engine(engine, room_id, platform)` | 注入脚本到引擎 |
| `expose_callback_to_engine(engine, room_id)` | 暴露回调到引擎 |

---

## 管理器 API

### ReconnectManager

断线重连管理器，指数退避策略。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_retries` | 3 | 最大重试次数 |
| `base_delay` | 1.0 | 基础延迟（秒） |

### HeartbeatMonitor

心跳保活监控器。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `room_id` | — | 房间 ID |
| `health_check` | — | 健康检查回调 |
| `recovery` | — | 恢复回调 |
| `interval` | 30 | 检查间隔（秒） |

---

## 性能指标 API

### MetricsCollector

运行时性能指标收集器。

| 方法 | 说明 |
|------|------|
| `record_message_received(room_id)` | 记录接收消息 |
| `record_message_published()` | 记录发布消息 |
| `record_message_filtered()` | 记录过滤消息 |
| `record_reconnect(room_id)` | 记录重连 |
| `record_error()` | 记录错误 |
| `set_active_rooms(count)` | 设置活跃房间数 |
| `get_metrics() -> dict` | 获取所有指标 |
| `reset()` | 重置所有指标 |

**指标字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `messages_received` | `int` | 接收消息总数 |
| `messages_published` | `int` | 发布消息总数 |
| `messages_filtered` | `int` | 过滤消息总数 |
| `reconnect_count` | `int` | 重连次数 |
| `errors_count` | `int` | 错误次数 |
| `active_rooms` | `int` | 活跃房间数 |
| `uptime_seconds` | `float` | 运行时间（秒） |
| `memory_mb` | `float` | 内存占用（MB） |
| `messages_per_second` | `float` | 消息吞吐量 |
| `per_room` | `dict` | 按房间统计 |
