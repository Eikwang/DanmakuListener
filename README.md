# DanmakuListener

高性能跨平台弹幕监听解决方案，支持代理模式和浏览器模式的混合架构。

## 特性

- **混合架构**：主流平台（抖音）使用高性能代理模式，其他平台使用 Playwright 浏览器模式兜底
- **多平台支持**：内置抖音、斗鱼、B站适配器，支持自定义扩展
- **内存稳定**：从根本上解决 Chromium 注入脚本导致的内存泄漏问题
- **统一格式**：所有平台弹幕转换为标准格式输出
- **异步非阻塞**：基于 asyncio 的事件驱动架构，支持高并发
- **断线重连**：智能指数退避重连机制，保障稳定运行
- **心跳保活**：定期检测页面/连接健康状态，异常时自动恢复
- **Cookie 持久化**：自动保存和恢复登录状态
- **性能监控**：内置指标收集器，实时监控消息吞吐量、内存占用等
- **结构化日志**：支持 JSON 格式输出和敏感信息自动遮蔽

## 支持的平台

| 平台 | 弹幕 | 进场 | 点赞 | 关注 | 礼物 | 房间信息 |
|------|:----:|:----:|:----:|:----:|:----:|:--------:|
| B站 | ✅ | ✅ | ✅ | ✅（含分享归一） | ✅ | ✅ 在线 |
| 斗鱼 | ✅ | ✅ | 协议边界 | 协议边界 | ✅ | ✅ 在线 |
| 快手 | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| 抖音 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 在线+累计 |
| 淘宝 | ✅ | ✅ | — | — | — | ✅ 观看数 |
| 1688 | ✅ | ✅ | — | — | ✅ | ✅ |
| 美团 | ✅ | — | — | — | — | ✅ |
| 小红书 | ✅ | ✅ | ✅ 昵称反查 | ✅ | ✅ | — |
| 拼多多 | ✅ | ✅ | ✅ | ✅ | — | ✅ |
| 京东 | ✅ | ✅ | ⚠️ 聚合帧 | — | — | — |
| 虎牙 | ✅ | ✅ | — | — | ✅ | — |
| 视频号 | ✅ | ✅ | ✅ 严格帧驱动 | ✅ | ✅ | ✅ 在线+点赞 |

（"—" = 平台无对应功能或协议未开放；"协议边界" = 采样实证平台不推送，详见 `docs/testing/full_platform_test_plan.md`）

## 快速开始

### 安装（独立分发）

```bash
# 核心安装（B站/斗鱼/虎牙/快手/视频号引擎 + Web 控制台）
pip install .

# 可选平台依赖
pip install ".[douyin]"    # 抖音（已原生 Web WS 直连，此 extras 现为空——保留兼容）
pip install ".[wechat]"    # 视频号受控后台（playwright）
pip install ".[all]"       # 全部
```

### 一键启动（Web 测试控制台 / 独立系统主界面）

```bash
danmaku-serve --web
# 浏览器打开 http://localhost:8080 —— 添加房间（如 bilibili:23058）即可看到契约 v1 弹幕流
# 端口可经 config.local.toml 覆盖（[ws] port / [web] port；默认 8765 / 8080——文档以默认值为准）
```

### 库用法（AUTOlive 集成）

```python
import asyncio
from danmaku_listener import DanmakuListener, DanmakuMessage

async def main():
    async with DanmakuListener() as listener:
        await listener.start(["douyin:123456"])
        @listener.on_danmaku
        async def handle(msg: DanmakuMessage):
            print(f"[{msg.platform}] {msg.user_name}: {msg.content}")
        await asyncio.Future()

asyncio.run(main())
```

### 基本用法

```python
import asyncio
from danmaku_listener import DanmakuListener, DanmakuMessage

async def main():
    # 使用上下文管理器
    async with DanmakuListener() as listener:
        # 启动监听（格式：platform:room_id）
        await listener.start(["douyin:123456"])

        # 注册弹幕事件回调
        @listener.on_danmaku
        async def handle_danmaku(message: DanmakuMessage):
            print(f"[{message.platform}] {message.user_name}: {message.content}")

        # 注册错误回调
        @listener.on_error
        async def handle_error(error: Exception):
            print(f"Error: {error}")

        # 保持运行
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
```

### 多平台混合监听

```python
async with DanmakuListener() as listener:
    # 同时监听多个平台
    await listener.start([
        "douyin:123456",   # 原生 Web WS 直连
        "bilibili:789012", # 协议直连
        "douyu:345678",    # TCP 明文 STT 直连
    ])
```

### 显式控制模式

```python
listener = DanmakuListener()
await listener.start(["douyin:123456", "bilibili:789012"])

# ... 运行中

await listener.stop()
```

## 配置

复制 `.env.example` 为 `.env.local` 并修改配置：

```bash
cp .env.example .env.local
```

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `LOG_LEVEL` | `INFO` | 日志级别 (DEBUG/INFO/WARNING/ERROR) |
| `PROXY_PORT` | `8827` | 代理服务器端口 |
| `MAX_ROOMS` | `10` | 同时监听的最大房间数 |
| `BROWSER_HEADLESS` | `true` | 浏览器是否使用无头模式 |
| `COOKIE_DIR` | `./cookie` | Cookie 存储目录 |
| `RECONNECT_MAX_RETRIES` | `3` | 重连最大重试次数 |
| `RECONNECT_BASE_DELAY` | `1.0` | 重连基础延迟（秒） |
| `HEARTBEAT_INTERVAL` | `30` | 心跳检测间隔（秒） |
| `DEDUP_WINDOW_SIZE` | `300` | 去重窗口大小（条消息） |

## 项目结构

```
danmaku_listener/
├── __init__.py          # 包入口
├── listener.py          # DanmakuListener 主类
├── core.py              # 性能指标收集器
├── engines/             # 监听引擎层
|   ├── base.py          # BaseEngine 抽象基类
|   ├── registry.py      # 引擎注册表（十二平台路由）
|   └── protocol/        # 十二平台协议直连引擎
├── adapters/            # 平台适配器层
|   ├── base.py          # BaseAdapter 抽象基类
|   ├── douyin.py        # 抖音适配器
|   ├── douyu.py         # 斗鱼适配器
|   ├── bilibili.py      # B站适配器
|   ├── generic.py       # 通用适配器
|   └── protocols/       # 协议定义
|       └── message_types.py
├── bus/                 # 消息总线层
|   ├── event_bus.py     # 事件分发中心
|   ├── message.py       # 数据模型
|   └── dedup_filter.py  # 去重过滤器
├── managers/            # 资源管理器
|   ├── certificate_manager.py
|   ├── cookie_manager.py
|   ├── reconnect_manager.py
|   └── heartbeat_monitor.py
├── config/              # 配置管理
|   ├── settings.py      # Pydantic Settings
|   └── defaults.py      # 默认配置值
└── utils/               # 工具函数
    ├── platform_parser.py
    └── logger.py
```

## 文档

- [API 文档](docs/api.md) — 详细的 API 参考文档
- [高级用法指南](docs/advanced.md) — 自定义适配器、脚本扩展、错误处理等

## 开发

### 环境要求

- Python >= 3.10
- Poetry >= 1.7

### 安装依赖

```bash
poetry install
```

### 运行测试

```bash
pytest tests/
```

### 代码检查

```bash
ruff check danmaku_listener/
mypy danmaku_listener/
black --check danmaku_listener/
```

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！
