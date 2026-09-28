<!-- /autoplan restore point: "C:\\Users\\admin\\.gstack\\projects\\DanmakuListener\\master-autoplan-restore-20260927-010342.md" -->
# Implementation Plan: 六平台弹幕监听系统重构（DanmakuListener → AUTOlive 监听底座）

Generated: 2026-09-27 | Branch: master | Status: DRAFT（待 /autoplan 评审流水线审定）
设计依据: docs/designs/six-platform-danmaku-rebuild.md（APPROVED，office-hours 三轮评审）

## Implementation plan

### 目标

在现有 `danmaku_listener` Python 包基础上重构监听引擎层，实现 B站、斗鱼、虎牙、抖音、快手、微信视频号六平台无感监听（7x24 稳定 + 低资源占用），浏览器注入降级为兜底。系统作为 AUTOlive 的弹幕获取底座，AUTOlive 是唯一前端。

### 架构概览

```
AUTOlive（唯一前端，Python）
   ▲ 统一消息（九类：8 业务 + SYSTEM_STATUS）
   │ 本机 WebSocket 推送（默认）/ HTTP 回调（可选）
┌──┴───────────────────────────────────────────────┐
│ danmaku_listener                                  │
│  ┌─────────────┐  统一消息总线（现有 bus/ 扩展）   │
│  │ 引擎层       │  标准化 / 去重 / 事件分发 /       │
│  │ ┌─────────┐ │  背压（有界环形缓冲+丢弃计数）     │
│  │ │协议直连  │ │ B站/斗鱼/虎牙/快手：每房间一条     │
│  │ │         │ │ asyncio 长连接，单进程 ≤100MB     │
│  │ ├─────────┤ │                                   │
│  │ │代理/伴侣 │ │ 抖音：扩展 proxy_engine，进程级    │
│  │ │直听     │ │ 共享多房间，证书+端口为部署前提    │
│  │ ├─────────┤ │                                   │
│  │ │受控后台  │ │ 视频号：官方管理后台单页面+网络层  │
│  │ │         │ │ 拦截，每房间独立 BrowserContext    │
│  │ ├─────────┤ │                                   │
│  │ │注入兜底  │ │ browser_engine 保留，人工开关，    │
│  │ │         │ │ 有界会话（4h 生命周期事件驱动重建）│
│  │ └─────────┘ │                                   │
│  └─────────────┘                                   │
└───────────────────────────────────────────────────┘
```

核心原则：按平台选引擎（每条路线有参考项目对照）；SYSTEM_STATUS 状态消息是必选行为（心跳/GAP/登录态/活跃引擎/背压计数/路线失效）；不承诺回补但 GAP 必达。

### 阶段分解

每阶段完成即接入 AUTOlive 内部验证（产品交付为六平台全量，工程上逐平台验证）。

**阶段 0：契约与骨架（先行，对应 The Assignment）**
1. 消息契约 v1：九类消息 × 六平台 JSON Schema（含平台特有字段必选/可选标注）。九类 = DANMU、GIFT、SUPER_CHAT、ENTER_ROOM、LIKE、LIVE_STATUS_CHANGE、ROOM_STATS、SOCIAL（八类业务，对照 barrage-fly）+ SYSTEM_STATUS（系统状态，本系统扩展）
2. 传输与投递语义：WebSocket 推送格式、单房间顺序保证、at-least-once + 去重窗口、背压策略、总线重连
3. 崩溃恢复 GAP 补发语义：引擎持久化每房间 last-received 序号/时间戳，进程崩溃或重启恢复后补发一条带起止时间窗的 GAP——停机窗口对上层必达可见（与断线 GAP 同语义）。GAP 窗口裁剪规则：按 LIVE_STATUS_CHANGE 裁剪——下播期间的消息缺失不计 GAP；停机窗口横跨下播时段时拆分为下播前、再开播后两段各自补发
4. 两套心跳入 Schema：平台连接静默检测（引擎↔平台，默认超时 30s）与引擎存活心跳（引擎→AUTOlive，默认 10s/条、连续 3 周期未收到判定失联）；失联判定后 AUTOlive 侧告警并呈现，引擎进程的监护与自动重启（退避重试至多 3 次，超出后持久化为 SYSTEM_STATUS 故障告警）由常驻服务负责
5. NEEDS_LOGIN 定义为跨路线通用行为：任何路线的登录态缺失/过期统一走该消息（视频号扫码、协议直连所需的 cookie/token 同样适用）
6. 契约拿给真实电商客户过一遍（需求验证）：含平台优先级确认与产品形态确认项（headless 部署 + 状态消息呈现是否满足客户运维预期）
9. 合规与账号安全评审（CEO 评审 F3，商业交付前置项）：六平台 ToS 风险评估、客户书面知情同意、专用监听账号策略（严禁绑定客户主账号）、封号影响隔离（每平台独立小号/游客态优先）
10. 自研 vs Java sidecar 书面 ADR（CEO 评审 F2/F11）：内存预算、运维复杂度、许可证三维对比，结论决定四协议平台实现路线；护城河定位声明——监听管道非护城河，产品护城河在 AUTOlive 层
11. 许可证审计（CEO 评审 F10）：ordinaryroad-live-chat-client / blivedm / DouyinBarrageGrab 许可证核查；只借鉴协议行为特征不复制代码，GPL 类传染风险一票否决
7. 引擎接口抽象重构：`BaseEngine` 扩展（多房间生命周期钩子、SYSTEM_STATUS 上报接口、每房间独立 asyncio 任务语义）
8. 调试三项落地：协议版本元数据入消息元数据、GAP 原因分类（网络/协议/风控）、契约 Schema 单源生成 pydantic 模型

**阶段 0 DX 交付束（DX 评审采纳项，随契约一次成型）**：
A. 最小可运行入口：`danmaku-listen`（演示 CLI：单平台单房间，标准化 JSON 打印 stdout，含 TTHW 计时输出）与 `danmaku-serve`（常驻服务入口）；每引擎接入时 demo 必须保持可用（防 DX 回归项），使单平台验收解耦 AUTOlive 可用性
B. 配置面：单一配置格式（TOML）+ 四层优先级（内置默认 → 配置文件 → 环境变量 → 每房间覆盖）；全部有界参数（环形缓冲容量、丢弃方向、去重窗口时长、4h 会话寿命、堆监控阈值、WS 端口、凭据路径）给默认值+配置键，运维手册含资源受限部署建议值
C. 预共享 token：环境变量或受限权限文件注入，生成步骤写入部署清单
D. 部署前置检查覆盖六平台（协议平台查网络/端口/凭据；代理/浏览器平台查证书/杀软），抖音检测脚本升级为统一框架
E. 失败类消息 Schema 强制：reason_code（机器可读）+ fix_hint（人类可读修复指引）+ docs_anchor（指向风控/运维手册锚点），非空校验；信封含 contract_version 与 category: business|system；契约 v1 内 additive-only，消费者忽略未知字段/类型并计数上报
F. 命名映射表：契约类型 ↔ 各平台上游消息类型（DANMU 为有意裁剪，注明对照 DANMU_MSG）
G. 消息示例：九类 × 六平台各 ≥1 条（由录制 fixtures 自动生成，回归测试校验不漂移）+ docs/integration/ AUTOlive 接入指南（WS 地址/token 鉴权/去重窗口/背压消费/心跳失联判定）
H. docs/ 信息架构：docs/contract/（Schema+示例+映射表+迁移指南）、docs/platforms/<平台>/（风控手册）、docs/ops/（运维手册+兼容清单+部署检测）、docs/integration/
I. restart(room_id) 语义明确：仅重启该房间 asyncio 任务，引擎级重启另用显式方法；序号连续性与 GAP 影响写入 BaseEngine 扩展文档
J. 逃生舱三级覆盖：兜底开关与引擎强制指定支持 全局 → 平台 → 房间 粒度
K. 迁移指南：DanmakuMessage 3 类→9 类与配置迁移，含弃用警告与升级路径（docs/contract/）

**阶段 0 工程出口前置（Eng 评审采纳项，7 项）**：
L. 进程拓扑显式化：协议四平台单进程单事件循环 + 每平台每房间独立 asyncio 任务；新增事件循环滞后 watchdog（loop lag 采样入 SYSTEM_STATUS）；抖音代理引擎默认独立进程+本机 IPC 接总线（预算单独核定），若坚持与总线同进程则阶段 2 开工前先做 mitmproxy 嵌入 asyncio 的 spike，失败即回退独立进程（ADR 裁定）
M. 背压分级：GIFT/SUPER_CHAT/SOCIAL 队列独立或高水位优先，丢弃顺序默认先丢 LIKE/ENTER_ROOM/DANMU；任一窗口丢弃数>0 时对该房间发带时间窗 GAP（与断线 GAP 同语义）
N. live 状态持久化：每房间最近 live 状态与转换时间戳持久化，重启后经平台直播状态 API 校准；GAP 边界时间声明为尽力近似（误差口径入契约）
O. 重试策略：3 次快速退避耗尽后进入慢速无限重试（指数退避封顶 15 分钟），告警保持激活；「慢速重试已恢复」为独立 SYSTEM_STATUS 事件
P. 投递/去重语义闭合：重连不重放（依赖 GAP 报知缺失段）；跨路线语义去重键（平台原生消息 ID 必填入信封，无原生 ID 的平台在接入指南明示切换期允许重复）；AUTOlive 重启后去重窗口冷启动行为入接入指南；去重窗口为有界结构（时间淘汰+容量上限，溢出方向入配置面）
Q. NEEDS_LOGIN 交互闭环：Schema 增加 interactive_login 载荷（QR 图像 base64 或一次性登录 URL + 扫码完成回调语义）为契约必选字段，接入指南给出重扫流程示例
R. 合规清单补两条：根 CA 安装范围/域名限定/卸载步骤；hook 注入路线单独知情确认；运行期直播伴侣版本漂移检测（不符→ROUTE_FAILED，fix_hint 指向版本锁定指南）
S. 其他：预算表 spike 验证项（阶段 0 空骨架实测基线 RSS）；CI Schema diff 检查（禁删字段/禁改类型/新字段 optional）；WS 默认绑定 127.0.0.1+常量时间 token 比较+Windows ACL；凭据文件唯一写者约定（引擎写、AUTOlive 只读）；延迟测量注明平台时钟偏移与保守对照口径

**阶段 1：B站协议直连引擎**
1. 协议客户端实现（对照 ordinaryroad-live-chat-client 的 bilibili 模块；Python 生态参考 blivedm）
2. 八类业务消息解析映射（B站平台特有字段标注进契约）
3. 断线重连 + 平台静默检测（30s 超时）+ 下播/再开播生命周期（离线退避重连、再开播自动恢复、下播不产生 GAP）
4. 登录态验证：确认 B站弹幕连接是否需要 cookie/游客 token；需要则接入 NEEDS_LOGIN 流程
5. 单平台验收：延迟 <1s、进程 RSS ≤100MB、24h 漂移 ≤10%、AUTOlive 内部验证
6. 阶段出口附带：B站协议流量录制 fixtures 回归测试 + B站风控应对手册（docs/）

**阶段 2：抖音代理/伴侣直听引擎**
0. R3-2 默认裁定方向（否决制确认，项目所有者与工程负责人会签，阶段 2 开工前完成）：抖音代理引擎并入引擎进程计量口径（与消息总线同进程，基准 ≤100MB）；若 mitmproxy 必须独立进程，则该进程树预算单独核定并计入系统级预算统计边界
1. `proxy_engine` 扩展：进程过滤 + 域名白名单 + protobuf 解析（`直播监听脚本/dy.proto`）
2. 直播伴侣 hook 子路线（免代理模式，对照 DouyinBarrageGrab 的 liveCompanHook 逻辑）；子路线选择准则落地为部署检测脚本（证书/端口/杀软清单）
3. 与阶段 1 相同的重连/生命周期/验收（代理引擎预算并入引擎进程口径，见 Reviewer Concerns R3-2 待裁定）
4. 阶段出口附带：抖音协议流量录制 fixtures 回归测试 + 抖音风控应对手册（docs/）

**阶段 3a：斗鱼协议直连引擎**（与 3b 独立门禁，任一卡壳不阻塞另一平台）
1. 斗鱼协议客户端（对照 ordinaryroad-live-chat-client 的 douyu 模块）；复用阶段 1 骨架（重连/生命周期/SYSTEM_STATUS 全部继承）
2. 登录态验证（斗鱼是否需要 cookie/token，需要则接入 NEEDS_LOGIN）
3. 单平台验收 + 阶段出口附带：斗鱼 fixtures 回归测试 + 斗鱼风控手册（docs/，含协议失效信号与重录适配 runbook）

**阶段 3b：虎牙协议直连引擎**
1. 虎牙协议客户端（对照同库 huya 模块）；复用阶段 1 骨架
2. 登录态验证（虎牙是否需要 cookie/token）
3. 单平台验收 + 阶段出口附带：虎牙 fixtures 回归测试 + 虎牙风控手册（docs/，含协议失效信号与重录适配 runbook）

**阶段 4：快手协议直连引擎**
1. 协议客户端（对照同库 kuaishou 模块；本地 `ks.proto`/`kuaishou_pb2.py` 交叉验证）
2. 登录态验证：确认快手弹幕连接是否需要 cookie/游客 token（**重点验证项**：快手公开抓包普遍需要游客 token，若证实则接入 NEEDS_LOGIN 并记录获取方式）
3. 单平台验收
4. 阶段出口附带：快手协议流量录制 fixtures 回归测试 + 快手风控应对手册（docs/）

**阶段 5：视频号受控后台引擎**
1. 受控浏览器管理后台登录 + storageState 持久化（复用 cookie/ 目录）
2. 每直播间独立 BrowserContext 页面 + 网络层拦截
3. **部署前验证项**：同账号多 BrowserContext 并行的风控实测（互踢/登录风控）；触发则降级为每房间独立微信账号方案
4. NEEDS_LOGIN 流程：登录态过期 → SYSTEM_STATUS → AUTOlive 界面提示重扫
5. 单平台验收：进程树 ≤600MB（满配多房间）
6. 阶段出口附带：视频号网络层流量录制 fixtures 回归测试 + 视频号风控应对手册（docs/，含后台页面结构变更的失效信号）

**阶段 6：兜底引擎改造 + 全局收口**
1. browser_engine 有界会话：4h 生命周期、事件驱动重建（前后发 SYSTEM_STATUS）、堆监控超阈值提前重建；移除全局定时重启机制
2. 兜底触发语义落地：配置文件人工开关，三场景 = ① 长尾平台（不在六平台范围的临时需求）② 主路线失效期间（协议/代理路线故障待修复）③ 调试对照（新引擎与注入引擎并行比对）；默认全部关闭
3. 背压机制落地：有界环形缓冲 + 丢弃计数上报
4. 全平台统一消息格式终验（九类 × 六平台）

**阶段 7：AUTOlive 集成验证 + 量化验收**
1. 容量压测：10 直播间跨 ≥3 平台，延迟/内存不劣化，系统级总预算 ≤1.2GB；另加六平台满配场景（4 条协议连接 + 抖音代理 + 视频号页面同时在线，兜底关闭）与兜底开启场景（替代预算 1.6GB）
2. 观察窗口：24h 标准压测 + 7 天试点直播间实测（psutil 分钟级 RSS 采样）
3. 极端场景压测：单房间消息风暴（礼物雨）与 100 房间低流量两档
4. 时钟跳变（NTP 校时步进）下的 GAP 与延迟统计回归
3. 电商客户试点部署（含部署兼容性清单：杀软/防火墙/伴侣版本/端口）
4. 运维归属模型（CEO 评审 F4/F7）：定义每平台失效响应责任人与响应时限；7x24 是运营承诺而非项目终点——失效容忍预算（单平台月维护工时上限，超限自动降级兜底注入而非死磕）写入运维手册，兜底引擎战略定位为对冲资产

### 验收标准（引用设计文档，评审基准）

- 延迟：六平台弹幕延迟 <1 秒（测量口径见 Reviewer Concerns R3-4，待契约 v1 定义）
- 内存：协议直连 ≤100MB（进程）；受控后台 ≤600MB、兜底 ≤400MB（进程树）；每进程树 24h 漂移 ≤10%（阶段门禁）且 7 天试点窗口累计漂移 ≤10%（终验，7x24 承诺的验收代理）；系统级 ≤1.2GB（统计边界见降级态条目下方）
- 连续性：断线自动重连；GAP 必达；两套心跳参数入契约 Schema
- 通道安全：本机 WS 推送通道增加预共享 token 鉴权（本机进程间通信的最低防线，Section 3）
- 重启机制：全局定时重启移除，替换为事件驱动有界重建
- 契约：九类消息 × 六平台统一格式，AUTOlive 无平台区分处理
- 降级态验收：兜底路线生效期间，延迟放宽至 <3s（DOM 抓取固有延迟），内存预算与漂移标准不变（有界会话保障），SYSTEM_STATUS 可见性（活跃引擎标识、降级告警）必达——降级态豁免主路线延迟指标，观测性不豁免
- 系统级预算统计边界 = danmaku_listener 全部自有进程树 RSS 之和（协议直连引擎进程 + 抖音代理引擎进程树 + 视频号浏览器进程树 + 常驻服务/消息总线），不含 AUTOlive 主进程；1.2GB 适用于兜底关闭的六平台满配，兜底开启场景采用替代预算 1.6GB
- 进程拓扑：协议四平台单进程（每房间独立任务 + loop lag watchdog）；抖音代理默认独立进程经本机 IPC 接总线（ADR 裁定）；背压按消息类别分级丢弃，任一窗口丢弃>0 即发窗口 GAP

### 依赖与前置

- ordinaryroad-live-chat-client 源码单独获取（版本锚定 barrage-fly 依赖声明）——阶段 1 前完成
- 消息契约 v1 经真实客户校验——阶段 0 出口条件
- DouyinBarrageGrab 已知问题清单（用户持有）——阶段 2 前
- 电商客户环境样本——阶段 7 试点部署前
- 真实客户校验边界规则：约定 5 个工作日响应时限，逾期未响应由产品侧代理确认并显式记录风险后放行（放行不等于客户已确认契约）
- 视频号降级方案所需的独立微信账号来源（客户侧提供）——阶段 5 风控实测触发降级时的执行前提
- 登录态凭据文件（cookie/、storageState）以用户级加密或受限文件权限存储，不入版本库（Section 3）

### 不在范围（NOT in scope）

- 弹幕/礼物发送能力（只监听）
- 自有 UI（AUTOlive 是唯一前端；本系统只有部署级人工步骤 + 经 SYSTEM_STATUS 的运行期提示）
- 消息持久化存储、AI 分析、分布式部署、移动端
- 长尾平台协议适配（走兜底注入引擎覆盖）
- DouyinBarrageGrab 参考项目自身的已知问题修复（只学逻辑不修上游）
- 指标导出端点（Prometheus）——已裁定 DEFERRED 至 TODOS.md，待 AUTOlive 监控栈定型后重启（CEO 摘要 Scope Decision #4）


<!-- autoplan-accepted:ceo -->
- 阶段 0 契约 v1 必须包含九类消息 Schema（8 业务 + SYSTEM_STATUS）与传输投递语义（单房间顺序 / at-least-once + 去重窗口 / 背压 / 总线重连），并经真实电商客户校验后方可进入阶段 1
- BaseEngine 扩展保持现有 start/stop/restart(room_id) 公开契约不变，新增多房间生命周期钩子与 SYSTEM_STATUS 上报接口
- 每平台引擎交付标准：延迟 <1s、内存预算按设计文档进程/进程树口径、24h 漂移 ≤10%、AUTOlive 内部验证通过
- （接受扩展）协议录制回放测试基建：每平台协议引擎交付时必须附带真实流量 fixtures 回归测试
- （接受扩展）平台风控应对手册：docs/ 下每平台失效信号、降级流程与上报路径，随平台逐份产出
- （接受扩展）调试三项：协议版本元数据入消息元数据、GAP 原因分类（网络/协议/风控）、契约 Schema 单源生成 pydantic 模型
- Reviewer Concerns R3-2（抖音代理引擎与消息总线的内存预算计量归属）在阶段 2 实现前必须裁定并更新验收表
- Reviewer Concerns R3-4（延迟测量口径）在契约 v1 中定义（起点=平台消息时间戳，终点=AUTOlive 收到，P95 统计，无平台时间戳时的替代测法）
- 现有 DanmakuMessage 模型（normal/gift/system 三类）扩展到九类时的向后兼容策略（现有消费者与 tests/ 不破坏）在阶段 0 契约中明确
- web/static 旧前端页面的处置（保留为本地调试工具并标注，或随阶段 6 移除）在阶段 0 裁定，不得与「AUTOlive 是唯一前端」前提冲突
- （Sections 落实）合规与账号安全评审为阶段 0 前置项（F3）：ToS 评估、书面知情同意、专用监听账号、封号影响隔离——未完成不得进入试点部署
- （Sections 落实）自研 vs sidecar ADR 与许可证审计为阶段 1 前置（F2/F10/F11）；监听管道定位为非护城河，护城河在 AUTOlive 层
- （Sections 落实）运维归属模型与失效容忍预算（单平台月维护工时上限，超限降级兜底）在阶段 7 试点前写入运维手册（F4/F7）
- （Sections 落实）本机 WS 通道预共享 token 鉴权、登录态凭据加密存储为安全底线（S3-2/S3-3）
- （Sections 落实）坏消息处置语义（丢弃+计数+连续失败→ROUTE_FAILED 的阈值）与视频号单实例房间数上限在契约 v1/满配矩阵中定义（S1-1/S1-2）
- （Sections 落实）常驻服务崩溃恢复集成测试（kill -9 场景）为阶段 0/6 任务（S6-1）
<!-- /autoplan-accepted:ceo -->

<!-- autoplan-accepted:dx -->
- 最小可运行入口（danmaku-listen 演示 CLI + danmaku-serve 常驻入口）为阶段 0 交付物，每引擎接入时 demo 保持可用（DX 回归项），单平台验收解耦 AUTOlive 可用性
- 配置面：TOML 单格式 + 四层优先级；全部有界参数给默认值+配置键，运维手册含资源受限建议值
- 失败类消息 Schema 强制 reason_code + fix_hint + docs_anchor 非空；信封含 contract_version 与 category: business|system；契约 v1 additive-only
- 消息示例（fixtures 自动生成）与 docs/integration/ 接入指南为阶段 0 出口条件
- docs/ 四目录信息架构（contract/platforms/ops/integration）于阶段 0 定骨架
- 部署前置检查覆盖六平台，统一检测框架于阶段 0 建立
- restart(room_id) 语义（仅该房间任务）与三级覆盖逃生舱（全局→平台→房间）写入 BaseEngine 扩展文档
- 命名映射表（含 DANMU 有意裁剪注明）与迁移指南（3 类→9 类+弃用警告）入 docs/contract/
<!-- /autoplan-accepted:dx -->

<!-- autoplan-accepted:eng -->
- 七项工程出口前置（L-R：进程拓扑/背压分级/live 状态持久化/重试策略/投递去重闭合/NEEDS_LOGIN 闭环/合规补条+预算 spike+CI diff+WS 安全+凭据写者+时钟口径）随阶段 0 契约一次成型，未完成不得进入阶段 1
- 阶段 3 拆分为 3a（斗鱼）与 3b（虎牙）独立门禁；两平台手册含协议失效信号与重录适配 runbook
- 阶段 7 压测矩阵含单房间消息风暴、100 房间低流量、时钟跳变回归三档
- 测试计划工件（admin-master-eng-review-test-plan-20260927.md）为 /qa 与 /qa-only 的主输入
<!-- /autoplan-accepted:eng -->
## Review record

<!-- autoplan-baseline-edits:ceo {"sourceSha256":"607e19979980d3a46ce6bdd0b173367cb4d63c544a71a638d9933588b42f6d22","replacements":[]} -->
<!-- autoplan-baseline-edits:dx {"sourceSha256":"607e19979980d3a46ce6bdd0b173367cb4d63c544a71a638d9933588b42f6d22","replacements":[]} -->
<!-- autoplan-baseline-edits:eng {"sourceSha256":"607e19979980d3a46ce6bdd0b173367cb4d63c544a71a638d9933588b42f6d22","replacements":[]} -->

<!-- autoplan-accepted:ceo -->
- 阶段 0 契约 v1 必须包含九类消息 Schema（8 业务 + SYSTEM_STATUS）与传输投递语义（单房间顺序 / at-least-once + 去重窗口 / 背压 / 总线重连），并经真实电商客户校验后方可进入阶段 1
- BaseEngine 扩展保持现有 start/stop/restart(room_id) 公开契约不变，新增多房间生命周期钩子与 SYSTEM_STATUS 上报接口
- 每平台引擎交付标准：延迟 <1s、内存预算按设计文档进程/进程树口径、24h 漂移 ≤10%、AUTOlive 内部验证通过
- （接受扩展）协议录制回放测试基建：每平台协议引擎交付时必须附带真实流量 fixtures 回归测试
- （接受扩展）平台风控应对手册：docs/ 下每平台失效信号、降级流程与上报路径，随平台逐份产出
- （接受扩展）调试三项：协议版本元数据入消息元数据、GAP 原因分类（网络/协议/风控）、契约 Schema 单源生成 pydantic 模型
- Reviewer Concerns R3-2（抖音代理引擎与消息总线的内存预算计量归属）在阶段 2 实现前必须裁定并更新验收表
- Reviewer Concerns R3-4（延迟测量口径）在契约 v1 中定义（起点=平台消息时间戳，终点=AUTOlive 收到，P95 统计，无平台时间戳时的替代测法）
- 现有 DanmakuMessage 模型（normal/gift/system 三类）扩展到九类时的向后兼容策略（现有消费者与 tests/ 不破坏）在阶段 0 契约中明确
- web/static 旧前端页面的处置（保留为本地调试工具并标注，或随阶段 6 移除）在阶段 0 裁定，不得与「AUTOlive 是唯一前端」前提冲突
- （Sections 落实）合规与账号安全评审为阶段 0 前置项（F3）：ToS 评估、书面知情同意、专用监听账号、封号影响隔离——未完成不得进入试点部署
- （Sections 落实）自研 vs sidecar ADR 与许可证审计为阶段 1 前置（F2/F10/F11）；监听管道定位为非护城河，护城河在 AUTOlive 层
- （Sections 落实）运维归属模型与失效容忍预算（单平台月维护工时上限，超限降级兜底）在阶段 7 试点前写入运维手册（F4/F7）
- （Sections 落实）本机 WS 通道预共享 token 鉴权、登录态凭据加密存储为安全底线（S3-2/S3-3）
- （Sections 落实）坏消息处置语义（丢弃+计数+连续失败→ROUTE_FAILED 的阈值）与视频号单实例房间数上限在契约 v1/满配矩阵中定义（S1-1/S1-2）
- （Sections 落实）常驻服务崩溃恢复集成测试（kill -9 场景）为阶段 0/6 任务（S6-1）
<!-- /autoplan-accepted:ceo -->

<!-- autoplan-accepted:dx -->
- 最小可运行入口（danmaku-listen 演示 CLI + danmaku-serve 常驻入口）为阶段 0 交付物，每引擎接入时 demo 保持可用（DX 回归项），单平台验收解耦 AUTOlive 可用性
- 配置面：TOML 单格式 + 四层优先级；全部有界参数给默认值+配置键，运维手册含资源受限建议值
- 失败类消息 Schema 强制 reason_code + fix_hint + docs_anchor 非空；信封含 contract_version 与 category: business|system；契约 v1 additive-only
- 消息示例（fixtures 自动生成）与 docs/integration/ 接入指南为阶段 0 出口条件
- docs/ 四目录信息架构（contract/platforms/ops/integration）于阶段 0 定骨架
- 部署前置检查覆盖六平台，统一检测框架于阶段 0 建立
- restart(room_id) 语义（仅该房间任务）与三级覆盖逃生舱（全局→平台→房间）写入 BaseEngine 扩展文档
- 命名映射表（含 DANMU 有意裁剪注明）与迁移指南（3 类→9 类+弃用警告）入 docs/contract/
<!-- /autoplan-accepted:dx -->

<!-- autoplan-accepted:eng -->
- 七项工程出口前置（L-R：进程拓扑/背压分级/live 状态持久化/重试策略/投递去重闭合/NEEDS_LOGIN 闭环/合规补条+预算 spike+CI diff+WS 安全+凭据写者+时钟口径）随阶段 0 契约一次成型，未完成不得进入阶段 1
- 阶段 3 拆分为 3a（斗鱼）与 3b（虎牙）独立门禁；两平台手册含协议失效信号与重录适配 runbook
- 阶段 7 压测矩阵含单房间消息风暴、100 房间低流量、时钟跳变回归三档
- 测试计划工件（admin-master-eng-review-test-plan-20260927.md）为 /qa 与 /qa-only 的主输入
<!-- /autoplan-accepted:eng -->

## CEO 评审记录（Sections 1-10，2026-09-27，[single-model]）

### Section 1: Architecture Review
系统边界清晰：四引擎路线 + 统一总线 + AUTOlive 仅依赖消息契约（低耦合）。数据流四路径：happy 与 error（断连→重连→GAP）已覆盖；**nil/empty 路径（单条消息解析失败、空载荷）计划未定义处置** → 发现 S1-1：坏消息处置语义（丢弃+计数，连续 N 条失败→ROUTE_FAILED）并入契约 v1（与 Section 2 GAP 同源）。状态机：引擎/房间生命周期完整（下播/再开播/有界重建/监护自愈）。扩展性：10 房间达标；100 房间时视频号每房间一 BrowserContext 不可行（估算 ~6GB）→ 发现 S1-2：视频号单实例房间数上限（建议 ≤10，超出提示分机部署）由 CL1 满配矩阵一并定义。单点故障：常驻服务监护 ✓。回滚：单平台故障切兜底 + 失效容忍预算止损 ✓。

### Section 2: Error & Rescue Map（capability rows）
| 路径 | 主要错误 | 救援 | 用户所见 |
|---|---|---|---|
| 协议直连连接 | 断连/静默超时 | 重连退避 | GAP 标记 |
| 消息解析 | 平台格式变更 | 丢弃计数→ROUTE_FAILED | 路线失效告警 |
| 代理引擎 | 证书/端口/杀软 | 部署检测脚本前置 | 部署失败提示 |
| 视频号后台 | 页面/接口结构变更 | 失效告警+人工适配 | ROUTE_FAILED/NEEDS_LOGIN |
| last-received 持久化 | 磁盘满/文件损坏 | 粗粒度 GAP 降级 | GAP(时间不可信标记) |
| 引擎进程 | 崩溃 | 常驻服务重启(退避 3 次) | SYSTEM_STATUS 故障告警 |
GAP：解析失败→路线失效的连续失败阈值未定（S1-1，契约 v1 定义）。现有代码无 catch-all 异常吞没（审计确认）。

### Section 3: Security & Threat Model
已落实三项修复：**S3-1 合规/账号安全评审**（F3 CRITICAL——ToS 评估、书面知情同意、专用账号、封号隔离入阶段 0）；S3-2 凭据文件加密/受限权限；S3-3 本机 WS 预共享 token。威胁评级：平台风控封号（High/High/缓解=专用账号+游客态优先+止损预算）；hook 模式被检测（Med/Med/缓解=代理默认+hook 备选）；平台消息注入 AUTOlive（Low/Med/缓解=AUTOlive 侧消费校验，边界声明入契约）。

### Section 4: Data Flow & Interaction Edge Cases
数据流 shadow paths 由 GAP/背压/重连/去重覆盖。异步顺序：单房间有序（契约）；跨房间无序（契约声明）；去重窗口吸收 at-least-once 重复 ✓。动态房间管理复用现有 web/app.py REST（/api/rooms）✓。边缘：运行时删房在途消息 flush 后关闭——契约细节，阶段 0 定义。

### Section 5: Code Quality
现有 5426 行分层清晰（engines/adapters/bus/managers/config），specs 有完整工具链（ruff/mypy/black）。新代码：四协议引擎继承 BaseEngine 骨架（DRY）、契约单源生成防 Schema/pydantic 双维护。无新发现——现有代码审计健康，新代码受骨架与契约约束。

### Section 6: Test Review
新测试图：协议解析 unit（fixtures 回归，已接受扩展）、断线重连（现有 test_ws_reconnect.py 先例）、GAP/心跳行为 unit+integration、背压丢弃 unit、**常驻服务崩溃恢复 integration（kill -9 场景）→ S6-1 记入阶段 0/6 任务**、满配压测 load。金字塔合理；真实连接的 flaky 风险由录制回放替代。2am 信心测试=七平台满配 7 天漂移曲线。

### Section 7: Performance
预算体系完整（进程/进程树/系统级/漂移双窗口/统计边界/替代预算）。解析热路径 protobuf/orjson 选型合理。无 DB、无 N+1。满配矩阵（CL1）定义后可直接压测。无新发现。

### Section 8: Observability & Debuggability
loguru 结构化日志 + SYSTEM_STATUS 最小观测集 ✓；Prometheus DEFERRED（TODOS ✓）。本机部署模式无远程盲飞（AUTOlive 同机消费状态消息）；运维归属模型（F4）已入阶段 7。Runbook=平台风控手册（接受扩展）✓。

### Section 9: Deployment & Rollout
部署检测脚本+兼容性清单+试点顺序+回滚（切兜底+止损）均已覆盖。客户环境差异（杀软/防火墙/伴侣版本）已前置为清单。无新发现。

### Section 10: Long-Term Trajectory
技术债主项=四协议持续维护（F2 ADR 裁定实现路线；失效容忍预算止损兜底）。可逆性 4/5（每引擎独立，可替换 sidecar）。知识集中风险由风控手册+契约文档缓解。1 年问题：新工程师凭架构图+契约 v1 可上手。

（Section 11 SKIPPED——无 UI scope）

## CEO Completion Summary

```
+====================================================================+
|            MEGA PLAN REVIEW — COMPLETION SUMMARY                   |
+====================================================================+
| Mode selected        | SELECTIVE_EXPANSION                         |
| System Audit         | 单 commit 基线; 核心代码 5426 行; 测试目录    |
|                      | 完整; 无遗留 TODO; 无 stash                  |
| Step 0               | SELECTIVE EXPANSION; 3 接受/1 推迟/1 拒绝;   |
|                      | 0H 三轮规格评审 24 发现(15 修复确认)          |
| Section 1  (Arch)    | 2 issues (S1-1 坏消息路径, S1-2 视频号上限)   |
| Section 2  (Errors)  | 6 error paths mapped, 1 GAP (失败阈值)       |
| Section 3  (Security)| 3 issues (合规/凭据/token), 1 CRITICAL 已落实 |
| Section 4  (Data/UX) | 边缘已覆盖, 动态房间复用现有 API              |
| Section 5  (Quality) | 0 issues (骨架+契约约束)                     |
| Section 6  (Tests)   | 图已建, S6-1 崩溃恢复测试补入                |
| Section 7  (Perf)    | 0 issues (预算体系完整)                      |
| Section 8  (Observ)  | 0 gaps (最小集覆盖, Prometheus deferred)     |
| Section 9  (Deploy)  | 0 risks (F4 运维模型已入计划)                |
| Section 10 (Future)  | Reversibility: 4/5, debt: 协议维护(ADR 裁定) |
| Section 11 (Design)  | SKIPPED (no UI scope)                        |
+--------------------------------------------------------------------+
| NOT in scope         | written (6 items)                            |
| What already exists  | written                                     |
| Dream state delta    | written                                     |
| Error/rescue registry| 6 rows, 1 GAP (阈值, 契约 v1 闭合)           |
| Failure modes        | 6 total, 0 CRITICAL GAPS                    |
| TODOS.md updates     | 2 items (客户访谈扩样, 指标端点)              |
| Scope proposals      | 5 proposed, 3 accepted                      |
| CEO plan             | written (~/.gstack/ceo-plans/)               |
| Outside voice        | codex unavailable (provider 400 x2)          |
| Lake Score           | N/A (kind-only questions)                    |
| Diagrams produced    | 架构图(计划内), 错误/救援表                   |
| Stale diagrams found | 0                                            |
| Unresolved decisions | 1 User Challenge (F1 需求门禁) 排队最终门     |
+====================================================================+
```


## What already exists（CEO 阶段）

| 子问题 | 现有代码 | 处置 |
|---|---|---|
| 引擎骨架 | `danmaku_listener/engines/base.py`（BaseEngine/EngineStatus/重连集成） | 扩展复用，公开契约不变 |
| 消息总线 | `bus/event_bus.py` + `dedup_filter.py` | 扩展（九类+背压+SYSTEM_STATUS） |
| 数据模型 | `bus/message.py` DanmakuMessage（3 类） | 大改→九类，向后兼容策略入阶段 0 |
| 抖音代理 | `engines/proxy_engine.py` + `managers/certificate_manager.py` | 扩展（伴侣 hook + 部署检测） |
| 浏览器引擎 | `engines/browser_engine.py` + Playwright 管道 | 改造（视频号受控后台 + 兜底有界会话） |
| 对接通道 | `web/app.py`（aiohttp WS /ws + /api/rooms REST） | 复用为 AUTOlive 推送通道 + 动态房间管理 |
| 配置/日志 | `config/settings.py`（pydantic-settings）、loguru | 直接复用 |
| 协议工件 | `直播监听脚本/`（dy.proto、ks.proto、pb2 生成物、逆向 JS） | 交叉验证基础 |
| 测试基建 | `tests/`（unit/integration/manual，test_ws_reconnect 等） | 扩展（fixtures 回归归此） |

## Dream state delta（CEO 阶段）

```
CURRENT STATE                THIS PLAN                     12-MONTH IDEAL
单平台代理+注入泄漏,      -->  六平台四路线引擎+统一契约  -->  电商客户多平台稳定运营,
定时重启硬扛,                  +量化验收+止损运维模型,          协议失效→适配→发布为
客户电脑卡顿投诉               逐平台可验证                     可运营流水线(SLA 化),
                                                               AUTOlive 层承载产品护城河
```
本计划把现状推进到理想态的地基完成位：监听层从「不可靠」变「可运营」，使 AUTOlive 的差异化（AI 互动、分析）建立在可靠数据流上。剩余差距（SLA 化运营、指标体系、多客户规模化）由运维模型与 deferred 项承接。


## DX 评审记录（Phase 2.5，2026-09-27，[single-model]）

### Developer Persona Card
- Who: AUTOlive 维护者（Python 开发者，asyncio 熟练），将监听包作为库集成进 AUTOlive 数字人系统
- Context: 重构完成后第一时间把六平台监听接入 AUTOlive；电商客户现场部署由其指导
- Tolerance: 单平台验证窗口数小时；Hello World 期望 <5 分钟
- Expects: import 即用、统一消息格式稳定、故障经 SYSTEM_STATUS 可观测、离线可测（fixtures）

### Developer Empathy Narrative（摘要）
「我是 AUTOlive 的维护者。pip install 之后我最想看到的是一条真实弹幕——不是读完六份手册之后。如果 demo 命令 30 秒内滚出标准化 JSON，我立刻知道格式对不对、字段全不全。引擎挂了的时候，我不想到源码里找原因——SYSTEM_STATUS 里应该直接告诉我 problem、cause、下一步 fix，最好带文档锚点。升级时我最怕 DanmakuMessage 字段变了导致 AUTOlive 全线崩——迁移指南和弃用警告是底线。」→ 该叙事由 DX 交付束 A/E/K 直接回应。

### DX Scorecard（初评 → DX 交付束采纳后预期）

```
+====================================================================+
|              DX PLAN REVIEW — SCORECARD                             |
+====================================================================+
| Dimension            | Score(initial→post)  | Trend  |
|----------------------|----------------------|--------|
| Getting Started      | 4 → 8                | ↑↑     |
| API/CLI/SDK          | 5 → 8                | ↑↑     |
| Error Messages       | 5 → 8                | ↑↑     |
| Documentation        | 5 → 8                | ↑↑     |
| Upgrade Path         | 5 → 7                | ↑      |
| Dev Environment      | 7 → 8                | ↑      |
| Community            | 3 (内部产品，暂不适用) | —      |
| DX Measurement       | 4 → 7                | ↑      |
+--------------------------------------------------------------------+
| TTHW                 | 未定义(~15-30min) → <2 min (Champion 目标)    |
| Competitive Rank     | Needs Work → Competitive（采纳后）             |
| Magical Moment       | designed via danmaku-listen + fixtures 回放    |
| Product Type         | Library/SDK + 内嵌 Service                     |
| Mode                 | DX POLISH (autoplan override)                  |
| Overall DX           | 5 → 8                                          |
+====================================================================+
| DX PRINCIPLE COVERAGE                                               |
| Zero Friction      | covered (demo CLI, 单命令)                     |
| Learn by Doing     | covered (fixtures 回放+示例)                    |
| Fight Uncertainty  | covered (reason_code/fix_hint/docs_anchor)      |
| Opinionated + Escape Hatches | covered (四层优先级+三级覆盖)          |
| Code in Context    | covered (接入指南+真实示例)                      |
| Magical Moments    | covered (danmaku-listen 30s 首条弹幕)           |
+====================================================================+
```

### Developer Journey Map（9 阶段）

| 阶段 | 开发者动作 | 摩擦点 | 状态 |
|---|---|---|---|
| Discover | README/设计文档 | 现有 README 需更新六平台矩阵 | 阶段 0 文档 |
| Install | pip install | 单命令 ✓ | ok |
| Hello World | danmaku-listen 单命令 | 原缺失 → DX-A 交付 | fixed |
| Real Usage | serve + 动态房间 API | 配置面原未定义 → DX-B/C | fixed |
| Debug | SYSTEM_STATUS + loguru | 失败语义三段式 → DX-E | fixed |
| Upgrade | 迁移指南 | 3→9 类迁移 → DX-K | fixed |
| Scale | 满配压测/分机部署 | 视频号房间上限（CL1） | 契约 v1 定义 |
| Contribute | 内部产品暂缓 | — | deferred |
| Migrate | 旧系统数据迁移 | 消息持久化不在范围 | N/A |

### First-Time Developer Confusion Report（要点）
T+0:00 pip install 成功 → T+0:30 找不到「跑起来」的入口（原缺口，DX-A 修复）→ T+1:00 配置格式不明（DX-B 修复）→ T+2:00 demo 出弹幕，格式一目了然（magical moment）→ T+3:00 接入 AUTOlive 时读 docs/integration/（DX-G 修复）。

### TTHW 评估
- 现状：Hello World 路径未定义（推演 15-30 分钟，多步未定义）
- 目标（已采纳）：<2 分钟（Champion）：pip install → danmaku-listen bilibili <room_id> → 首条标准化 JSON（含 TTHW 计时输出自证）
- 度量：demo 命令计时输出（DX Measurement 7/10）；TTHW 无遥测上报（additive-only 原则，阶段 0 不引入）

### "NOT in scope"（DX 增补）
- 社区/生态建设（开源渠道、插件体系）——内部产品阶段不适用
- TTHW 遥测自动上报——阶段 0 保持零依赖，度量仅本地输出
- 第三方 SDK 语言绑定——单一 Python 消费者

### "What already exists"（DX 增补）
- README 中文快速开始示例（质量好，保留并扩展六平台）
- web/app.py REST API（动态房间管理复用）
- loguru 结构化日志、pytest 工具链、tests/ 先例
- cookie/ 目录约定、.env.example 配置先例


## Eng 评审记录（Phase 3，2026-09-27，[single-model]）

### Scope Challenge
- 子问题→现有代码映射完整（见 CEO What already exists 表）；最小变更集成立（复用骨架+契约先行）
- 复杂度：>>8 文件（多引擎+总线+web+测试），结构检查——四引擎继承 BaseEngine 为保留全部承诺的最小清晰排列；autoplan 覆盖「never reduce」，P5 显式原则通过
- 搜索检查：网络不可用，按本地参考项目知识库评估（协议直连/受控后台/代理 hook 均有参考实现锚定）
- 结论：scope accepted as-is（FULL_REVIEW）

### 共识表（Eng DUAL VOICES — Codex unavailable → N/A）
| Dimension | Claude | Codex | Consensus |
|---|---|---|---|
| 1. Architecture sound? | 有条件（A-1 故障隔离/A-2 拓扑） | — | N/A |
| 2. Test coverage sufficient? | 缺 8 项（T-1） | — | N/A |
| 3. Performance risks addressed? | 是（E-4 补极端压测） | — | N/A |
| 4. Security threats covered? | 是（S-1/S-2/S-3 补强） | — | N/A |
| 5. Error paths handled? | 是（A-3/E-1/E-2/E-3 闭合） | — | N/A |
| 6. Deployment risk manageable? | 是（H-1 登录闭环是关键） | — | N/A |
CONFIRMED = 0（outside 不可用）；native 结论：有条件通过（GO，7 项阶段 0 前置）

### Sections 1-4 发现（全部采纳，已写入正文）
- 架构：A-1（高，代理与总线同进程故障隔离→L 默认独立进程+spike 兜底）、A-2（中，拓扑显式化+loop lag watchdog→L）、A-3（高，背压分级+窗口 GAP→M）
- 边缘：E-1（中高，live 状态持久化+GAP 近似→N）、E-2（中，慢速无限重试→O）、E-3（中，重放/去重/冷启动→P）、E-4（中，有界去重+极端压测→P+阶段 7.3）、E-5（低，时钟口径→R）
- 测试：T-1 八项清单入测试计划工件（~/.gstack/projects/DanmakuListener/admin-master-eng-review-test-plan-20260927.md）；T-2 CI diff→TODOS
- 安全：S-1（根 CA/hook 知情同意+版本漂移→R）、S-2（127.0.0.1 绑定+常量时间比较+ACL→R）、S-3（凭据唯一写者→R）
- 复杂度：H-1（高，NEEDS_LOGIN interactive_login 闭环→Q）、H-2（中，协议失效 runbook+阶段 3 拆 3a/3b）、H-3（低，预算 spike→R）、H-4（低，编号重排——留待文档卫生，避免 packet 失效）

### Failure Modes Registry（Eng）
| CODEPATH | FAILURE MODE | RESCUED? | TEST? | USER SEES? | LOGGED? |
|---|---|---|---|---|---|
| 协议连接 | 断连/静默超时 | Y(重连+退避) | Y(fixtures 场景) | 窗口 GAP | Y |
| 消息解析 | 格式变更 | Y(丢弃计数→ROUTE_FAILED) | Y(fuzz, T-1.1) | 路线告警+fix_hint | Y |
| 背压溢出 | 高水位丢弃 | Y(分级+窗口 GAP) | Y(T-1.8) | GAP+计数 | Y |
| 引擎进程 | 崩溃 | Y(监护重启+慢速重试) | Y(TerminateProcess) | 故障告警+恢复事件 | Y |
| 持久化 | 磁盘满/损坏 | Y(粗粒度 GAP 降级) | Y(T-1.6) | GAP(不可信标记) | Y |
| 登录态 | 过期/互踢 | Y(NEEDS_LOGIN 闭环) | Y(集成) | QR/URL 提示 | Y |
CRITICAL GAPS: 0（全部路径有救援+测试+可见性）

### Worktree 并行化策略
| Step | Modules touched | Depends on |
|---|---|---|
| 阶段 0 契约+骨架 | danmaku_listener 核心 | — |
| 阶段 1 B站 / 2 抖音 / 3a 斗鱼 / 3b 虎牙 / 4 快手 | 各 adapters/engines 子树 | 阶段 0 |
| 阶段 5 视频号 | browser_engine 改造 | 阶段 0 |
| 阶段 6 兜底+收口 | bus/ 全局 | 阶段 1-5 |
| 阶段 7 集成验收 | 全局 | 全部 |
并行车道：Lane A = 阶段 1→3a→4（协议系）；Lane B = 阶段 2（代理系）；Lane C = 阶段 5（浏览器系）——三车道在阶段 0 完成后并行，阶段 6 汇合，阶段 7 收口。

### Completion Summary（Eng）
- Step 0: Scope accepted as-is
- Architecture Review: 3 issues（A-1 高/A-2/A-3，全部采纳）
- Code Quality Review: 1 issue（H-4 编号卫生，留待清理）
- Test Review: diagram produced, 8 gaps identified（T-1，入测试计划）
- Performance Review: 2 issues（E-4 压测矩阵、H-3 预算 spike，采纳）
- NOT in scope: written；What already exists: written（CEO 表）
- TODOS.md updates: 1 item（T-2 CI diff）
- Failure modes: 6 rows, 0 critical gaps
- Unresolved decisions: 0（全部自动决策采纳，User Challenge 1 项排队最终门——CEO F1）
- Outside voice: codex unavailable（provider 400×3 阶段累计）
- Parallelization: 3 lanes（协议/代理/浏览器），阶段 0 后并行
- Lake Score: N/A（kind-only）

## Autoplan 决策审计轨迹

| # | 阶段 | 决策 | 分类 | 原则 | 理由 | 否决项 |
|---|---|---|---|---|---|---|
| 1 | CEO | 模式=SELECTIVE_EXPANSION | 机械 | autoplan 覆盖 | 覆盖规则固定 | — |
| 2 | CEO | 接受扩展：fixtures/风控手册/调试三项 | 机械 | P2 | blast radius 内+S 成本 | — |
| 3 | CEO | 推迟 Prometheus 指标 | 机械 | P3 | 等 AUTOlive 监控栈 | — |
| 4 | CEO | 拒绝弹幕发送 | 机械 | 用户约束 | 只监听 | 发送能力 |
| 5 | CEO | F3 合规评审入阶段 0 | 机械 | P1 | CRITICAL 缺口 | — |
| 6 | CEO | F2 ADR+F10 许可证审计入阶段 0/1 | 机械 | P1/P5 | 显式化决策 | — |
| 7 | CEO | F4/F7 运维模型+止损入阶段 7 | 机械 | P1 | 7x24 承诺可运营 | — |
| 8 | CEO | F1 需求门禁→User Challenge | User Challenge | — | 与用户 D6 决策张力 | — |
| 9 | DX | DX 交付束 A-K 全采纳 | 机械 | P1/P5 | 阶段 0 一次成型 | — |
| 10 | Eng | 7 项前置（L-R）+3a/3b 拆分全采纳 | 机械 | P1 | 阶段 0 出口前关闭 | — |
| 11 | Eng | T-2 CI diff→TODOS | 机械 | P3 | 非阻塞工程化 | — |

## User Challenges（排队至最终审批门）

- **Challenge 1（来自 CEO 原生评审 F1）**：你说「六平台全做齐再交付」（依据：客户多平台同时开播）。Claude CEO 建议：阶段 3-5（斗鱼/虎牙/快手/视频号）增设需求门禁——无第二客户信号或明确战略理由则推迟。两种立场不矛盾但优先级张力真实存在：若平台优先级验证（已入阶段 0 客户校验）显示电商客户集中在抖音/快手/视频号，先做 B站/斗鱼/虎牙的排序可能推迟核心价值交付。最终审批门裁决。

（评审流水线进行中——CEO 阶段 Step 0 完成，其余评审结论将追加到本节。）

