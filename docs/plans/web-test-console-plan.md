<!-- /autoplan restore point: "C:\\Users\\admin\\.gstack\\projects\\DanmakuListener\\master-autoplan-restore-20260928-093036.md" -->
# Implementation Plan: Web 测试控制台 v2（前端完善，服务手工测试）

Generated: 2026-09-28 | Branch: master | Status: DRAFT（CEO 已过，待 Design/DX/Eng 评审）
设计依据: docs/designs/six-platform-danmaku-rebuild.md（背景）；web/static 处置条款（阶段 0 义务块）由用户触发：**保留 web 前端为测试控制台并完善**

## Implementation plan

### 目标

把现有 web 前端（web/static + web/app.py，1700 行骨架：房间管理/代理控制/弹幕流/关键词屏蔽）升级为**契约 v1 测试控制台**，使用户能在浏览器里完成弹幕监听系统的手工测试（对应 docs/testing/manual-test-procedure.md 的观测点），并对接阶段 0-6 新增的统一消息契约。

### 架构概览

```
AUTOlive（生产消费者，8765 PushServer，不变、隔离）
测试控制台链路（web/app.py 端口 8080）：
  引擎实例（registry 构造）→ bridge.py（legacy→UnifiedMessage 转换）
  → web/app.py 广播（复用 push.ws_server.PushServer 类实例，非 8765 那个）
  → /ws（契约 v1 线格式，含 SYSTEM_STATUS）
  → 浏览器前端 v2（/static，纯静态无构建链）
  ├── /api/rooms   → 房间管理（现有）
  └── /api/status  → 引擎/统计快照（数据源=bridge 实际引擎实例）
```

核心决策：**web/app.py 的 /ws 输出统一升级为契约 v1 线格式**（旧 ad-hoc 消息如
reconnect_success 映射为 SYSTEM_STATUS），8765 PushServer 保持不变（AUTOlive 专用）。
前端为纯静态 HTML/JS/CSS（无框架无构建链，P5）。

### 阶段分解

**阶段 W1：后端契约桥接**
1. bridge.py 消息出口统一：引擎消息（UnifiedMessage 线格式）直通；旧 DanmakuMessage 经 contract.legacy 转 UnifiedMessage 后输出；ad-hoc 事件（reconnect_success 等）→ SYSTEM_STATUS/ENGINE_STATUS 映射
2. /api/status 扩展：引擎快照（engine_id、每房间 seq、收发计数、TTHW/最近延迟样本）
3. serve 集成：danmaku-serve 可选挂载 web 前端（--web 开关）。回放注入复用既有 `fixtures/replayer.py`（阶段 0 交付）——`serve --replay` 已把回放 wire 广播到通道（阶段 0 实现），web 前端经同一通道接收
4. **端口策略（裁定）**：web 前端与 /ws 挂在 web/app.py 现有端口（8080，配置项 web_port）；**8765 专属 PushServer（AUTOlive 契约通道），web 端口不得占用 8765**（隔离硬约束）
5. 数据源标识：前端直接显示 `envelope.engine`（live 引擎=protocol:x/proxy:x，回放=replay:demo）——无需新增字段
4. 单元测试：桥接映射（legacy→wire、ad-hoc→SYSTEM_STATUS）、status 快照结构

**阶段 W2：前端 v2（index.html/app.js/style.css 原地升级）**
1. 消息流渲染按 category 分流：business 消息带类型徽章（八类：DANMU/GIFT/SUPER_CHAT/ENTER_ROOM/LIKE/LIVE_STATUS_CHANGE/ROOM_STATS/SOCIAL，各自色系）；GIFT/SUPER_CHAT 特殊样式（金额/连击）；机读 Schema：docs/contract/schema.json（校验脚本 scripts/export_contract.py --check）
2. SYSTEM_STATUS 告警条（**全部 8 种**，定义见 `danmaku_listener/contract/models.py` SystemType 枚举）：① HEARTBEAT→统计面板心跳指示；② ROOM_STATUS→房间在线徽章；③ GAP→黄色警示条（窗口+原因+approx 标记）；④ NEEDS_LOGIN→紫色操作条（fix_hint + interactive_login.qr_image_b64 直接 `<img src="data:image/png;base64,...">` 渲染——契约字段已定义，无前端新依赖）；⑤ ENGINE_STATUS→当前引擎标识更新；⑥ BACKPRESSURE→丢弃计数条；⑦ ROUTE_FAILED→红色错误条（reason_code+fix_hint+docs_anchor 可点击链接）；⑧ RECOVERED→绿色恢复提示
3. 统计面板：按类型实时计数、消息速率（msg/s，10s 滚动窗口）、当前引擎标识；**多房间维度**：每条消息显示 platform:room_id 前缀，统计面板按房间分组（可折叠），seq 连续性按房间观察（跳跃提示等待该房间 GAP）
4. 类型过滤 chips + 关键词屏蔽（现有功能保留）
5. 观测辅助：消息 timestamp 与本地时钟差显示（延迟观测，R3-4 口径备注）
6. 回放模式标识（连接横幅显示数据源：live/replay）

**阶段 W3：端到端验证**
1. fixtures 回放 → 前端全类型渲染验证（对照 demo.jsonl 12 条）
2. B站真实引擎 → 前端实测（与 docs/testing/manual-test-procedure.md §4A 联动）
3. GAP 触发（拔网线）→ 告警条验证（对应测试流程 §5.1）
4. 文档更新：web/static 处置条款兑现记录 + 测试流程文档引用前端

### 验收标准

- 前端渲染的消息 100% 为契约 v1 线格式（devtools 可校验 against schema.json）
- 九类业务消息 + 8 种 SYSTEM_STATUS 事件全部有视觉呈现（含 NEEDS_LOGIN 的 QR 图渲染）
- 房间管理/关键词屏蔽现有功能无回归（现有 web 测试通过）
- 回放与真实引擎两种数据源下前端均可正常渲染
- 无构建链：直接静态文件服务即用

### 依赖与前置

- 无外部新依赖（aiohttp + 原生 JS）
- contract.legacy 适配器已存在（阶段 0 交付）

### 不在范围（NOT in scope）

- AUTOlive 前端（生产 UI 仍归 AUTOlive；本前端定位为**本地测试控制台**，页面标注）
- 构建链/框架引入（React/Vue 等）
- 消息持久化/历史存储（前端刷新即清空，与契约边界一致）
- 8765 PushServer 的改动（AUTOlive 契约通道冻结）
- 弹幕发送能力（只监听）


<!-- autoplan-accepted:ceo -->
- web /ws 输出统一升级为契约 v1 线格式：引擎消息直通（UnifiedMessage.to_wire）；旧 DanmakuMessage 经 contract.legacy 转换；ad-hoc 事件（reconnect_success 等）映射为 SYSTEM_STATUS——旧格式消息不再出现在前端
- 广播逻辑单源：web/app.py 复用 push.ws_server.PushServer（或抽出共享广播器），禁止两份 WS 广播实现
- /api/status 扩展的数据源为 bridge 实际引擎实例的真实状态（engine_id/seq/计数），不虚构
- NOT in scope 约束生效：无 AUTOlive UI、无构建链、无消息持久化、8765 PushServer 冻结
- 前端页面标注「本地测试控制台」定位（与 AUTOlive 生产前端区分）
- 契约漂移：schema.json 变更必须经 export_contract.py --check（CI 可用）
<!-- /autoplan-accepted:ceo -->

<!-- autoplan-accepted:design -->
- 告警条位于弹幕流顶部固定堆叠（最新在上可关闭）；统计面板右栏上半、关键词屏蔽右栏下半
- 交互状态表全量落地（连接/弹幕流/统计/QR 的 LOADING-EMPTY-ERROR-SUCCESS-PARTIAL）
- 中文字体栈显式声明（PingFang SC/Microsoft YaHei 优先）；新增九类徽章色与三类告警色 CSS 变量
- 最小 a11y：键盘可达、对比度 ≥4.5:1、弹幕流 ARIA live region；<900px 右栏折叠；移动端非目标
- 空态文案即首访引导（不加 tour）
<!-- /autoplan-accepted:design -->

<!-- autoplan-accepted:dx -->
- DX 交付：serve --web 开关挂载前端（web_port 8080 独立于 ws_port 8765）；前端显示 envelope.engine 数据源标识与 TTHW/延迟观测
<!-- /autoplan-accepted:dx -->

<!-- autoplan-accepted:eng -->
- bridge.py 旧 ad-hoc 事件映射表显式实现并单测覆盖（reconnect_success→ENGINE_STATUS/RECOVERED、房间启停→ROOM_STATUS、未知→ENGINE_STATUS detail 兜底）
- web 通道默认 loopback 无 token（可选 token 复用 load_token）；桥接单测（legacy→wire 全类型）+ 现有 web 测试回归为验收项
- 500 条上限与 10s 速率窗口内存有界维持
<!-- /autoplan-accepted:eng -->
## Review record


<!-- autoplan-accepted:ceo -->
- web /ws 输出统一升级为契约 v1 线格式：引擎消息直通（UnifiedMessage.to_wire）；旧 DanmakuMessage 经 contract.legacy 转换；ad-hoc 事件（reconnect_success 等）映射为 SYSTEM_STATUS——旧格式消息不再出现在前端
- 广播逻辑单源：web/app.py 复用 push.ws_server.PushServer（或抽出共享广播器），禁止两份 WS 广播实现
- /api/status 扩展的数据源为 bridge 实际引擎实例的真实状态（engine_id/seq/计数），不虚构
- NOT in scope 约束生效：无 AUTOlive UI、无构建链、无消息持久化、8765 PushServer 冻结
- 前端页面标注「本地测试控制台」定位（与 AUTOlive 生产前端区分）
- 契约漂移：schema.json 变更必须经 export_contract.py --check（CI 可用）
<!-- /autoplan-accepted:ceo -->

## CEO 评审记录（2026-09-28，[single-model]）

- **0A 前提**：用户显式方向变更（测试控制台），直接解决「手工测试流程文档的可视化观测点」痛点——非代理指标 ✓。与「AUTOlive 唯一前端」前提的变更已由用户触发，义务块兑现 web/static 处置条款。
- **0B 复用**：web/static 1700 行骨架（房间管理/代理/弹幕流/关键词）、contract.legacy 适配器、PushServer 广播模式——全部复用，新代码集中在桥接与渲染 ✓
- **0C 梦想态**：测试控制台是 AUTOlive 集成的消费端预演（处理矩阵同构），测试期发现的契约问题反哺生产集成
- **发现**：CEO-1（中）双通道广播实现分裂风险 → 采纳单源义务；CEO-2（中）/api/status 数据源未定义 → 采纳真实实例约束；CEO-3（低）前端膨胀风险 → NOT in scope 已约束，无动作
- **范围裁定**：SELECTIVE_EXPANSION——无新增范围提案（计划自身已克制）；复杂度 ~6 文件低于阈值
- Outside voice: codex unavailable（第 4 次，provider 持续 400）
- **范围裁定（spec SC1）**：NEEDS_LOGIN 的 QR 图渲染属**观测呈现**（显示引擎发来的 interactive_login 载荷），非控制通道——不触碰「只监听」边界；批准进入 v2

## 决策审计轨迹（本次 autoplan 轮次）

| # | 阶段 | 决策 | 分类 | 原则 | 理由 |
|---|---|---|---|---|---|
| 1 | CEO | web/static 处置=保留为测试控制台 | 用户裁定 | — | 用户显式触发义务块条款 |
| 2 | CEO | web /ws 升级契约线格式 | 机械 | P1 | 测试观测点依赖统一消息 |
| 3 | CEO | 广播逻辑单源化 | 机械 | P4 DRY | CEO-1 |
| 4 | CEO | 8765 PushServer 冻结 | 机械 | 用户约束 | AUTOlive 契约通道 |


（CEO 已完成——Design/DX/Eng 评审结论将追加到本节。）

## Design 评审记录（Phase 2，UI scope，[single-model]，2026-09-28）

- 设计器无 OpenAI key → 文本评审回退（Step 0.5 fallback）；Design Outside Voices 按 autoplan 跳过清单跳过
- 分类：**OPERATE**（App UI 测试控制台）——密集可读、utility 语言、最小装饰
- **Pass 1 IA：5→8**。告警条位置裁定：置于弹幕流顶部（中栏上缘固定堆叠，最新在上可关闭）；统计面板右栏上半（引擎/速率/计数），关键词屏蔽移右栏下半
- **Pass 2 状态覆盖：4→8**。交互状态表（新增）：连接=状态点闪烁/断线红点重连倒数/绿点+引擎标识；弹幕流=空态引导文案（"添加房间或启动 --replay 回放"）/GAP 后插入缺口标记；统计=全 0 初始化；QR=加载中/超时提示
- **Pass 3 Journey：6→8**。情绪弧：困惑→掌控→信任；首访引导=空态文案即引导（不加 tour，Rams 减法）
- **Pass 4 AI Slop：6→8**。踩坑：system-ui 主字体（blacklist #11）→ **裁定**中文字体栈 "PingFang SC","Microsoft YaHei" 显式声明；无渐变/无 3 列网格 ✓
- **Pass 5 设计系统：5→8**。CSS 变量已有 ✓；新增：--type-danmu/gift/... 九类徽章色 + --warn-gap/login/route 告警色；无 DESIGN.md → 内联变量约定记录于 style.css 顶部（测试工具不引入 design-consultation）
- **Pass 6 响应式+a11y：3→7**。最小 a11y：按钮键盘可达、正文对比度 ≥4.5:1、弹幕流 ARIA live region；响应式最小：<900px 右栏折叠；**移动端非目标（NOT in scope 增补）**
- **Pass 7 未决决策**：以上裁定全部落地后无未决

```
  +====================================================================+
  |         DESIGN PLAN REVIEW — COMPLETION SUMMARY                    |
  +====================================================================+
  | Pass 1 IA 5→8 | Pass 2 States 4→8 | Pass 3 Journey 6→8           |
  | Pass 4 Slop 6→8 | Pass 5 Sys 5→8 | Pass 6 Resp 3→7 | P7: 0 deferred |
  | Overall: 3/10 → 7/10（a11y/响应式按测试工具最小口径有意收窄）        |
  +====================================================================+
```

## DX 评审记录（Phase 2.5，[single-model]，2026-09-28）

八维度初评（框架复用上轮 DX）：GS 8（serve --web 一键）/API 8（--web 开关一致）/Errors 8（前端告警三段式）/Docs 7（测试文档引用前端）/Upgrade 7（现有功能无回归）/DevEnv 9（无构建链）/Community N/A/Measure 7（TTHW+延迟显示）。Overall 8/10。
发现：DX-1 serve --web 端口冲突处理 → W1.4 已裁定（web_port 8080 独立于 ws_port 8765）✓ 无新发现。

## Eng 评审记录（Phase 3，[single-model]，2026-09-28）

- Scope Challenge：~7 文件接近阈值但结构清晰（桥接/静态/文档分层）；autoplan never reduce ✓ scope accepted as-is
- **发现与采纳**：
  - E1（中）：bridge.py 旧 ad-hoc 事件映射清单必须显式——**裁定映射表**：reconnect_success→ENGINE_STATUS(已恢复)；房间启停→ROOM_STATUS；未知事件→ENGINE_STATUS(detail=原名)；映射表写入实现并单测覆盖
  - E2（低）：web 通道 token 策略——测试控制台默认 loopback 无 token（与 PushServer 默认一致），token 可选支持 ✓（load_token 已有）
  - E3（中）：测试——桥接映射单测（legacy→wire 全类型）+ 现有 web 测试回归 + 前端渲染人工验证（测试流程文档 §3/§4 联动）
  - E4（低）：500 条上限与 10s msg/s 窗口内存有界 ✓（现有模式）
- Failure Modes：桥接映射遗漏→未知事件静默丢失（M）→救援=ENGINE_STATUS 兜底+单测清单；无 CRITICAL GAP

```
ENG DUAL VOICES — CONSENSUS TABLE: Codex unavailable → 6 维度 N/A；native 有条件通过
```

<!-- autoplan-accepted:design -->
- 告警条位于弹幕流顶部固定堆叠（最新在上可关闭）；统计面板右栏上半、关键词屏蔽右栏下半
- 交互状态表全量落地（连接/弹幕流/统计/QR 的 LOADING-EMPTY-ERROR-SUCCESS-PARTIAL）
- 中文字体栈显式声明（PingFang SC/Microsoft YaHei 优先）；新增九类徽章色与三类告警色 CSS 变量
- 最小 a11y：键盘可达、对比度 ≥4.5:1、弹幕流 ARIA live region；<900px 右栏折叠；移动端非目标
- 空态文案即首访引导（不加 tour）
<!-- /autoplan-accepted:design -->

<!-- autoplan-accepted:dx -->
- DX 交付：serve --web 开关挂载前端（web_port 8080 独立于 ws_port 8765）；前端显示 envelope.engine 数据源标识与 TTHW/延迟观测
<!-- /autoplan-accepted:dx -->

<!-- autoplan-accepted:eng -->
- bridge.py 旧 ad-hoc 事件映射表显式实现并单测覆盖（reconnect_success→ENGINE_STATUS/RECOVERED、房间启停→ROOM_STATUS、未知→ENGINE_STATUS detail 兜底）
- web 通道默认 loopback 无 token（可选 token 复用 load_token）；桥接单测（legacy→wire 全类型）+ 现有 web 测试回归为验收项
- 500 条上限与 10s 速率窗口内存有界维持
<!-- /autoplan-accepted:eng -->

## 前端轮次决策审计（CEO→Design→DX→Eng）

| # | 阶段 | 决策 | 分类 | 原则 | 理由 |
|---|---|---|---|---|---|
| 1 | CEO | web /ws 契约化+广播单源+端口隔离 8080/8765 | 机械 | P1/P4 | spec 10 项修复 |
| 2 | CEO | QR 渲染=观测裁定 | 机械 | — | spec SC1，不触碰只监听 |
| 3 | Design | 告警条/统计/关键词三区布局与状态表 | 机械 | P1/P5 | Design passes 1-2 |
| 4 | Design | 中文字体栈+色板变量+最小 a11y | 机械 | P5 | Pass 4-6，移动非目标 |
| 5 | Eng | ad-hoc 事件映射表显式+单测 | 机械 | P5/P1 | Eng E1/E3 |
