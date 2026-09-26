# DanmakuListener → AUTOlive 整合就绪文档

> 由 /learn 导出（2026-09-27）。本文件是 AUTOlive 侧接入弹幕监听组件的**唯一入口参考**：
> 连接方式、消息处理要点、平台就绪矩阵、部署步骤与已知边界。
> 配套文档：[autolive.md](autolive.md)（接入指南）、[../contract/schema.json](../contract/schema.json)（机读 Schema）。

## 1. 组件定位与边界

- DanmakuListener **只做监听**：六平台弹幕采集 → 标准化 → 推送；无 UI、无持久化、不发送
- AUTOlive 是唯一前端：消费统一消息流驱动数字人互动
- 部署形态：同机 Python 组件（`pip install -e` 或直接 `python -m danmaku_listener`）

## 2. 连接与鉴权（AUTOlive 侧代码要点）

```python
import asyncio, json, websockets

async def consume():
    async with websockets.connect(
        "ws://127.0.0.1:8765/ws",
        additional_headers={"Authorization": "Bearer <token>"},
    ) as ws:
        async for raw in ws:
            msg = json.loads(raw)
            if msg["category"] == "business":
                ...   # 数字人互动：msg["type"] ∈ DANMU/GIFT/SUPER_CHAT/...
            else:
                ...   # 系统状态：见 §4 处理矩阵
```

- 服务端默认绑定 127.0.0.1（`ws_bind` 配置）；token 经 `DANMAKU_TOKEN` 环境变量
  或受限权限文件注入，`Authorization: Bearer` 头携带
- 未配置 token 时仅依赖 loopback 边界（serve 启动横幅会明示）

## 3. 消息处理契约（九类 = 8 业务 + SYSTEM_STATUS）

| AUTOlive 必须处理 | 语义 | 处理要点 |
|---|---|---|
| category=business | 互动消息（DANMU/GIFT/SUPER_CHAT/ENTER_ROOM/LIKE/ROOM_STATS/SOCIAL/LIVE_STATUS_CHANGE） | 按 payload 字段驱动；忽略未知 type 并计数（additive-only 契约） |
| system/HEARTBEAT (10s) | 引擎存活 | 3 周期未收到 → 判定失联并告警 |
| system/GAP | 消息缺口（必达） | reason: network/protocol/risk_control/backpressure/crash_recovery；approx=true 表示边界为近似 |
| system/NEEDS_LOGIN | 登录态过期 | 携带 interactive_login（QR base64/URL）→ 界面呈现扫码 → 引擎自动恢复 |
| system/ENGINE_STATUS | 活跃引擎标识 | 界面展示当前引擎（protocol:x / proxy:x / fallback:x） |
| system/ROUTE_FAILED | 路线失效 | reason_code/fix_hint/docs_anchor 三段式，直接可用于 UI 呈现 |
| system/BACKPRESSURE | 背压丢弃计数 | 窗口级；同窗口会有伴随 GAP |

- **去重**：按 `envelope.msg_id`（平台原生 ID）；AUTOlive 重启后去重窗口冷启动
- **顺序**：同房间 `seq` 单调；跳跃时等待 GAP 确认
- **背压**：慢消费时服务端分级丢弃（先丢 LIKE/ENTER_ROOM/DANMU，保 GIFT/SUPER_CHAT）

## 4. 平台就绪矩阵（六平台）

| 平台 | 引擎 | 状态 | AUTOlive 侧注意 |
|---|---|---|---|
| B站 | protocol:bilibili | codec 完整，需实测 token 获取 | 游客可听，无登录负担 |
| 斗鱼 | protocol:douyu | codec 完整，需实测 | 同上 |
| 虎牙 | protocol:huya | **draft**（huya-0-draft，parse_hook 待抓包校准） | 暂不承诺 |
| 快手 | protocol:kuaishou | codec 完整（本地 ks_pb2） | **游客 token 签名 = 重点验证项** |
| 抖音 | proxy:douyin | 桥接完成（ProxyEngine 独立进程，ADR-001） | 需证书/伴侣版本确认（preflight） |
| 视频号 | controlled:wechat_channels | 引擎完整，后台接口结构待实测校准 | NEEDS_LOGIN 扫码是**常规路径**，UI 需常驻入口 |

## 5. 部署与验证命令

```bash
pip install -e .                                          # 获得 danmaku-listen/serve 命令
python scripts/preflight.py --platforms <平台列表>         # 部署前置检测（网络/端口/凭据/人工项）
python -m danmaku_listener listen --replay docs/contract/examples/demo.jsonl   # 离线冒烟（TTHW 实测 3-7ms）
python -m danmaku_listener serve                          # 启动推送通道（AUTOlive 对接）
python scripts/export_contract.py --check                 # 契约漂移检查（CI 可用）
python -m pytest tests/unit/ -q                           # 609 单测
```

## 6. 治理与合规（商业交付前置）

- 合规清单：`docs/ops/compliance-review.md`——ToS 评估、客户书面知情同意、
  **专用监听账号（严禁客户主账号）**、根 CA 与 hook 单独知情确认
- 许可证审计：`docs/ops/license-audit.md`——参考项目全部 MIT/Apache-2.0
- 预算基线：`docs/ops/budget-baseline.md`——空骨架 RSS 54.1MB（系统级 ≤1.2GB 校准）
- 运维 SLA：失效容忍预算（单平台月维护工时上限，超限降级兜底）

## 7. 遗留实测项（非代码缺口）

1. 虎牙 payload 解析（parse_hook 注入点已留）
2. 快手游客 token 签名接口
3. 视频号后台接口结构（变更点集中在引擎头部常量）
4. B站/斗鱼/抖音真实连接长时间稳定曲线（24h 漂移门禁）
5. 契约 + 平台优先级经真实电商客户校验（阶段 0 出口条件，线下）

## Project Learnings（本任务沉淀）

### Architecture
- **contract-v1-single-source**: pydantic 单源 → Schema 导出 + CI 漂移检查（confidence: 9/10）
- **engine-topology-adr001**: 协议单进程 / 抖音独立 IPC / 视频号浏览器树 / 兜底有界会话（confidence: 9/10）

### Patterns
- **system-status-three-part**: 失败消息三段式 reason_code+fix_hint+docs_anchor 强制非空（confidence: 9/10）
- **gap-semantics-family**: GAP 窗口语义族（下播裁剪 + approx 降级 + 背压触发）（confidence: 9/10）

### Operational
- **autolive-integration-interface**: WS+token+category 分流+msg_id 去重+seq 顺序（confidence: 9/10）
- **platform-readiness-matrix**: 六平台就绪差异与 AUTOlive 侧注意点（confidence: 8/10）

### Pitfalls
- **eager-import-heavy-deps**: 主包勿顶层 import 重依赖（PEP 562 惰性模式）（confidence: 9/10）
- **protobuf-gencode-mismatch**: pb2 gencode 与 runtime 版本必须对齐；UTF-8 requirements 需 PYTHONUTF8=1（confidence: 8/10）
