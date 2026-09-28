<!-- /autoplan restore point: "C:\\Users\\admin\\.gstack\\projects\\Eikwang-AUTOlive\\main-autoplan-restore-20260927-050947.md" -->
## Implementation plan
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
                ...   # 系统状态：见 §3 处理矩阵
```

> 示例为骨架写法，仅示意 category 分流。生产消费者的完整契约（重连退避、401 中止、
> envelope 校验、未知 type 计数）以 Review record 义务块为准。

- 服务端默认绑定 127.0.0.1（`ws_bind` 配置）；token 经 `DANMAKU_TOKEN` 环境变量
  或受限权限文件注入，`Authorization: Bearer` 头携带
- 未配置 token 时仅依赖 loopback 边界（serve 启动横幅会明示）

## 3. 消息处理契约（十六类 = 8 业务 + 8 系统）

| AUTOlive 必须处理 | 语义 | 处理要点 |
|---|---|---|
| category=business | 互动消息（DANMU/GIFT/SUPER_CHAT/ENTER_ROOM/LIKE/ROOM_STATS/SOCIAL/LIVE_STATUS_CHANGE） | 按 payload 字段驱动；忽略未知 type 并计数（additive-only 契约） |
| system/HEARTBEAT (10s) | 引擎存活 | 3 周期未收到 → 判定失联并告警 |
| system/GAP | 消息缺口（必达） | reason: network/protocol/risk_control/backpressure/crash_recovery；approx=true 表示边界为近似 |
| system/NEEDS_LOGIN | 登录态过期 | 携带 interactive_login（QR base64/URL）→ 界面呈现扫码 → 引擎自动恢复 |
| system/ENGINE_STATUS | 活跃引擎标识 | 界面展示当前引擎（protocol:x / proxy:x / fallback:x） |
| system/ROUTE_FAILED | 路线失效 | reason_code/fix_hint/docs_anchor 三段式，直接可用于 UI 呈现 |
| system/BACKPRESSURE | 背压丢弃计数 | 窗口级；同窗口会有伴随 GAP |
| system/RECOVERED | 慢速重试后恢复 | 呈现恢复时长（after_seconds），闭合失联告警 |
| system/ROOM_STATUS | 房间在线状态 | 配合 GAP 裁剪：下播期间缺失不计 GAP |

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

> **部署形态（G8 裁决前）**：当前按复制唯一副本范式执行，`pip install -e` 在 G8 裁决前不受支持；AUTOlive 托管层统一以 `python -m danmaku_listener` 形态调用（不依赖 console script）。待裁决项汇总见 Review record 的 Decision Audit Trail。以下为组件侧开发/验证命令。

```bash
pip install -e .                                          # 获得 danmaku-listen/serve 命令（上游双入口并存；托管层用 python -m 形态）
python scripts/preflight.py --platforms bilibili,douyu    # 部署前置检测（合法平台标识：bilibili/douyu/huya/kuaishou/douyin/wechat_channels）
python -m danmaku_listener listen --replay docs/contract/examples/demo.jsonl   # 离线冒烟（单消息回放延迟实测 3-7ms；端到端 TTHW 以冒烟脚本计时为准）
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
6. B站/斗鱼 token 获取实测（§4 状态"需实测"对应的遗留项）

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



<!-- autoplan-accepted:ceo -->
- 整合形态：DanmakuListener 以同机独立进程（serve）部署，AUTOlive 托管其生命周期（复用 EDTalk/音频整合的子进程编排范式：拉起/端口探活/崩溃自动重拉带失控防护——"连续 3 次拉起失败"或"拉起后 5 分钟内再次僵死"均计入防护计数，达 3 次停止重拉、音频整合交付的服务状态条胶囊组件置红）；正常关停——AUTOlive 退出或停止托管时终止 serve 子进程（terminate→超时 kill），确认端口释放；AUTOlive 侧新建 WS 消费者模块连接 `ws://127.0.0.1:<port>/ws`（默认 8765，端口可配），`Authorization: Bearer <token>` 鉴权；WS 连接连续 3 次失败移交托管层（与失控防护计数对齐），移交期间消费者保持退避重连，serve 拉起后端口探活通过即自然恢复。代码归属（G8）待 Phase 4 终门裁决：当前按复制唯一副本范式起草，pip install -e 为备选；复制落点为 AUTOlive 仓库 `danmaku_listener/`（类比 `edtalk/` 先例），复制工具复用 `Scripts/` 既有复制脚本模式。
- 鉴权与 token：AUTOlive 托管层生成随机 token 经环境变量 `DANMAKU_TOKEN` 注入子进程（备选：受限权限文件注入）；强制注入开关 `danmaku_listener.require_token`（默认 true，关闭时仅依赖 loopback 边界，限开发态）。
- 消息契约：按契约 v1（docs/contract/schema.json，16 类 = 8 业务 + 8 系统）消费；按 category 分流（business→互动处理，system→状态处理）；未知 type 忽略并计数（additive-only 契约）；按 envelope.msg_id 去重，去重存储复用 my_handle 既有去重机制与窗口参数（内存态，重启后冷启动）；同房间 seq 单调，跳跃时等待 GAP 确认——等待期内后续消息缓冲（上限 1000 条/房间，超限按背压同序丢弃低优先级），GAP 到达或超时 10s（1 个心跳周期）后按 approx 降级放行并告警。
- business 消息逐类映射：DANMU/GIFT/SUPER_CHAT→对话链触发（复用现有弹幕→LLM→TTS 链）；ENTER_ROOM/LIKE→计数与既有播报路径；ROOM_STATS→计数存储与 UI 展示；SOCIAL→计数/播报；LIVE_STATUS_CHANGE→开播/下播状态机（联动下播裁剪）；下播窗口内新到 business 消息仍记录（danmu 表/弹幕文件）但不触发对话链互动，开播（live=true）复位状态机并恢复互动；全部映射进现有 my_handle.py 交互链，不重建处理逻辑。
- system 消息矩阵：HEARTBEAT（10s，3 周期未收→失联告警——告警形态为服务状态条胶囊+日志，无独立通知渠道；失联持续 60s→托管层判进程僵死并重拉；失联判定基于组件级 WS 通道心跳，不随单平台引擎 failover 切换误触发，平台级引擎状态经 ENGINE_STATUS 呈现）；托管层重拉成功后由托管层以首个 HEARTBEAT 到达闭合失联告警并自行计算呈现恢复时长（RECOVERED 仅覆盖进程内慢速恢复时长呈现；进程内恢复场景由恢复后首个 HEARTBEAT 到达闭合失联告警）；GAP（窗口+reason+approx 呈现）；下播裁剪——收到 LIVE_STATUS_CHANGE(live=false) 后的 GAP 窗口不再做历史缺漏告警，并清空互动队列中低优先级待处理消息（DANMU/ENTER_ROOM/LIKE），保留 GIFT/SUPER_CHAT；NEEDS_LOGIN（interactive_login QR/URL 在 AUTOlive UI 呈现，视频号扫码为常规路径需常驻入口，操作后引擎自动恢复；多平台并发登录请求逐个队列呈现）；ENGINE_STATUS（当前引擎标识展示 protocol:x/proxy:x/fallback:x）；ROUTE_FAILED（reason_code/fix_hint/docs_anchor 三段式直接呈现）；BACKPRESSURE（窗口丢弃计数呈现）；RECOVERED（恢复时长告知）；ROOM_STATUS（在线状态展示）。
- 配置数据节（G6）：config.json 新增 `danmaku_listener` 节——WS 端口、`require_token`（默认 true）、token 注入方式（env/file）、平台启用开关（按就绪梯度默认 B站/斗鱼/抖音，逐平台独立）、NEEDS_LOGIN 常驻入口开关、旧适配器退役开关位（G7 预留，Phase 4 裁决通过才生效）；运行时阈值（心跳 10s/3 周期/60s、seq 超时 10s、退避 1s/30s、防护 3 次）首版为消费端命名常量不进配置；托管层将配置映射为 serve 启动参数（端口/平台列表经 CLI 参数、token 经环境变量，组件 CLI 参数形态实施时对齐）。
- 平台上线梯度：首发就绪平台（B站/斗鱼/抖音），preflight 通过即可启用；B站/斗鱼 token 实测失败时首发收缩为实测可用平台（启用开关逐平台独立，不互相阻塞）；24h 真实连接漂移门禁为商用交付前置（个人使用阶段不阻塞）；虎牙 draft、快手游客 token、视频号结构校准为上游遗留实测项——AUTOlive 侧以就绪状态在 UI 明示，不承诺未验证平台。
- 复用前提（P1 首任务逐项核验存在性与接口签名，不符即回报修订）：my_handle 既有去重机制与窗口参数（utils/my_handle.py 直播消息存储去重区域）、服务状态条胶囊组件及其置红调用（frontend/ui/ 服务状态条，音频整合交付）、既有播报路径入口（my_handle 播报函数）、websockets≥13 与 AUTOlive 既有依赖树无版本冲突（uv/pip-compile 统一依赖解析检查一次）。部署硬约束：serve 运行期间 AUTOlive 控制台（WebUI）不得公网暴露（WS 无 TLS、Bearer 明文）；token 随托管层每次重拉轮换。
- 测试基线：消费者模块单测（鉴权头注入/重连——指数退避 1s 起上限 30s、连续 3 次连接失败移交托管重拉、重连后去重与 seq 状态延续/category 分流/msg_id 去重/seq 跳跃与 10s 超时降级与等待期缓冲上限/未知 type 计数/16 消息类型路由）+ 离线冒烟（listen --replay demo.jsonl 链路）+ serve 连通冒烟；websockets 客户端依赖 ≥13（additional_headers 参数名）在 AUTOlive 侧 requirements 明确。
- 合规边界：专用监听账号（严禁客户主账号）；抖音 proxy 引擎启用前完成根 CA 与 hook 单独知情确认项。合规是商业模式可行性问题而非交付清单：商业签约/定价前取得专业法律意见或以最小规模实测风险边界，并设计商业退路（仅支持官方开放 API 的平台 / 自托管工具+客户自担账号责任模式）写入组件侧 docs/ops/compliance-review.md 风险章节；个人使用阶段不受阻。
- 消费者并发与队列：WS 消费者为独立 asyncio 任务 + 自身有界主队列（上限 500 条，溢出按背压同序丢弃低优先级并计数），经队列投递至主处理线程执行 my_handle 交互链，不阻塞 WS 读循环。
- 首版单房间：消费者首版绑定单房间（对齐现有单直播间架构），多房间为后续扩展。
- 鉴权失败处理：token 鉴权失败（401/403）立即告警置红、不自动重试（重试无意义），等待人工介入或配置修正。
- 信封校验：envelope 必填字段缺失的消息丢弃并计数 + 日志记录（契约反向防御）。
- 扫码 UI 安全与状态：interactive_login.qr_image_b64 渲染复用既有字幕页 XSS 转义模式（data:image 安全渲染）；QR 过期（expires_at）后呈现过期态，依赖引擎重发新 NEEDS_LOGIN 刷新，UI 展示最新一条。
- 总开关分离：config 新增 `danmaku_listener.enabled` 总开关（默认 false，false 时托管不拉起 serve、消费者不启动），与旧链路退役开关（G7 预留位）语义分离。
- 结构化日志：消费者关键事件（连接/断连/移交/重拉/消息分流/丢弃计数）结构化日志，携带 room_id/seq/msg_id 关键字段。
- 模块落点：组件副本落 `danmaku_listener/`（G8 裁决后生效），消费者接线模块落 `utils/danmaku_consumer.py`（WS 消费 + 队列桥 + 分发），托管接线复用 utils/service_orchestrator.py 的 ManagedProcess。
- 契约漂移防护：G8 裁决为复制时，`python scripts/export_contract.py --check` 纳入 AUTOlive 侧测试流程（复制后运行）。
- 既有风险观察：弹幕文本进 LLM 对话链的 prompt injection 面为既有风险（旧适配器同样暴露），多平台接入扩大暴露面——净化防护随既有 gpt 链路，不因本次整合新增防线，记录在案。
- 商用前置与客户校验（与 P1 并行，不阻塞编码）：用 `listen --replay demo.jsonl` 离线冒烟链路向目标客户演示验证；校验第一问"客户直播间在哪些平台"，答案作为平台优先级唯一输入重排就绪矩阵；北极星指标（互动响应延迟、GIFT/SUPER_CHAT 触发转化）随 P1 验收定义；为每平台估月维护工时基线写入 SLA 文档，退出阈值=连续 2 个月超限即从就绪矩阵降级，"兜底"定义为降级为人工监听或直接下线（随 SLA 文档定案）。
<!-- /autoplan-accepted:ceo -->

<!-- autoplan-accepted:dx -->
- 分阶段上手路径（DX）：AUTOlive 侧提供三阶段 Hello World——阶段 1 独立 serve + 任意 WS 客户端收 demo 流；阶段 2 单平台（B 站）跑通数字人对话链；阶段 3 全配置启用。每阶段一条可复制命令 + 预期现象，写入 §5 或模块 README；冒烟脚本输出各步耗时（端到端 TTHW 可见，目标 replay 冒烟 <2 分钟、全链路部署 ≤10 分钟）。
- 三段式全覆盖（DX）：reason_code+fix_hint+docs_anchor 为所有面向 UI 错误的最小契约——鉴权 401/403（cause=token 不匹配或轮换未同步，fix=核对 DANMAKU_TOKEN 注入，docs_anchor 指向部署文档）；托管重拉 3 次失败（fix_hint=端口占用检查命令 + serve 日志路径）；端口占用（EADDRINUSE）与"serve 未启动"在探活失败中区分呈现；NEEDS_LOGIN QR 过期且引擎未重发时 UI 提供手动重试出口；托管层调用组件 preflight 的失败输出按三段式转呈 UI。
- docs_anchor 解析约定（DX）：P1 首任务与组件侧确认 anchor 语法（形如 docs/platform/bilibili.md#token）与 URL 映射规则（映射为组件副本内文档相对路径），schema 侧约束格式；UI 呈现为可点击文档链接。
- 配置与参数面（DX）：G6 数据节补 G7 键名 `legacy_adapter_retired`（裁决通过才生效）；CLI 参数表（--port/--platforms 等）P1 首任务与组件侧实核后定死并写入配置注释，与配置键一一映射；去重窗口等继承参数在配置文档列出当前值与来源；调参逃生门小节说明各命名常量的落点文件与调整时机（首版不进配置的裁决不变）。
- 升级与版本（DX）：上游组件更新流程 = 重跑复制脚本（版本戳变化可见）→ `export_contract.py --check` → 冒烟脚本，三步写入模块 README；消费者启动时断言 envelope.contract_version 兼容（1.x 接受，2.x 拒绝并告警）。
- 文档单源澄清（DX）：实现区义务块为 /autoplan 评审导出形态，实施义务以 Review record 的 autoplan-accepted 块为权威源，两处内容由工具保持同步。
<!-- /autoplan-accepted:dx -->

<!-- autoplan-accepted:eng -->
- token 生命周期（修订 A-1）：消费者每次重连前从共享源读取当前 token（文件注入或 orchestrator 句柄），不缓存旧值；401/403 触发一次 token 刷新后重试一次，仍失败才告警置红；token 轮换兼作 serve 世代信号。
- 消费者双通道（修订 A-2/B-2）：system 消息（心跳计时/seq/GAP 判定/ENGINE_STATUS 等）在 WS 读循环协程内快路径直接处理，不进 500 主队列；仅 business 消息跨线程过队列。8 业务类统一优先级表（服务端丢弃序 = 消费端溢出序 = 队列路由分类）：DANMU/GIFT/SUPER_CHAT/SOCIAL 进队列（GIFT/SUPER_CHAT FIFO 保序），LIKE/ENTER_ROOM/ROOM_STATS 走计数快路径不进对话链队列；优先级表随契约导出防漂移。
- 对话链聚合限速（新增 B-1）：DANMU 进 LLM 链前做窗口聚合（N 条/时间窗合并为一条 prompt 或摘要播报）+ 消费端限速与丢弃预算；GIFT/SUPER_CHAT 保持 FIFO（SUPER_CHAT 可插队）。
- 重拉归口与世代（修订 A-3/A-4）：重拉裁决单一归口托管层（心跳超时或连接失败任一先到为准，计数器唯一，消费者只上报）；重拉即新世代——消费者以世代信号（token 轮换）为界重置 seq 期待与去重窗口。
- 进程树管理（修订 A-5）：Windows 下 terminate→kill 扩展为整棵进程树回收（taskkill /T /F 或 Job Object），抖音 ProxyEngine 子进程不残留；"端口释放确认"升级为"进程树回收确认"，Windows 实跑测试。
- 缓冲放行（修订 B-3）：seq 等待缓冲放行分批注入（不一次性打满主队列）；缓冲动作显式非阻塞（不阻塞 WS 读循环）；下播清队列与已进 LLM 链消息的行为固化为测试预期。
- 安全防线（修订 S-1/S-2/S-3/C-2）：DANMU 文本进 LLM 前长度钳制 + 控制字符/零宽字符剥离，URL 与社交字段不进 prompt（升级原"记录在案"）；UI 渲染 docs_anchor/fix_hint 做 scheme 白名单（仅 https 或组件内相对路径），QR 渲染钳制 MIME 与 base64 大小；token 生成用 secrets.token_urlsafe(≥32 字节)，require_token=false 时状态条胶囊持续示警；托管层子进程 env 契约显式列单（PYTHONUTF8=1、PYTHONPATH、DANMAKU_TOKEN）。
- 依赖钉版（修订 S-4）：websockets 在 AUTOlive 侧 requirements 钉死版本并显式 `from websockets.asyncio.client import connect`（additional_headers 属 asyncio.client 新实现，顶层 connect 13/14.x 为 legacy 参数名 extra_headers——requirements_common.txt:276 当前裸名，P1 依赖解析实核）。
- 执行模型（新增 C-1）：P1 首任务定 asyncio→线程队列桥执行模型（my_handle 链为同步阻塞 → 单 worker 线程 + 线程安全队列，asyncio.Queue 与线程安全队列语义区分），500 上限与溢出行为按此模型设计测试。
- 测试扩充（Eng）：在既定测试基线上补 10 项——token 轮换重连成功、僵死重拉全链（60s→重拉→3 次防护→置红→手动清零）、世代重置、进程树回收（Windows 实跑）、system 快路径延迟断言（队列满载心跳处理 < 阈值）、contract_version 2.x 拒绝、enabled/require_token 开关行为、下播开播状态机、非法 JSON 帧容错计数、优先级表双端一致性。
<!-- /autoplan-accepted:eng -->
## Review record

<!-- autoplan-baseline-edits:ceo {"sourceSha256":"352368e9367f7e814429caeb38fe9b0dae523bfc40e9a1093d53b9a185096de9","replacements":[]} -->
<!-- autoplan-baseline-edits:dx {"sourceSha256":"6cb11ad2c824e26c8e8f3f7b2ade1dbd22d54dbf9349e6807d9a4dd4f4650767","replacements":[]} -->
<!-- autoplan-baseline-edits:eng {"sourceSha256":"897caf6af273e583f1348c233552672e4c66bb848823273b59c12030055f7934","replacements":[]} -->

<!-- autoplan-accepted:ceo -->
- 整合形态：DanmakuListener 以同机独立进程（serve）部署，AUTOlive 托管其生命周期（复用 EDTalk/音频整合的子进程编排范式：拉起/端口探活/崩溃自动重拉带失控防护——"连续 3 次拉起失败"或"拉起后 5 分钟内再次僵死"均计入防护计数，达 3 次停止重拉、音频整合交付的服务状态条胶囊组件置红）；正常关停——AUTOlive 退出或停止托管时终止 serve 子进程（terminate→超时 kill），确认端口释放；AUTOlive 侧新建 WS 消费者模块连接 `ws://127.0.0.1:<port>/ws`（默认 8765，端口可配），`Authorization: Bearer <token>` 鉴权；WS 连接连续 3 次失败移交托管层（与失控防护计数对齐），移交期间消费者保持退避重连，serve 拉起后端口探活通过即自然恢复。代码归属（G8）待 Phase 4 终门裁决：当前按复制唯一副本范式起草，pip install -e 为备选；复制落点为 AUTOlive 仓库 `danmaku_listener/`（类比 `edtalk/` 先例），复制工具复用 `Scripts/` 既有复制脚本模式。
- 鉴权与 token：AUTOlive 托管层生成随机 token 经环境变量 `DANMAKU_TOKEN` 注入子进程（备选：受限权限文件注入）；强制注入开关 `danmaku_listener.require_token`（默认 true，关闭时仅依赖 loopback 边界，限开发态）。
- 消息契约：按契约 v1（docs/contract/schema.json，16 类 = 8 业务 + 8 系统）消费；按 category 分流（business→互动处理，system→状态处理）；未知 type 忽略并计数（additive-only 契约）；按 envelope.msg_id 去重，去重存储复用 my_handle 既有去重机制与窗口参数（内存态，重启后冷启动）；同房间 seq 单调，跳跃时等待 GAP 确认——等待期内后续消息缓冲（上限 1000 条/房间，超限按背压同序丢弃低优先级），GAP 到达或超时 10s（1 个心跳周期）后按 approx 降级放行并告警。
- business 消息逐类映射：DANMU/GIFT/SUPER_CHAT→对话链触发（复用现有弹幕→LLM→TTS 链）；ENTER_ROOM/LIKE→计数与既有播报路径；ROOM_STATS→计数存储与 UI 展示；SOCIAL→计数/播报；LIVE_STATUS_CHANGE→开播/下播状态机（联动下播裁剪）；下播窗口内新到 business 消息仍记录（danmu 表/弹幕文件）但不触发对话链互动，开播（live=true）复位状态机并恢复互动；全部映射进现有 my_handle.py 交互链，不重建处理逻辑。
- system 消息矩阵：HEARTBEAT（10s，3 周期未收→失联告警——告警形态为服务状态条胶囊+日志，无独立通知渠道；失联持续 60s→托管层判进程僵死并重拉；失联判定基于组件级 WS 通道心跳，不随单平台引擎 failover 切换误触发，平台级引擎状态经 ENGINE_STATUS 呈现）；托管层重拉成功后由托管层以首个 HEARTBEAT 到达闭合失联告警并自行计算呈现恢复时长（RECOVERED 仅覆盖进程内慢速恢复时长呈现；进程内恢复场景由恢复后首个 HEARTBEAT 到达闭合失联告警）；GAP（窗口+reason+approx 呈现）；下播裁剪——收到 LIVE_STATUS_CHANGE(live=false) 后的 GAP 窗口不再做历史缺漏告警，并清空互动队列中低优先级待处理消息（DANMU/ENTER_ROOM/LIKE），保留 GIFT/SUPER_CHAT；NEEDS_LOGIN（interactive_login QR/URL 在 AUTOlive UI 呈现，视频号扫码为常规路径需常驻入口，操作后引擎自动恢复；多平台并发登录请求逐个队列呈现）；ENGINE_STATUS（当前引擎标识展示 protocol:x/proxy:x/fallback:x）；ROUTE_FAILED（reason_code/fix_hint/docs_anchor 三段式直接呈现）；BACKPRESSURE（窗口丢弃计数呈现）；RECOVERED（恢复时长告知）；ROOM_STATUS（在线状态展示）。
- 配置数据节（G6）：config.json 新增 `danmaku_listener` 节——WS 端口、`require_token`（默认 true）、token 注入方式（env/file）、平台启用开关（按就绪梯度默认 B站/斗鱼/抖音，逐平台独立）、NEEDS_LOGIN 常驻入口开关、旧适配器退役开关位（G7 预留，Phase 4 裁决通过才生效）；运行时阈值（心跳 10s/3 周期/60s、seq 超时 10s、退避 1s/30s、防护 3 次）首版为消费端命名常量不进配置；托管层将配置映射为 serve 启动参数（端口/平台列表经 CLI 参数、token 经环境变量，组件 CLI 参数形态实施时对齐）。
- 平台上线梯度：首发就绪平台（B站/斗鱼/抖音），preflight 通过即可启用；B站/斗鱼 token 实测失败时首发收缩为实测可用平台（启用开关逐平台独立，不互相阻塞）；24h 真实连接漂移门禁为商用交付前置（个人使用阶段不阻塞）；虎牙 draft、快手游客 token、视频号结构校准为上游遗留实测项——AUTOlive 侧以就绪状态在 UI 明示，不承诺未验证平台。
- 复用前提（P1 首任务逐项核验存在性与接口签名，不符即回报修订）：my_handle 既有去重机制与窗口参数（utils/my_handle.py 直播消息存储去重区域）、服务状态条胶囊组件及其置红调用（frontend/ui/ 服务状态条，音频整合交付）、既有播报路径入口（my_handle 播报函数）、websockets≥13 与 AUTOlive 既有依赖树无版本冲突（uv/pip-compile 统一依赖解析检查一次）。部署硬约束：serve 运行期间 AUTOlive 控制台（WebUI）不得公网暴露（WS 无 TLS、Bearer 明文）；token 随托管层每次重拉轮换。
- 测试基线：消费者模块单测（鉴权头注入/重连——指数退避 1s 起上限 30s、连续 3 次连接失败移交托管重拉、重连后去重与 seq 状态延续/category 分流/msg_id 去重/seq 跳跃与 10s 超时降级与等待期缓冲上限/未知 type 计数/16 消息类型路由）+ 离线冒烟（listen --replay demo.jsonl 链路）+ serve 连通冒烟；websockets 客户端依赖 ≥13（additional_headers 参数名）在 AUTOlive 侧 requirements 明确。
- 合规边界：专用监听账号（严禁客户主账号）；抖音 proxy 引擎启用前完成根 CA 与 hook 单独知情确认项。合规是商业模式可行性问题而非交付清单：商业签约/定价前取得专业法律意见或以最小规模实测风险边界，并设计商业退路（仅支持官方开放 API 的平台 / 自托管工具+客户自担账号责任模式）写入组件侧 docs/ops/compliance-review.md 风险章节；个人使用阶段不受阻。
- 消费者并发与队列：WS 消费者为独立 asyncio 任务 + 自身有界主队列（上限 500 条，溢出按背压同序丢弃低优先级并计数），经队列投递至主处理线程执行 my_handle 交互链，不阻塞 WS 读循环。
- 首版单房间：消费者首版绑定单房间（对齐现有单直播间架构），多房间为后续扩展。
- 鉴权失败处理：token 鉴权失败（401/403）立即告警置红、不自动重试（重试无意义），等待人工介入或配置修正。
- 信封校验：envelope 必填字段缺失的消息丢弃并计数 + 日志记录（契约反向防御）。
- 扫码 UI 安全与状态：interactive_login.qr_image_b64 渲染复用既有字幕页 XSS 转义模式（data:image 安全渲染）；QR 过期（expires_at）后呈现过期态，依赖引擎重发新 NEEDS_LOGIN 刷新，UI 展示最新一条。
- 总开关分离：config 新增 `danmaku_listener.enabled` 总开关（默认 false，false 时托管不拉起 serve、消费者不启动），与旧链路退役开关（G7 预留位）语义分离。
- 结构化日志：消费者关键事件（连接/断连/移交/重拉/消息分流/丢弃计数）结构化日志，携带 room_id/seq/msg_id 关键字段。
- 模块落点：组件副本落 `danmaku_listener/`（G8 裁决后生效），消费者接线模块落 `utils/danmaku_consumer.py`（WS 消费 + 队列桥 + 分发），托管接线复用 utils/service_orchestrator.py 的 ManagedProcess。
- 契约漂移防护：G8 裁决为复制时，`python scripts/export_contract.py --check` 纳入 AUTOlive 侧测试流程（复制后运行）。
- 既有风险观察：弹幕文本进 LLM 对话链的 prompt injection 面为既有风险（旧适配器同样暴露），多平台接入扩大暴露面——净化防护随既有 gpt 链路，不因本次整合新增防线，记录在案。
- 商用前置与客户校验（与 P1 并行，不阻塞编码）：用 `listen --replay demo.jsonl` 离线冒烟链路向目标客户演示验证；校验第一问"客户直播间在哪些平台"，答案作为平台优先级唯一输入重排就绪矩阵；北极星指标（互动响应延迟、GIFT/SUPER_CHAT 触发转化）随 P1 验收定义；为每平台估月维护工时基线写入 SLA 文档，退出阈值=连续 2 个月超限即从就绪矩阵降级，"兜底"定义为降级为人工监听或直接下线（随 SLA 文档定案）。
<!-- /autoplan-accepted:ceo -->

<!-- autoplan-accepted:dx -->
- 分阶段上手路径（DX）：AUTOlive 侧提供三阶段 Hello World——阶段 1 独立 serve + 任意 WS 客户端收 demo 流；阶段 2 单平台（B 站）跑通数字人对话链；阶段 3 全配置启用。每阶段一条可复制命令 + 预期现象，写入 §5 或模块 README；冒烟脚本输出各步耗时（端到端 TTHW 可见，目标 replay 冒烟 <2 分钟、全链路部署 ≤10 分钟）。
- 三段式全覆盖（DX）：reason_code+fix_hint+docs_anchor 为所有面向 UI 错误的最小契约——鉴权 401/403（cause=token 不匹配或轮换未同步，fix=核对 DANMAKU_TOKEN 注入，docs_anchor 指向部署文档）；托管重拉 3 次失败（fix_hint=端口占用检查命令 + serve 日志路径）；端口占用（EADDRINUSE）与"serve 未启动"在探活失败中区分呈现；NEEDS_LOGIN QR 过期且引擎未重发时 UI 提供手动重试出口；托管层调用组件 preflight 的失败输出按三段式转呈 UI。
- docs_anchor 解析约定（DX）：P1 首任务与组件侧确认 anchor 语法（形如 docs/platform/bilibili.md#token）与 URL 映射规则（映射为组件副本内文档相对路径），schema 侧约束格式；UI 呈现为可点击文档链接。
- 配置与参数面（DX）：G6 数据节补 G7 键名 `legacy_adapter_retired`（裁决通过才生效）；CLI 参数表（--port/--platforms 等）P1 首任务与组件侧实核后定死并写入配置注释，与配置键一一映射；去重窗口等继承参数在配置文档列出当前值与来源；调参逃生门小节说明各命名常量的落点文件与调整时机（首版不进配置的裁决不变）。
- 升级与版本（DX）：上游组件更新流程 = 重跑复制脚本（版本戳变化可见）→ `export_contract.py --check` → 冒烟脚本，三步写入模块 README；消费者启动时断言 envelope.contract_version 兼容（1.x 接受，2.x 拒绝并告警）。
- 文档单源澄清（DX）：实现区义务块为 /autoplan 评审导出形态，实施义务以 Review record 的 autoplan-accepted 块为权威源，两处内容由工具保持同步。
<!-- /autoplan-accepted:dx -->

<!-- AUTONOMOUS DECISION LOG -->
## Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|-------|----------|----------------|-----------|-----------|----------|
| 1 | ceo | 评审模式 = SELECTIVE EXPANSION | Mechanical | autoplan override | autoplan 固定裁决，不询问 | — |
| 2 | ceo | G1 WS 消费者模块 + G2 serve 托管复用 + G3 business 映射 + G4 system 矩阵 + G5 扫码 UI + G6 config 数据节 | Mechanical | 原则 P1 完整性 + P2 煮沸湖区 | 全部在整合 blast radius 内，CC 工作量 1-2 天（对齐 CEO 摘要口径），原则 P1 要求完整覆盖 16 类消息 | 无 |
| 3 | ceo | G9 就绪平台首发（B站/斗鱼/抖音），未验证平台不承诺 | Mechanical | 原则 P5 显式优先 | 文档就绪矩阵自带梯度，显式优于空头承诺 | 六平台同时上线 |
| 4 | ceo | G7 旧适配器退役开关（默认关、保留配置） | Taste | 原则 P3 务实 / P4 DRY | 与音频整合 so_vits_svc 退役先例对齐，但涉及旧链路取舍 | — |
| 5 | ceo | G8 代码归属：复制唯一副本 vs pip install -e | Taste | 原则 P2 vs 组件文档 | EDTalk 范式（复制）与组件文档（pip -e）冲突，装机分发要求复制 | — |
| 6 | ceo | 原生声部 12 发现处置：7 接受入义务（合规升格/客户校验并行/维护基线/依赖检查/部署硬约束/G8 决策记录/QR 安全）+ 1 factual correction（build-vs-adopt N/A：组件为用户自研在开发项目）+ 1 拒绝（16 类首发分层——路由同链减分支不减工作量）+ 3 Deferred | Mixed | P1+P5 | 评审员有条件通过；接受项全部落义务块 v5 | 六平台同时上线（维持拒绝） |

## Sections 1-11 审查记录（CEO 阶段，SELECTIVE EXPANSION）

### Section 1: Architecture Review

Current scope：G1-G6+G9 已接受，G7/G8 taste 悬置。系统架构（新增组件与既有关系）：

```
DanmakuListener serve (独立进程, ManagedProcess 托管)
  └─ ws://127.0.0.1:8765/ws (Bearer token, loopback)
       └─ utils/danmaku_consumer.py (新建: asyncio 任务 + 有界队列 500)
            ├─ category=business → 主处理线程 → my_handle 交互链 (对话/弹幕表/文件)
            └─ category=system  → 状态矩阵 → 服务状态条胶囊 / 扫码对话框 / 日志
前端: frontend/ui (服务状态条 + NEEDS_LOGIN 常驻入口)
```

数据流四路径：happy（消息→分流→处理）；nil（envelope 缺字段→丢弃计数）；empty（空 content/全可选 payload→schema 放行，处理层忽略）；error（WS 断/上游崩→退避重连→移交托管重拉）。状态机：serve 托管（stopped→starting→running→zombie→restarting→failed_3x，防护计数防回环）；登录态（ok→needs_login→scanning→ok）。耦合：consumer 单向依赖契约 schema 与 my_handle 入口，无反向耦合；与旧适配器无共享状态（G7 分离）。SPOF：serve 进程（托管+重拉覆盖）；my_handle 主线程（既有单点，非新增）。安全架构：loopback+Bearer+token 轮换+WebUI 不公网暴露（义务块）。失败场景：引擎 failover 不误触重拉（心跳组件级）；serve 僵死 60s 重拉。回滚：`danmaku_listener.enabled=false` 总开关（默认 false）即回滚路径，旧链路不受 G8/G7 悬置影响——回滚时间 <1 分钟。**发现 A1/A2 已入义务块**（队列桥/单房间）。10x 弹性：热直播百条/秒下 asyncio 消费+有界队列不积压，LLM 链为既有瓶颈非新增。

### Section 2: Error & Rescue Map

映射新 codepath（consumer/托管/桥接）错误类与救援（义务块已定义为主）：WS 连接失败→退避重连 1s-30s→3 次移交托管（ConnectionRefused/TimeoutError）；token 鉴权失败→立即告警不重试（AuthError）；JSON 解析失败→忽略+计数+日志（JSONParseError）；envelope 缺字段→丢弃+计数（ValidationError）；seq 跳跃→缓冲 1000/房间→GAP 或 10s 降级（SeqGapError 语义）；队列溢出→同序丢弃+计数（QueueOverflow 语义）；心跳失联→告警→60s 僵死重拉（HeartbeatTimeout）；托管拉起失败→3 次防护停止（ProcessSpawnError）；关停超时→kill+端口确认（ProcessKillTimeout）；my_handle 处理异常→既有 error_handler.py 兜底（既有链）。无 catch-all 新增；每个救援路径有测试锚点（义务块测试基线）。GAPS：无——全部路径有救援与用户可见形态（胶囊/日志/计数）。

### Section 3: Security & Threat Model

攻击面增量：WS 端口（loopback 限定+Bearer，token 随重拉轮换——义务块）；扫码对话框（QR base64 渲染 XSS 面→复用既有转义模式，义务块）；平台消息 payload（弹幕文本→LLM prompt injection——**既有风险**，多平台扩大暴露，义务块记录在案，非本次新增防线）；配置面（config 节新增键无执行语义）。威胁表：伪造弹幕流（token 泄露→轮换+loopback 缓解，likelihood 低/impact 高/缓解 Y）；QR 替换（loopback+token 下不可达，缓解 Y）；WebUI 远程暴露（硬约束写入义务，缓解 Y）。无新 secrets 落盘（token 进程内生成注入）；审计日志=结构化消费者日志（义务块）。

### Section 4: Data Flow & Interaction Edge Cases

数据流：`WS raw → JSON parse → envelope 校验 → category 分流 → payload 分发 → danmu 表/状态/UI`，阴影路径全部映射（nil/empty/解析失败/缺字段/溢出/乱序——见 Section 2）。异步排序：单生产者（WS 读）单消费者（主线程）FIFO 队列，无共享可变状态竞争；seq 等待缓冲与主队列独立，溢出策略同序。交互边界：启动顺序（serve 未起→连接失败→退避+移交，自然恢复）；AUTOlive 重启（去重冷启动——义务块）；多 QR 并发（队列呈现）；重复扫码（最新覆盖）；下播窗口消息（记录不互动，义务块）。全部边界有定义，无未处理缺口。

### Section 5: Code Quality Review

模块组织：契约驱动单消费者模块 + 既有托管复用，符合 EDTalk/音频整合范式（复制副本+薄接线层）；无重复实现（去重/托管/告警全复用）；命名显式（danmaku_consumer/ManagedProcess/服务状态条）；16 类 switch 显式分支优于抽象映射表（P5）。无过度工程（总开关/退役开关分离而非统一插件化）；无欠工程（全部错误路径有救援）。无新分支超过 5 层的方法级风险。

### Section 6: Test Review

测试图（义务块测试基线为骨架）：WS 层（鉴权头/重连退避/移交）单测；契约层（分流/去重/seq/超时/缓冲/未知 type/16 类型路由）单测；托管层（探活/重拉/防护计数/关停）单测；桥接层（队列溢出/投递顺序）单测；集成（replay 冒烟/serve 连通）；契约漂移检查（复制场景）。失败路径测试锚点：连接失败→移交、鉴权失败→告警、心跳 60s→重拉、防护 3 次→停止。边界：空 content/全可选 payload/去重窗口冷启动。2am Friday 测试=断链重连后消息不重不丢（去重+seq 联合）；chaos 测试=serve 半路 kill 后恢复曲线。金字塔：单测为主+2 冒烟，无倒置；无时间/随机依赖（退避参数注入测试）；契约漂移检查为 additive-only 的回归防线。**S-T1 已入义务块**。

### Section 7: Performance Review

热直播峰值（百条/秒）：asyncio 单任务消费 + 有界队列 500 上限——溢出策略保证有界延迟而非无限积压；LLM/TTS 对话链为既有吞吐瓶颈（与旧链路同，非新增）；内存上界明确（队列 500 + seq 缓冲 1000/房间 + 去重窗口复用 my_handle 参数）；组件进程 RSS 基线 54.1MB（预算文档）；无新 DB 查询（danmu 表复用）；无连接池压力（单 WS 连接）。无 N+1 类问题。首版单房间使 10x 场景（多房间）天然推迟。无发现需行动。

### Section 8: Observability & Debuggability Review

日志：消费者结构化日志义务（连接/断连/移交/重拉/分流/丢弃计数 + room/seq/msg_id 字段）；指标：胶囊状态（健康/置红）+ 引擎标识展示 + 背压计数呈现；告警形态=胶囊+日志（无独立通知渠道——设计文档既有裁决，义务块显式）；3 周后 debug：GAP 窗口（时间边界）+ 结构化日志 + seq 连续性可重建任意断档；runbook：ROUTE_FAILED 三段式 docs_anchor 直接指向组件侧运维手册；RECOVERED/心跳闭合让告警生命周期可追溯。缺口：无——观察义务已入块。

### Section 9: Deployment & Rollout Review

部署序列（P1）：依赖冲突检查（复用前提）→ G8 裁决落地（复制/pip -e）→ config 节（enabled 默认 false）→ 托管接线（ManagedProcess）→ 消费者接线 → replay 冒烟 → serve 连通冒烟 → 启用开关打开。回滚：enabled=false（<1 分钟，不触碰旧链路）；完全回滚=git revert 整合提交。部署风险窗口：新旧链路并存期由 enabled 总开关保证互斥（义务块分离语义）；环境 parity=单机 Windows（与既有部署同构）。冒烟后 5 分钟检查：胶囊绿色 + HEARTBEAT 到达 + demo 消息进弹幕表。无迁移（config 节为增量，ensure-default 模式扩展——既有范式）。

### Section 10: Long-Term Trajectory Review

技术债：G8 复制场景的双副本漂移（版本戳+契约漂移检查缓解——义务块）；旧适配器滞留（G7 裁决处置，退役开关位已预留）。路径依赖：契约 v1 additive-only 使消费端向前兼容；consumer→my_handle 单向依赖不阻塞未来输入源（连麦/语音走同一事件总线模式——dream state 的平台潜力）。知识集中度：契约 schema 机读+接入指南双文档，新工程师可自学。可逆性 4/5（总开关+配置保留，唯一接近单向门的是 danmu 表双写格式）。12 个月问题：consumer 模块以契约为界，DanmakuListener 侧引擎迭代不冲击 AUTOlive 消费面——架构支持轨迹。**Deferred 项**（差异化假设/追赶节奏）记录于 CEO 摘要。

### Section 11: Design & UX Review（G5 扫码 UI 触发，非跳过）

用户流程：
```
服务状态条(常驻) ──NEEDS_LOGIN──> 扫码对话框
                                    ├─ LOADING: QR 解码中
                                    ├─ READY: QR 展示 + expires_at 倒计时
                                    ├─ EXPIRED: 过期态（引擎重发后自动刷新）
                                    ├─ SUCCESS: 自动恢复→对话框关闭+胶囊恢复
                                    └─ 多平台: 队列逐个呈现
```
信息架构：入口常驻（视频号常规路径）；状态覆盖五态齐备（LOADING/READY/EXPIRED/SUCCESS + 多平台排队）；SUCCESS 闭环由心跳闭合语义（义务块）驱动，无需用户确认——情绪弧线"告警→扫码→自动恢复"无死角。AI slop 风险低（Quasar 既有对话框组件+既有胶囊范式）；设计系统对齐（frontend 设计令牌系统）；无障碍沿用 Quasar 兜底（TODOS 既有 ARIA 挂账不重复）。**QR 过期态发现已入义务块**。建议：实施后随 /design-review 实测（Phase 2 未跑，本节覆盖设计意图层）。

## Required Outputs（CEO 阶段）

### NOT in scope

| 项 | 处置 | 理由 |
|---|---|---|
| 多房间支持 | Deferred | 首版单房间对齐现有架构（Section 1 A2） |
| G7 旧链路退役开关落地 | Phase 4 taste | 悬置待终门 |
| G8 代码归属落地 | Phase 4 taste | 悬置待终门（决策记录要求已备） |
| 差异化假设书面化 | Deferred→TODOS | 产品战略议题 |
| draft 平台校准节拍 | Deferred→TODOS | 组件侧协作节奏 |
| 16 类首发分层 | 拒绝 | 路由同链减分支不减工作量（原生声部 3.2） |
| build-vs-adopt 决策记录 | N/A | 组件为用户自研在开发项目（factual correction 4.1） |
| HTTP 回调通道 | N/A | 组件 v1 未实现（预留） |
| DanmakuListener 侧遗留实测五项 | N/A | 上游职责（虎牙/快手/视频号/24h/客户校验线下） |

### What already exists

| 子问题 | 既有代码 | 复用 |
|---|---|---|
| 子进程托管/重拉/防护 | utils/service_orchestrator.py:73 ManagedProcess（音频整合交付） | Y |
| 告警呈现 | frontend 服务状态条胶囊（音频整合交付） | Y |
| business 消息处理 | my_handle 交互链（弹幕文件/danmu 表/去重/对话触发） | Y |
| 处理链异常兜底 | utils/error_handler.py | Y |
| base64 图像安全渲染 | 字幕页 XSS 转义三件套（d38950f4） | Y |
| 配置节范式 | config.json + frontend/config/settings.py + ensure-default | Y |
| 旧弹幕链路 | utils/platforms/* 11 适配器 | 并存（G7 裁决对象） |

### Dream state delta

```
CURRENT: 进程内 11 适配器 / 主账号 cookie / 无契约
   → THIS PLAN: serve 托管 + WS 消费者 + 16 类契约 + 系统消息可观测 + 合规监听账号
      → 12-MONTH: 全输入源统一事件总线 + 商用交付（合规/SLA/预算闭环）
```

本计划完成理想态的"输入层统一"环节；商用前置义务（合规法律意见/维护基线/客户校验）是通往理想的显式关卡，已入义务块而非悬置。

### Error & Rescue Registry（按层组织，实现深度）

| 层 | CODEPATH | 异常类 | RESCUED | 动作 | 用户所见 |
|---|---|---|---|---|---|
| WS | danmaku_consumer#connect | ConnectionRefused/Timeout | Y | 退避重连 1-30s→3 次移交 | 胶囊状态+日志 |
| WS | danmaku_consumer#auth | AuthError(401/403) | Y | 立即告警不重试 | 胶囊置红 |
| 契约 | danmaku_consumer#parse | JSONParseError | Y | 忽略+计数 | 计数可见 |
| 契约 | danmaku_consumer#validate | ValidationError | Y | 丢弃+计数 | 计数可见 |
| 契约 | danmaku_consumer#seq | SeqGap | Y | 缓冲→GAP/10s 降级 | GAP 呈现 |
| 队列 | danmaku_consumer#queue | QueueOverflow | Y | 同序丢弃+计数 | 背压计数 |
| 心跳 | danmaku_consumer#heartbeat | HeartbeatTimeout | Y | 3 周期告警→60s 重拉 | 胶囊+日志 |
| 托管 | orchestrator#spawn | ProcessSpawnError | Y | 3 次防护停止 | 胶囊置红 |
| 托管 | orchestrator#shutdown | ProcessKillTimeout | Y | terminate→kill+端口确认 | 无感 |
| 登录 | consumer#needs_login | LoginExpired | Y | QR 呈现→引擎自动恢复 | 扫码对话框 |
| 业务 | my_handle#chain | 既有异常类 | Y | 既有 error_handler | 既有表现 |

### Failure Modes Registry

| CODEPATH | FAILURE MODE | RESCUED? | TEST? | USER SEES? | LOGGED? |
|---|---|---|---|---|---|
| WS 连接 | 断连/拒绝 | Y | Y | 胶囊+日志 | Y |
| WS 鉴权 | token 失败 | Y | Y | 置红 | Y |
| 消息解析 | 畸形 JSON | Y | Y | 计数 | Y |
| 信封校验 | 缺必填字段 | Y | Y | 计数 | Y |
| seq 顺序 | 跳跃 | Y | Y | GAP 呈现 | Y |
| 队列 | 溢出 | Y | Y | 背压计数 | Y |
| 心跳 | 失联 3 周期 | Y | Y | 胶囊+日志 | Y |
| 心跳 | 僵死 60s | Y | Y | 胶囊状态 | Y |
| 托管 | 拉起失败 3 次 | Y | Y | 置红 | Y |
| 托管 | 关停挂起 | Y | Y | 无感 | Y |
| 登录 | QR 过期 | Y | Y | 过期态+自动刷新 | Y |
| 业务链 | 处理异常 | Y | 既有 | 既有表现 | Y |

CRITICAL GAPS：0（全部 RESCUED=Y、TEST=Y、非静默）。

### Stale Diagram Audit

本计划触及文件中既有 ASCII 图：无（specs/integration 历史计划为独立文档）。audio-integration-voice-pipeline.md 的架构描述不受本次影响。0 处过期。

### Completion Summary（CEO 阶段）

```
+====================================================================+
|            MEGA PLAN REVIEW — COMPLETION SUMMARY                   |
+====================================================================+
| Mode selected        | SELECTIVE EXPANSION                         |
| System Audit         | 既有弹幕链=进程内11适配器/主账号cookie；EDTalk 托管范式可复用 |
| Step 0               | SELECTIVE EXPANSION；G1-G6+G9 接受，G7/G8 taste 悬置 |
| Section 1  (Arch)    | 2 issues（队列桥/单房间），已入义务          |
| Section 2  (Errors)  | 12 error paths mapped, 0 GAPS               |
| Section 3  (Security)| 3 issues（QR XSS/依赖冲突/部署硬约束），已入义务 |
| Section 4  (Data/UX) | 9 edge cases mapped, 0 unhandled            |
| Section 5  (Quality) | 0 issues found                              |
| Section 6  (Tests)   | Diagram produced, 1 gap（契约漂移流程），已补 |
| Section 7  (Perf)    | 0 issues（有界队列/内存上界明确）            |
| Section 8  (Observ)  | 0 gaps（结构化日志义务已入块）               |
| Section 9  (Deploy)  | 1 risk（总开关分离），已补                   |
| Section 10 (Future)  | Reversibility: 4/5, debt items: 2            |
| Section 11 (Design)  | 1 issue（QR 过期态），已补                   |
+--------------------------------------------------------------------+
| NOT in scope         | written (9 items)                           |
| What already exists  | written (7 rows)                            |
| Dream state delta    | written                                     |
| Error/rescue registry| 11 rows, 0 CRITICAL GAPS                    |
| Failure modes        | 12 total, 0 CRITICAL GAPS                   |
| TODOS.md updates     | 2 items written                             |
| Scope proposals      | 9 proposed, 7 accepted                      |
| CEO plan             | written (ceo-plans/2026-09-27-danmaku-listener-integration.md) |
| Outside voice        | codex unavailable (400 InvalidParameter)    |
| Lake Score           | N/A（autoplan 自动裁决，无覆盖型提问）       |
| Diagrams produced    | 3 (system arch / hosting state / login flow) |
| Stale diagrams found | 0                                           |
| Unresolved decisions | 2 (G7/G8 taste — Phase 4 gate 呈现)         |
+====================================================================+
```

Spec Review Loop 指标：3 轮，34 发现全部修复，质量分 5→7→8。原生声部：有条件通过，12 发现（7 入义务/1 factual correction/1 拒绝/3 Deferred）。

## Phase 2 记录

**SKIPPED — no UI scope detected**（Phase 0 检测：2 处匹配均为 platform 子串误报）。G5 扫码 UI 设计意图层已由 CEO Section 11 覆盖；实施后建议 /design-review 实测。非完成评审。

## Phase 2.5 DX 审查记录（DX POLISH，autoplan）

### Developer Persona Card
```
TARGET DEVELOPER PERSONA
========================
Who:       AUTOlive 维护者本人（单人开发者 + AI 辅助，Python/asyncio 熟练）
Context:   为自己的直播系统接入弹幕监听组件；未来为装机用户排障
Tolerance: 时间碎片化——单步卡壳超过 10 分钟即切换任务，需要明确"下一步跑什么"
Expects:   复制即用命令、失败消息带修复指引、契约变更可机读检测
```

### Developer Empathy Narrative
"我打开整合就绪文档，先看 §5 部署命令——第一条 pip install -e 和义务块里'按复制范式执行'打架（已修：§5 顶部明示）。我想先跑通再说，replay 冒烟一条命令 3-7ms 有输出，很顺。然后接 AUTOlive 侧：config 节、托管接线、消费者模块——步骤都在义务块里但散在 20 条中，我不知道先跑哪个、跑到哪一步算成功（已修：三阶段上手路径）。serve 连不上时，我看到胶囊红了但不知道是端口被占还是进程没起（已修：EADDRINUSE 区分）。最后平台报 ROUTE_FAILED，三段式直接给了修复指引和文档锚点——这一刻体验很好，我希望所有错误都这样（已修：三段式全覆盖）。"

### Competitive DX Benchmark（参考基准——Aside/WebSearch 不可用，用 gstack TTHW tiers）
| 工具 | Start → result | 时间 + 证据 | DX 选择 | 来源 |
|---|---|---|---|---|
| 本整合（replay 冒烟）| 克隆 → 冒烟通过 | 估计 ~5 分钟（复制+依赖+命令） | 一条命令出消息 | 计划 §5（估计，待实测） |
| 本整合（全链路）| 部署 → 数字人回复首条弹幕 | 估计 ~10 分钟 | 分阶段验证 | 义务块（估计） |
| Tier 基准 Champion | — | < 2 min | 一键 | gstack TTHW tiers |
| Tier 基准 Competitive | — | 2-5 min | — | gstack TTHW tiers |

TTHW 目标（0C gate，auto-decide）：replay 冒烟 < 2 分钟（Champion 级，现有 3-7ms/条延迟支撑）；全链路部署 ≤ 10 分钟（Needs Work → 冒烟脚本+三阶段路径收敛）。

### Magical Moment（0D，P5 最低 effort 载具）
载具 = **一键冒烟脚本**：`python Scripts/smoke_danmaku.py` 拉起 serve → 消费者连接 → demo 消息进弹幕表 → 各步耗时输出 → PASS/FAIL。开发者第一刻看到"消息从平台流到数字人弹幕表"的完整证据。

### Developer Journey Map
```
STAGE           | DEVELOPER DOES                  | FRICTION POINTS            | STATUS
----------------|---------------------------------|----------------------------|--------
1. Discover     | 读整合就绪文档                  | 部署形态歧义               | fixed（§5 明示）
2. Install      | 复制组件/依赖检查               | 依赖冲突未知               | ok（复用前提核验）
3. Hello World  | replay 冒烟                     | 无 AUTOlive 侧路径         | fixed（三阶段路径）
4. Real Usage   | config 节+托管+消费者           | CLI 参数未定死             | fixed（参数表义务）
5. Debug        | 看胶囊/日志                     | EADDRINUSE 不区分          | fixed（三段式全覆盖）
6. Upgrade      | 重跑复制脚本                    | 升级步骤未写               | fixed（三步流程）
```

### First-Time Developer Confusion Report（要点）
T+0:00 打开文档 → 部署形态歧义（已修）；T+0:30 replay 冒烟通过（顺）；T+2:00 AUTOlive 侧接线步骤不明（已修：三阶段）；T+5:00 serve 连接失败无法诊断（已修：区分呈现）；T+8:00 平台失败三段式指引（亮点，推广到全部错误面——已修）。

### DX Scorecard（POLISH，before → after-amendment）
```
+====================================================================+
|              DX PLAN REVIEW — SCORECARD                             |
+====================================================================+
| Dimension            | Score   | Trend  |
|----------------------|---------|--------|
| Getting Started      | 5 → 8   | ↑      |
| API/CLI/SDK          | 7 → 8   | ↑      |
| Error Messages       | 6 → 9   | ↑      |
| Documentation        | 6 → 8   | ↑      |
| Upgrade Path         | 6 → 8   | ↑      |
| Dev Environment      | 7 → 8   | ↑      |
| Community            | 5 → 5   | —（私有单机产品，生态维度不适用，无行动项） |
| DX Measurement       | 5 → 7   | ↑      |
+--------------------------------------------------------------------+
| TTHW                 | ~10 min → <2 min（replay）/ ≤10 min（全链路） |
| Competitive Rank     | Needs Work → Competitive（replay 链路）       |
| Magical Moment       | designed via 一键冒烟脚本                      |
| Product Type         | Library/SDK（WS 契约消费组件）                 |
| Mode                 | DX POLISH                                      |
| Overall DX           | 6 → 8                                          |
+====================================================================+
| DX PRINCIPLE COVERAGE                                               |
| Zero Friction      | covered（三阶段路径+冒烟脚本）                 |
| Learn by Doing     | covered（replay demo 链路）                    |
| Fight Uncertainty  | covered（三段式全覆盖）                        |
| Opinionated + Escape Hatches | covered（默认值+调参文档小节）        |
| Code in Context    | covered（骨架示例标注+契约指引）               |
| Magical Moments    | covered（一键冒烟）                            |
+====================================================================+
```

### DX Implementation Checklist（关键项）
```
[ ] 三阶段上手路径每阶段一条命令+预期现象
[ ] 一键冒烟脚本输出各步耗时与 PASS/FAIL
[ ] 每个面向 UI 的错误有三段式（401/EADDRINUSE/重拉失败/preflight/QR 出口）
[ ] CLI 参数表定死并与配置键一一映射
[ ] docs_anchor 解析约定与 schema 约束
[ ] contract_version 兼容断言（1.x 接受 / 2.x 拒绝告警）
[ ] 升级三步流程写入模块 README
[ ] 调参逃生门小节（常量落点+调整时机）
[ ] PYTHONUTF8=1 进托管层 env 注入
[ ] websockets≥13 依赖解析检查
```

### "NOT in scope"（DX）
- 退避上限升为配置项——拒绝（推翻命名常量裁决；调参文档小节覆盖逃生需求）
- 组件 CLI 双入口收敛（danmaku-listen vs python -m）——上游职责，托管层统一 python -m 规避
- 示例升级为生产完整版——拒绝（P3 务实：骨架标注+契约指引已消除误导）
- 社区/生态建设——私有单机产品不适用

### "What already exists"（DX 复用）
- 组件 replay 冒烟链路（3-7ms/条）——三阶段路径的阶段 1 基础
- 三段式失败消息模式（组件沉淀 system-status-three-part）——推广模板
- export_contract.py --check——升级流程第二步
- 14 键三组微指引范式（前端设置页）——config 节文档落点
- 服务状态条胶囊——错误呈现载体

### Decision Audit Trail（DX 阶段补充行）
| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|-------|----------|----------------|-----------|-----------|----------|
| 7 | dx | DX POLISH 模式 + Persona=集成开发者 + TTHW 目标（replay<2min/全链路≤10min）+ Magical moment=一键冒烟 | Mechanical | autoplan override | autoplan 固定裁决 | — |
| 8 | dx | 原生声部 16 发现：13 接受入义务（三阶段/三段式全覆盖/anchor 约定/参数表/键名/版本断言/升级流程/调参文档/双源澄清等）+ 1 factual correction（TTHW 措辞）+ 2 拒绝（退避升配置、示例生产化） | Mixed | P1+P5 | DX 义务全部落义务块 | 退避升配置项 |

### Unresolved Decisions（DX）
无新增（taste 项仍为 G7/G8，Phase 4 终门）。

<!-- autoplan-accepted:eng -->
- token 生命周期（修订 A-1）：消费者每次重连前从共享源读取当前 token（文件注入或 orchestrator 句柄），不缓存旧值；401/403 触发一次 token 刷新后重试一次，仍失败才告警置红；token 轮换兼作 serve 世代信号。
- 消费者双通道（修订 A-2/B-2）：system 消息（心跳计时/seq/GAP 判定/ENGINE_STATUS 等）在 WS 读循环协程内快路径直接处理，不进 500 主队列；仅 business 消息跨线程过队列。8 业务类统一优先级表（服务端丢弃序 = 消费端溢出序 = 队列路由分类）：DANMU/GIFT/SUPER_CHAT/SOCIAL 进队列（GIFT/SUPER_CHAT FIFO 保序），LIKE/ENTER_ROOM/ROOM_STATS 走计数快路径不进对话链队列；优先级表随契约导出防漂移。
- 对话链聚合限速（新增 B-1）：DANMU 进 LLM 链前做窗口聚合（N 条/时间窗合并为一条 prompt 或摘要播报）+ 消费端限速与丢弃预算；GIFT/SUPER_CHAT 保持 FIFO（SUPER_CHAT 可插队）。
- 重拉归口与世代（修订 A-3/A-4）：重拉裁决单一归口托管层（心跳超时或连接失败任一先到为准，计数器唯一，消费者只上报）；重拉即新世代——消费者以世代信号（token 轮换）为界重置 seq 期待与去重窗口。
- 进程树管理（修订 A-5）：Windows 下 terminate→kill 扩展为整棵进程树回收（taskkill /T /F 或 Job Object），抖音 ProxyEngine 子进程不残留；"端口释放确认"升级为"进程树回收确认"，Windows 实跑测试。
- 缓冲放行（修订 B-3）：seq 等待缓冲放行分批注入（不一次性打满主队列）；缓冲动作显式非阻塞（不阻塞 WS 读循环）；下播清队列与已进 LLM 链消息的行为固化为测试预期。
- 安全防线（修订 S-1/S-2/S-3/C-2）：DANMU 文本进 LLM 前长度钳制 + 控制字符/零宽字符剥离，URL 与社交字段不进 prompt（升级原"记录在案"）；UI 渲染 docs_anchor/fix_hint 做 scheme 白名单（仅 https 或组件内相对路径），QR 渲染钳制 MIME 与 base64 大小；token 生成用 secrets.token_urlsafe(≥32 字节)，require_token=false 时状态条胶囊持续示警；托管层子进程 env 契约显式列单（PYTHONUTF8=1、PYTHONPATH、DANMAKU_TOKEN）。
- 依赖钉版（修订 S-4）：websockets 在 AUTOlive 侧 requirements 钉死版本并显式 `from websockets.asyncio.client import connect`（additional_headers 属 asyncio.client 新实现，顶层 connect 13/14.x 为 legacy 参数名 extra_headers——requirements_common.txt:276 当前裸名，P1 依赖解析实核）。
- 执行模型（新增 C-1）：P1 首任务定 asyncio→线程队列桥执行模型（my_handle 链为同步阻塞 → 单 worker 线程 + 线程安全队列，asyncio.Queue 与线程安全队列语义区分），500 上限与溢出行为按此模型设计测试。
- 测试扩充（Eng）：在既定测试基线上补 10 项——token 轮换重连成功、僵死重拉全链（60s→重拉→3 次防护→置红→手动清零）、世代重置、进程树回收（Windows 实跑）、system 快路径延迟断言（队列满载心跳处理 < 阈值）、contract_version 2.x 拒绝、enabled/require_token 开关行为、下播开播状态机、非法 JSON 帧容错计数、优先级表双端一致性。
<!-- /autoplan-accepted:eng -->

## Phase 3 Eng 审查记录（FULL_REVIEW，autoplan）

### Sections 1-4 审查结论

**Section 1 Architecture**：拓扑复用健全（ManagedProcess T-3 计数器/red 态 D10 手动清零语义经声部仓库实证一致）；2 issues（A-1 token/401 矛盾、A-2 system 快路径缺失）+ 4 中项（A-3 归口/A-4 世代/A-5 进程树/B-2 优先级表）全部接受入 eng 义务块。架构图（复用 CEO Section 1 + 修订：消费者双通道、世代信号、进程树回收）。

**Section 2 Code Quality**：复用前提声部实证 5 项全通过（ManagedProcess/服务状态条/my_handle 去重/copy_edtalk.py 先例/websockets 裸名疑点）；0 新 DRY 违规（全复用策略）；C-1 执行模型、C-2 env 契约接受入义务。模块结构沿用义务块落点。

**Section 3 Test Review**：测试图覆盖消费者连接行为（义务块基线）+ 托管状态机 + 故障注入 10 项扩充（token 轮换重连/僵死重拉全链/世代重置/进程树 Windows 实跑/system 快路径延迟断言/contract_version 拒绝/开关行为/下播状态机/非法 JSON/优先级双端一致）；E2E 判定：断链恢复与端到端对话链 [→E2E]；无 LLM prompt 变更（映射层复用现有链）→ 无 eval 套件要求。回归铁律：旧适配器链路在 enabled=false 下保持不动 = 天然回归保护（开关互斥）+ 下播状态机测试固化 B-4。测试计划工件已写盘（admin-main-eng-review-test-plan-20260927-063841.md）。

**Section 4 Performance**：B-1 对话链吞吐为真瓶颈（10x 负载下 500 队列 <1s 缓冲）→ 聚合/限速/丢弃预算入义务；B-3 缓冲放行分批；无 N+1（无新 DB 查询）；内存上界不变（队列 500+缓冲 1000）；组件 RSS 54.1MB 基线。

### ENG DUAL VOICES — CONSENSUS TABLE（Codex unavailable，六格 N/A）
| Dimension | Claude（原生） | Codex | Consensus |
|---|---|---|---|
| 1. Architecture sound? | 有条件（A-1/A-2 修订后健全） | N/A | N/A |
| 2. Test coverage sufficient? | 义务块+10 项扩充后充分 | N/A | N/A |
| 3. Performance risks addressed? | B-1 聚合限速后 | N/A | N/A |
| 4. Security threats covered? | S-1..S-3 防线后 | N/A | N/A |
| 5. Error paths handled? | 三段式全覆盖+世代语义 | N/A | N/A |
| 6. Deployment risk manageable? | 进程树+依赖钉版后 | N/A | N/A |

### Failure Modes Registry（Eng 增量关键行）
| CODEPATH | FAILURE MODE | RESCUED? | TEST? | USER SEES? | LOGGED? |
|---|---|---|---|---|---|
| token 轮换 | 旧 token 重连 401 | Y（刷新重试） | Y（新增） | 置红仅终态 | Y |
| 高负载 | 心跳延迟误判僵死 | Y（system 快路径） | Y（延迟断言） | 无误告警 | Y |
| 10x 负载 | 对话链饱和 | Y（聚合/限速/预算） | Y | 摘要播报 | Y |
| serve 重拉 | seq 世代错位 | Y（世代重置） | Y | 无盲窗 | Y |
| Windows | 孤儿 proxy 进程 | Y（taskkill /T） | Y（实跑） | 端口可用 | Y |
| 依赖 | websockets API 不匹配 | Y（钉版+显式 import） | Y | 启动即报非运行时 | Y |

CRITICAL GAPS：0（全部三要素齐备）。

### Completion Summary（Eng 阶段）
- Step 0 Scope Challenge：scope accepted as-is（autoplan never-reduce；结构=Original arrangement）
- Architecture Review: 6 issues found（2 高 4 中，全接受）
- Code Quality Review: 2 issues found（C-1/C-2，接受）
- Test Review: diagram produced, 10 gaps identified（全接受扩充）
- Performance Review: 2 issues found（B-1/B-3，接受）
- NOT in scope: written（继承 CEO 9 项 + Eng 无新增）
- What already exists: written（复用前提 5 项声部实证）
- TODOS.md updates: 0 新增（前序阶段 2 项已在 TODOS）
- Failure modes: 0 critical gaps
- Unresolved decisions: 2（G7/G8 taste——Phase 4）
- Outside voice: codex unavailable（provider 400 级故障，CEO 阶段实跑证实）
- Parallelization: Sequential implementation, no parallelization opportunity（单消费者模块核心，config/前端/测试可随主线顺序跟进）
- Lake Score: N/A（autoplan 自动裁决）
- 依赖 hardening：requirements_common.txt:276 websockets 裸名 → P1 钉版（声部实证）

### Decision Audit Trail（Eng 阶段补充行）
| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|-------|----------|----------------|-----------|-----------|----------|
| 9 | eng | 原生声部 20 发现全部接受（3 高：A-1/A-2/B-1 设计修订；A-3/A-4/A-5/B-2/B-3/S-1/S-4/C-1 中项；其余低） | Mechanical | P1+P5 | 设计自洽性修复，全部落 eng 义务块 | 无 |
| 10 | eng | Scope Challenge 结构裁决 = Original arrangement | Mechanical | autoplan never-reduce + P5 | 义务块已定模块落点，无更小安排保留 16 类契约义务 | Smaller arrangement |

### Unresolved decisions（Eng）
G7（旧链路退役开关）、G8（代码归属）——Phase 4 终门 taste 项，eng 义务按其裁决起草（复制范式假设）。

## GSTACK APPROVAL

**APPROVED (2026-09-27)** — /autoplan 终门用户选项 A（按现状批准）。G7 旧链路退役开关（legacy_adapter_retired，默认关）与 G8 复制唯一副本范式均按起草状态生效；38 条实施义务（ceo 21 + dx 7 + eng 10）全部生效。设计跳过（无 UI 范围）；Codex 外部声部全程不可用（provider 400）。下一站：P1 实施或 /ship。

## 实施进度（P1 消费链路，2026-09-27）

- [x] G8 组件复制：Scripts/copy_danmaku.py（MANIFEST 版本戳 676535a9）+ docs/danmaku_contract/
- [x] G6 config 节：frontend/config/settings.py _DANMAKU_LISTENER_DEFAULTS + ensure-default（含 platforms 子字典逐键补齐）
- [x] ManagedProcess 扩展：health_probe 回调（TCP 探活，向后兼容）
- [x] G2 托管 + G1 消费者：utils/danmaku_consumer.py（649 行：serve 拉起/TOML/token 世代/双通道/退避/聚合/优先级/下播裁剪/文本净化）
- [x] main.py 生命周期挂钩（build_danmaku_listener_service，enabled=false 不构建）
- [x] 测试：单测 10 项全过 + 端到端冒烟 PASS（TTHW 6.5s：serve→WS→消费者→映射链）
- [x] S-4 依赖钉版：websockets>=13,<18
- [x] 上游 bug 修复回传：DanmakuListener __main__.py cmd_serve replay 参数遮蔽（import 别名修复，已同步副本）
- [x] G5 扫码 UI + G4 system 消息 UI（2026-09-27 第二批完成：frontend/ui/components/danmaku_login.py——登录常驻入口+QR 安全渲染对话框+事件通知器；consumer 事件环+登录队列数据面；layout.py 侧边栏挂载；单测扩至 17/17；config 节 ensure-default 落盘验证通过）
- [ ] 真实平台连通（组件 serve 引擎接入后；义务块阶段 2 单平台验收）
- [ ] 真实平台连通（组件 serve 引擎接入后；义务块阶段 2 单平台验收）
