<!-- /autoplan restore point: "C:\\Users\\admin\\.gstack\\projects\\DanmakuListener\\main-autoplan-restore-20261008-094412.md" -->
# 多平台弹幕发送实测验收战役计划（2026-10-08）

## Implementation plan

### 背景与目标

- 监听侧十二平台 2026-10-05 全量复测通过（docs/testing/full_platform_test_plan.md 收官矩阵），本战役监听只做回归抽检，不重测。
- 发送侧 T1-T12 已落地、10 平台 sender 接线（danmaku_listener/senders/wiring.py）；M0 探针矩阵（docs/testing/m0-send-probe-cards.md）多平台实发 SUCCESS 终判。
- 用户 2026-10-08 启动逐平台实测验收（docs/ops/send-runbook.md「控制台房间行内发送 QA 清单 v11」），首站淘宝失败（见下节）。
- 目标（按序）：
  1. 修复淘宝集成环境发送失败（P0 blocker）并通过淘宝验收；
  2. 其余 9 接线平台逐个实发验收（B站/快手/虎牙/斗鱼/抖音/1688/小红书/京东/视频号）；
  3. 拼多多/美团发送缺口范围裁定（接线 or 申报边界）——交评审裁定；
  4. 收官报告：逐平台判定 + 缺陷卡 + 运维节奏建议。

### 已知问题：淘宝发送失败（P0，战役首 blocker）

症状（用户实测 2026-10-08）：
1. 点击发送 → 前端 prompt「输入发送 token（persistence_data/send_token.txt 内容）」——F6 鉴权设计，非故障；
2. 输入 token 后发送失败：「✗ 重复内容（DUPLICATE）」；
3. 重启系统再试：「✗ 发送超时（超过 60s）」。

初步解码（代码侦察 2026-10-08）：
- DUPLICATE=本地守卫去重命中，非淘宝服务器语义（danmaku_listener/senders/guard.py:126；pipeline.py:127 发起即占窗口；窗口默认 300s——config/settings.py:91）。上一次尝试（成败不论）后 5 分钟内重试同内容必被本地拒；首次命中来源待审计核实。
- 「超过 60s」=前端 AbortController 客户端超时（web/static/app.js:801），真实信号=后端 sender.send 60s 未返回。taobao_mtop.py 内部预算最坏 goto 30s + topic 20s + mtop lib 20s + eval 15s = 85s，天然可超前端上限（超时预算失配=独立缺陷候选，修复需对齐全链路预算）。
- 根因候选（集成环境 vs T2 探针环境差异）：① 瞬态浏览器 launch_persistent_context 与监听引擎并存时的 profile 冲突/锁行为（taobao_mtop.py:88-94 借引擎 _profile_lock）② 页面 topic 锚定失败（_wait_topic 20s 内无 iliad/powermsg 请求）③ 页面 mtop 库不可达。
- 关键对照事实：T2 管线级实发 status=sent 曾于 2026-10-07 单发实证（tools/send_probes/cards/taobao-mtop-t2-pipeline-20261007.json）——形态本身可行，今日集成失败需定位环境差异。
- 证据源：persistence_data/send_audit.jsonl（intent/result 两行制 + request_id）、服务日志、T1 探针重放健康检查（runbook 每周运维第 1 项）。

### 验收范围与平台矩阵

| 平台 | 监听 | 发送路线 | 既有证据 | 本战役动作 |
|---|---|---|---|---|
| 淘宝 | ✅ | mtop page-eval（瞬态页，DOM 降备选） | T1 探针 SUCCESS×2 + T2 管线 sent（2026-10-07）；集成实测失败（10-08） | P0 修复→探针回归→实发验收 |
| B站 | ✅ | API 直连（E4） | 管线实发 sent ✓（10-07） | 实发验收 |
| 快手 | ✅ | storage_state 注入（瞬态 headless=new） | M0×3 + T6 管线 sent×2 | 实发验收 |
| 虎牙 | ✅ | 常驻会话（headed minimized，35s 冷却） | M0×3 + T6 管线 sent×2 | 实发验收 |
| 斗鱼 | ✅ | cookie 注入（瞬态） | M0×3；T6 管线待真开播房间 | 真开播房间实发验收 |
| 抖音 | ✅ | 常驻会话（headless=new） | M0×3 + T3 管线 sent×2 | 实发验收 |
| 1688 | ✅ | 引擎钩子 DOM（逐键+Enter） | M0 SUCCESS | 实发验收 |
| 小红书 | ✅ | 引擎钩子 DOM（contenteditable+Enter） | M0×3 | 实发验收 |
| 京东 | ✅ | 引擎钩子 DOM | M0×3 | 实发验收 |
| 视频号 | ✅ | 引擎钩子 DOM（shadow DOM 穿透） | M0×3（有头约束） | 实发验收（有头形态） |
| 拼多多 | ✅ | 未接线 | 无 | 范围裁定（评审） |
| 美团 | ✅ | 未接线 | 无 | 范围裁定（评审） |

### 验收方法与判定标准

- 方法：runbook v11 QA 清单逐平台执行（dry-run→实发→错误分支）；每平台留存审计文件行号 + 截图证据。
- 平台验收通过判据：实发回执「✓ 已发送」+ 弹幕流回环可见（F8 链路）；错误分支回执文案正确（runbook 清单第 4/5/6 项）。
- 节奏：每平台验收→失败即记缺陷卡（症状/根因/修复面/证据）→P0 缺陷停线修复→探针回归→复验→下一平台。
- 监听回归抽检：每平台验收前确认监听正常（淘宝监听已由用户实测无异常）。

### 失败处理流程

缺陷记录（含审计行号/截图）→ 根因定位（send_audit.jsonl + 服务日志 + tools/send_probes 探针）→ 修复（最小面，根因优先）→ 对应平台探针回归 → runbook 清单复验 → 记录归档。

### 交付物

1. 淘宝发送修复（含超时预算全链路对齐）PR；
2. 逐平台验收记录（runbook 清单勾选 + 证据）；
3. 拼多多/美团范围裁定记录（ADR 或 TODOS 条目）；
4. 收官报告：发送验收判定矩阵 + 缺陷清单 + 运维建议。

### 非目标（NOT in scope）

- 拼多多/美团发送接线开发（除非平台矩阵裁定纳入）；
- 1688 mtop 同构化（TODOS P3 优化项，无实测痛点）；
- 监听侧功能增强与重测（2026-10-05 已收官）；
- AUTOlive 侧对账逻辑改动（F8 契约已定）。

### 已存在资产（What already exists）

- runbook v11 QA 清单、M0 探针矩阵、探针工具（tools/send_probes/）、审计文件（persistence_data/send_audit.jsonl）、测试卡片（tools/send_probes/cards/）、十二平台监听引擎与登录闭环。

## Review record

评审：/plan-ceo-review 2026-10-08（HOLD SCOPE，经 /autoplan 路线 C 授权自动裁定；外部声部 unavailable——codex gpt-6-astra 400 InvalidParameter，与 2026-10-06 学习 [codex-model-gpt6astra-400] 同因，修复=GSTACK_CODEX_MODEL 或修 ~/.codex/config.toml）。基线 commit fe85b78。

### Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|-------|----------|----------------|-----------|-----------|----------|
| CEO-1 | ceo | 淘宝 sender 阶段预算收敛：goto+topic+lib+eval 合计 ≤55s，前端 60s 中止不变 | Mechanical（deliverable 1 已含"预算全链路对齐"） | P3 pragmatic | 最坏 85s>60s 是 DUPLICATE 影子与超时幻象的直接成因；压缩后端而非放大前端，失败面更小 | 放大前端超时到 90s（掩盖后端病，用户等待更长） |
| CEO-2 | ceo | 修复前先取证：读 send_audit.jsonl 失败尝试实际 result + 跑每周 mtop replay 健康检查 + 复核 taobao.py 凭证提取浏览器生命周期 | Mechanical | P6 bias to action 的前提=证据先行 | 若审计显示曾 sent，则问题纯为预算/回执 UX；若 none/failed 才需定位挂起阶段——两分支修法不同 | 跳过取证直接改代码 |
| CEO-3 | ceo | 发送异常围栏加在管线唯一分发点（pipeline.py:128 sender.send 包裹→UNKNOWN 回执+审计 result 行），sender 级保留 ret 映射并补 catch | Mechanical | 根因修在共享函数（一处护栏覆盖全部 10 平台） | 现状异常穿透到 aiohttp 500；新版 TaobaoMtopSender 丢了旧 DOM 钩子的 E5 隔离（taobao.py:277 有、taobao_mtop.py 无） | 只在 TaobaoMtopSender 内包 catch（其余 sender 裸奔） |
| CEO-4 | ceo | 拼多多/美团发送接线：DEFER → TODOS.md（满足计划交付物 3 的裁定记录） | Taste（最终批准门呈现） | P3+范围纪律 | 无 sender 代码、无实测痛点证据；补线=新功能开发，与本验收战役范围冲突；沿用美团进场裁定先例（协议边界申报） | 本战役内补线（scope creep，XL 级） |
| CEO-5 | ceo | 前端 AbortError 后对账轮询：中止后单次查询 GET /api/send-results?request_id= 兜底回显真实结果 | Taste（最终批准门呈现） | P1 completeness（结果不可见=零号静默失败） | 预算收敛后中止不应再发生，但一旦发生（慢页/网络抖动）结果仍不可见；F9 幂等索引已就绪，查询是现成端点 | 不做（赌预算收敛覆盖全部场景） |
| CEO-6 | ceo | 可观测补齐：sender 阶段日志（goto/topic/lib/eval 完成+耗时）、pipeline 日志 detail 截断 60→200、runbook 失败表补 busy/hang/对账行 | Mechanical | P1（本类 bug 三周后必须可从日志重建） | 本次排障最大的痛=只有前端文案没有阶段证据 | 只加日志不更新 runbook |
| CEO-7 | ceo | 验收合规显式化：验收发送仅限自运营/受托直播间（ADR-002），且避开监听重登窗口（可见登录 240s 预算期间发送必 busy） | Mechanical（设计文档既有约束的继承） | P5 explicit | 设计文档约束已存在但计划未显式引用；验收时序踩重登窗口会误判"发送失败" | 不写进验收判据（靠执行人记忆） |
| CEO-8 | ceo | DUPLICATE fix_hint 增加对账指引（"上次尝试未出结果时先查 /api/send-results"）+ app.js 两处 60000 字面量提取常量 | Mechanical | P5 explicit | DUPLICATE 是影子症状，提示语要指路而非只报错 | 保持现状文案 |

### 评审节 findings（1-10 全跑，11 跳过）

**Section 1 架构**：现状复用充分（管线单例/R32 唯一分发点/E5 锁/F2 快照/F9 幂等），无新架构面。4 findings：A1 预算失配（CRITICAL，CEO-1 修）；A2 取证先行（CEO-2）；A3 规模特性 OK（发送受 30s 限速键约束，无放大面；SPOF=per-profile 锁单实例，设计固有已文档化）；A4 监听×发送 profile 生命周期耦合（WARNING——稳态监听无常开浏览器、凭证提取瞬态+锁串行，重登窗口期发送必 busy，CEO-7 验收时序规避）。

```
webui(app.js) --Bearer--> /api/send-danmu(app.py:316) --> DanmuCommandPipeline(pipeline.py)
  --> F6 鉴权 → F9 幂等 → 熔断/开关 → F2 房间快照 → 守卫链(guard.py)
  --> R25 审计 intent --> registry.get(platform) --> record_attempt(占窗口)
  --> sender.send ──> TaobaoMtopSender: _profile_lock(3s busy) → 瞬态浏览器
        goto(30s)→topic 锚定(20s)→mtop lib(20s)→page-eval mtop.request(15s)→ret 五路径映射
  --> record_result(熔断) --> _finish(审计 result+广播) --> webui 回执
  ✗ 异常路径（现状）: sender raise → 管线无围栏 → aiohttp 500 → 前端"服务错误"，审计无 result 行
```

**Section 2 错误与救援**（修复前现状→修复后）：

| CODEPATH | 可出错 | 现状救援 | 修复后（CEO-3/1） | 用户所见 |
|---|---|---|---|---|
| TaobaoMtopSender._send_locked 任意异常（launch 冲突/evaluate 崩） | TargetClosedError 等 | ✗ GAP 穿透 500 | 管线围栏→UNKNOWN+审计行 | 结构化回执，不再 500 |
| goto 失败 | TimeoutError | ✓ UNKNOWN/SEND_TIMEOUT（taobao_mtop.py:100） | 保持 | 回执文案 |
| topic 锚定失败 | 20s 无请求 | ✓ FAILED+fix_hint | 保持+阶段日志 | "未能锚定 topic" |
| mtop lib 缺失 | 页面改版 | ✓ ROUTE_UNVERIFIED | 保持 | "重跑 T1 探针" |
| ret 风控/登录/参数/未知 | 服务端码 | ✓ 五路径（单测 9/9） | 保持 | 对应 fix_hint |
| 前端 60s 中止而后端继续 | 慢页 | ✗ GAP 结果无人认领 | 预算≤55s+CEO-5 对账轮询 | 真实结果回显 |
| DUPLICATE 影子 | 上次尝试占窗口 | ✓（R14 设计语义，不改） | CEO-8 提示语指路 | 明确"查对账" |

CRITICAL GAP（修复前）：2（异常穿透、中止后结果不可见）——均有已批准补救。

**Section 3 安全**：无新端点/新依赖/新秘密；Bearer 常量时间比较 ✓；内容清洗（guard S3-1）✓；审计 fail-closed（R25）✓。1 finding：ADR-002 发声场景约束需显式进验收判据（CEO-7，Medium→闭环）。备注（不在本计划修）：webui 将 send_token 存 localStorage 为既有模式，XSS 面存在但与 v0.6.1.0 一致，不新增。

**Section 4 数据流/交互边界**：双击（发送中禁用 ✓ runbook 清单 3）；重试撞去重窗口（语义保持+提示改进 CEO-8）；request_id 幂等（F9 ✓）；异步序——profile 锁串行化监听/发送浏览器操作，锁 3s 超时 busy 回执（S4-1 ✓），两个完成序均安全（机制=asyncio.Lock）。无未处理边界。

**Section 5 代码质量**：2 findings——隔离回归缺口（CEO-3 修，根因在共享分发点）；_detail 日志截断 60 字符会切掉 ret 详情（CEO-6）。命名/复杂度/重复度 OK（_wait_topic 与 taobao.py TOPIC_ANCHORS 同构为已文档化的刻意选择）。

**Section 6 测试**：既有 9 单测（ret 五路径/凭证缺失）+全量 607 绿。缺口与新增（CEO-1/3 的直接回归）：①管线围栏——monkeypatch sender 抛异常→断言 UNKNOWN 回执+审计 result 行落盘；②预算 tripwire——模块常量和 ≤55s 断言（防未来调参回退）；③集成实证——监听运行中发送（复现集成环境）作为 T1 根因卡证据；④敌意 QA——launch 失败（杀浏览器）→结构化回执非 500；锁占用→busy。测试注入点沿用模块级 async_playwright monkeypatch 既有模式。金字塔：单测为主+1 探针实证，无 E2E 新增。

**Section 7 性能**：发送频次受守卫约束（30s 间隔+8s 抖动），瞬态浏览器冷启动 1-3s，无 DB/N+1 面。预算收敛后 p99 ≤55s。OK，无 findings。

**Section 8 可观测**：3 findings 全部入 CEO-6（阶段日志/detail 截断/runbook 行）。周成功率报表已存在（runbook CEO-F13/ENG-7）✓。三周后重建能力：修复后每次尝试有 intent+result+阶段耗时三段证据 ✓。

**Section 9 部署**：无迁移；配置零变更；单 PR 回滚=revert；平台级开关（send_enabled_platforms）已含布控面；部署后 5 分钟冒烟=runbook 清单淘宝行+周检 replay。无 findings。

**Section 10 长期轨迹**：可逆性 4/5（单 PR 无 schema）；新增债=app.js 60000 字面量重复（CEO-8 清偿）；升级路径=若瞬态形态再触行为风控，常驻会话模式（douyin T3 ResidentSendSession 先例，学习库 [douyin-send-resident-session]）是现成 PLAN B，不需要现在建；1 年之问：mtop 模板漂移由周检 replay 把守 ✓。知识集中度：runbook 是权威，CEO-6 补齐失败行后闭环。

**Section 11 设计/UX**：SKIPPED（no UI scope——快照 scope API 命中 1<阈值 2）。

### NOT in scope（含裁定）

| 项 | 裁定 | 理由 |
|---|---|---|
| 拼多多/美团发送接线 | DEFER → TODOS.md（CEO-4） | 无 sender 代码无痛点证据；新功能≠验收战役；沿用协议边界申报先例 |
| 1688 mtop 同构化 | 维持既有 defer | TODOS P3 已有（2026-10-07），无实测痛点 |
| 监听侧重测/增强 | 排除 | 2026-10-05 已收官，只做回归抽检 |
| AUTOlive 对账逻辑改动 | 排除 | F8 契约已定，对账端点已存在 |
| 守卫去重语义变更（failed 释放窗口） | 排除 | R14 既有裁定"发起即占窗"防连发穿透；影子症状由 CEO-1/8 消解 |
| DOM 兜底回切准备 | 排除 | deprecated 保留作 T4 参照即可，无触发证据 |

### What already exists（复用清单）

M0 探针工具与卡片（tools/send_probes/）、runbook v11 QA 清单、审计文件+幂等索引（send_audit.jsonl/send_idempotency.json）、ret 五路径映射+9 单测、E5 per-profile 锁、周检 replay 命令、常驻会话模式（PLAN B）、/api/send-results 对账端点（CEO-5 的现成依赖）。全部复用，零重建。

### Dream state delta

12 个月理想态：十二平台监听+发送全自动底座（AUTOlive 唯一前端）+官方通道合规备胎（TODOS CEO-F11 评估）。本战役后：发送从"探针级可用"推进到"生产形态逐平台实证验收"，淘宝集成环境缺陷清零，缺口与风险有台账（pdd/美团 defer、mtop 模板周检、风控升级时常驻会话 PLAN B）——楔子从"能发"到"可运营"。

### 时序审问（0I）

- 第 1 小时：读 send_audit.jsonl 失败尝试的 intent/result（request_id、时间差、实际 status）→ 跑周检 replay → 读 taobao.py 凭证提取与监听循环的浏览器生命周期；产出根因卡（挂起在哪个阶段/是否实际 sent）。
- 第 2-3 小时：管线围栏+预算收敛+sender catch；单测三连（围栏/tripwire/既有 9 测不回退）。
- 第 4-5 小时（集成）：**监听运行中**实测发送（这是与 T2 探针环境的差异点）；确认无重登窗口；验证 busy 路径。
- 第 6 小时+：runbook 清单淘宝行复验（dry-run→实发→错误分支）+ 截图/审计行号归档。
- 阻塞面：淘宝房间须开播（topic 锚定依赖页面请求）；登录态须有效（监听正常即基本成立）。

### Implementation Tasks

由上述 findings 合成；可与后续 Eng 阶段任务清单合并去重。

- [x] **T1 (P1, human: ~30min / CC: ~10min)** — 取证诊断——审计读取+周检 replay+taobao.py 生命周期复核，产出根因卡 ✅ 2026-10-08 完成
  - Surfaced by: Section 1 A2 / CEO-2
  - Files: persistence_data/send_audit.jsonl（读）、tools/send_probes/taobao_mtop_capture.py（跑）、docs/testing/m0-send-probe-cards.md（根因卡回填）
  - Verify: 根因卡写明失败尝试的实际 status 与挂起阶段（sent/failed/none 三选一+证据行号）
  - **结论**：none（挂起）——审计行 54/56 均 intent 无 result，行 55 DUPLICATE=影子实锤；挂点超 85s 预算→无超时 await，头号嫌疑 evaluate 无 wait_for（taobao_mtop.py:113）；详见根因卡（m0-send-probe-cards.md:39-65）。周检 replay 视房间开播情况执行（需实发确认）
  - **定稿（10-08 探针实证）**：挂起根因=**x5sec 风控触发 noCaptcha 验证，headless 瞬态页无人可解，mtop.request promise 永挂**。分阶段计时：launch/goto/topic/lib 全部秒级 ✓，eval_mtop 20s TIMEOUT；网络层捕获 `_____tmd_____/report?x5secdata=…` + `nocaptcha/initialize.jsonp`。独立干净进程复现（集成并发假设否决）。T1 探针零弹幕落地。附带发现：runbook 周检命令缺 `--page-eval`（T5 修正）。PLAN B=有头/常驻会话（验收阶段复现时裁定）
- [x] **T2 (P1, human: ~1天 / CC: ~30min)** — 修复——管线级 sender.send 异常围栏（UNKNOWN+审计 result 行）+ TaobaoMtopSender 阶段预算收敛 ≤55s + sender 级 catch 保留 ret 语义 ✅ 2026-10-08 完成
  - Surfaced by: Section 2 GAP / CEO-1、CEO-3
  - Files: danmaku_listener/senders/pipeline.py、danmaku_listener/senders/taobao_mtop.py
  - Verify: 新增单测（raise→UNKNOWN+result 行）+ 全量 pytest 绿
  - **落地**：管线围栏（UNKNOWN/SEND_TIMEOUT+审计行）；预算 goto20+topic12+lib8+eval15=55s；JS timeout 12s 同步；evaluate wait_for 兜底；x5sec 网络信号检测（FAILED+「验证待人工」hint）；E5 隔离 catch。实弹验证：同一房间 120s 永挂→16.8s 结构化回执
- [x] **T3 (P1, human: ~2h / CC: ~15min)** — 预算 tripwire 单测：阶段常量和 ≤55s 断言 + launch 失败→结构化回执测试 ✅ 2026-10-08 完成
  - Surfaced by: Section 6 / CEO-1、CEO-3
  - Files: tests/unit/test_taobao_mtop_sender.py
  - Verify: pytest tests/unit/test_taobao_mtop_sender.py
  - **落地**：8 个新测试（tripwire×2/风险信号纯函数/eval 未决→UNKNOWN/x5sec→FAILED/launch 失败→结构化/管线围栏×2 于 test_send_pipeline_fence.py）；全量 642 passed
- [x] **T4 (P2, human: ~2h / CC: ~20min)** — 前端对账轮询：AbortError 后单次 GET /api/send-results 兜底回显 + 60000 常量提取 ✅ 2026-10-08 完成
  - Surfaced by: Section 2 / CEO-5、CEO-8
  - Files: danmaku_listener/web/static/app.js
  - Verify: runbook 清单新增"慢页中止→对账回显"手测项
  - **落地**：SEND_TIMEOUT_MS 常量提取（两处字面量清零）；request_id 提升；fetch 层/响应读取层两处中止点统一走 reconcileAfterAbort（2s 宽限→带 Bearer 单次查询→sent/dry_run/failed 三态回显（sent 附带清空+焦点回位）→查不到回落「结果待对账」）；runbook 清单第 9 项；node --check 通过
- [x] **T5 (P2, human: ~1h / CC: ~15min)** — 可观测：sender 阶段日志（阶段名+耗时）、pipeline detail 截断 60→200、runbook 失败表补 busy/hang/对账三行 ✅ 2026-10-08 完成
  - Surfaced by: Section 5、8 / CEO-6
  - Files: danmaku_listener/senders/taobao_mtop.py、danmaku_listener/senders/pipeline.py、docs/ops/send-runbook.md
  - Verify: 根因卡附日志样例
  - **落地**：taobao_mtop 五阶段日志（launch/goto/topic/lib/eval，失败分支 warning 级）；pipeline detail[:200]；runbook 失败表补三行（sender 异常/页面未决/x5sec 信号）+ 周检命令修正（补 `--page-eval --room-url`，注明纯 HTTP 形态必败 RGV587）；sender/fence 17 测全绿
- [x] **T6 (P2, human: ~15min / CC: ~5min)** — 验收合规与时序检查项：ADR-002 自运营/受托房间前置检查 + 重登窗口避让，写入 runbook 清单 ✅ 2026-10-08 完成
  - Surfaced by: Section 3 / CEO-7
  - Files: docs/ops/send-runbook.md
  - Verify: 清单评审通过
  - **落地**：runbook QA 清单新增「前置检查（每平台验收前必过）」块——ADR-002 合规（自运营/受托房间、礼物禁止）+ 时序避让（重登窗口 busy 语义说明）
- [x] **T7 (P3, human: ~30min / CC: ~5min)** — DUPLICATE fix_hint 对账指引（管线守卫命中分支按 reason 细分 hint）✅ 2026-10-08 完成
  - Surfaced by: Section 4 / CEO-8
  - Files: danmaku_listener/senders/pipeline.py
  - Verify: 单测或手测回执文案
  - **落地**：守卫命中分支 hint 映射（DUPLICATE→指引 GET /api/send-results 对账，其余保持退避提示）；新增回归测试（同内容二连发→DUPLICATE+「对账」hint）；全量 643 passed
- [x] **T8 (P3, human: ~15min / CC: ~5min)** — TODOS.md 新增拼多多/美团发送接线条目（CEO-4 defer 落地）✅ 2026-10-08 完成
  - Surfaced by: NOT in scope / CEO-4
  - Files: TODOS.md
  - Verify: 条目含 What/Why/Effort/Depends
  - **落地**：条目已于 CEO 阶段落盘（TODOS.md「P3: 拼多多/美团弹幕发送接线」），字段齐全

<!-- autoplan-accepted:ceo -->
- CEO-1：TaobaoMtopSender 四阶段预算（goto/topic/lib/eval）合计 ≤55s，前端 60s 中止保持不变；预算以模块常量表达并被单测 tripwire 锁定。
- CEO-2：T2 修复动工前，T1 取证必须完成：send_audit.jsonl 失败尝试实际 status（sent/failed/none）+ 周检 replay 结果 + taobao.py 浏览器生命周期复核，写入根因卡。
- CEO-3：pipeline.py 唯一分发点对 sender.send 增加异常围栏，异常转 UNKNOWN SendResult 并落审计 result 行；TaobaoMtopSender 保留 ret 五路径映射并补 catch-all（回执语义不变）；两条路径均有单测。
- CEO-4：拼多多/美团发送接线 defer 至 TODOS.md，本战役不做。
- CEO-5：前端发送中止（AbortError）后对 /api/send-results?request_id= 做一次对账回显。
- CEO-6：sender 阶段日志（goto/topic/lib/eval 完成+耗时）、pipeline detail 截断放宽至 200、runbook 失败表补 busy/hang/对账三行。
- CEO-7：验收判据显式加入：仅自运营/受托直播间发送（ADR-002）、避开监听重登窗口时序。
- CEO-8：DUPLICATE 回执 hint 指引对账查询；app.js 60000 字面量提取为常量。
<!-- /autoplan-accepted:ceo -->

### Eng 阶段评审记录（/plan-eng-review 2026-10-08，FULL_REVIEW）

**Scope Challenge**：改动面 7 文件（<8）且 0 新类/服务 → 结构问题跳过；findings 裁定引用 CEO-1..8 账本（D1 授权自动裁定）+ 两项事实性澄清（不需批准）：① 围栏捕获异常时限速/去重窗口已被 record_attempt 占用——文档化为预期行为（AUTOlive 退避契约），测试断言一并锁定；② 预算收敛须同步 EVAL_SEND_JS 内嵌 `timeout:15000` 与 Python 常量两处，tripwire 只锁 Python 侧。结果：scope accepted as-is。

**Prior learning applied**: [douyin-send-resident-session]（9/10，2026-10-07）——瞬态窗口对淘宝的行为风控先例，常驻会话模式列为 PLAN B（不建，留触发条件）；[taobao-login-gate-design]（9/10）——per-profile 锁串行化语义即本计划 SPOF 分析依据。

**Section 1 架构**：No new issues found（CEO A1-A4 已裁定；分布架构=纯服务端+静态 webui，无 CI/CD 变更面）。历史回溯：taobao_mtop/pipeline 无 revert、无反复问题。
**Section 2 代码质量**：No new issues found（共享代码评估：围栏放管线唯一分发点=正确根因位；sender 间形态异构 API/DOM/mtop，强行提取=过早抽象，拒绝）。
**Section 3 测试**：框架=pytest（tests/unit/ 既有注入模式）。覆盖图：

```
CODE PATHS                                            USER FLOWS
[+] senders/pipeline.py                               [+] webui 行内发送
  ├── handle_request 守卫链 [★★★ TESTED 既有]           ├── [★★ TESTED?] token prompt→回执（runbook 手测清单）
  ├── record_attempt 占窗 [★★ TESTED]                   ├── [GAP] 慢页→60s 中止→对账回显（T4 后手测）
  ├── sender.send [GAP→围栏+单测 T2/T3]                 └── [GAP] 重登窗口期 busy 时序（T6 清单项）
  └── _finish 审计+广播 [★★ TESTED]                   [+] 错误状态
[+] senders/taobao_mtop.py                              ├── [★★★ TESTED] ret 五路径（9 单测）
  ├── _send_locked 四阶段 [GAP→tripwire T3]             ├── [GAP] launch 失败→结构化回执（T3）
  ├── ret 五路径 [★★★ TESTED 9/9]                       └── [GAP] DUPLICATE hint 对账指引（T7）
  └── 异常穿透 [GAP→围栏 T2]
COVERAGE: 6/12 paths tested (50%) | GAPS: 6（3 个由 T2/T3/T4 任务闭环，3 个为 runbook 手测项）
```

三条 Critical Path 均有 value card（见测试计划工件 `~/.gstack/projects/DanmakuListener/admin-main-eng-review-test-plan-20261008-100932.md`）。回归铁律：既有 9 测=ret 映射契约，T2 重构不得回退（全量 pytest 绿为验收门）。
**Section 4 性能**：No issues found（预算收敛后 p99≤55s；守卫 30s 间隔约束发送频次；无 DB/无循环查询）。

**Failure modes**（修复前现状）：2 CRITICAL GAPS（sender 异常→500 静默丢审计；前端中止后结果不可见）——均已有批准补救（T2 围栏、T4 对账轮询）并在 T3 断言锁定。
**并行化**：Sequential implementation, no parallelization opportunity（单模块簇 pipeline+taobao_mtop+app.js 强耦合）。
**外部声部**：codex unavailable（gpt-6-astra 400 InvalidParameter，两阶段同因；修复=GSTACK_CODEX_MODEL 或修 ~/.codex/config.toml）。
**Approval readiness: PASS**（CEO-1..8 全部引用 D1 路线 C 授权 + 账本记录；无未决 remedy）。
**任务 JSONL**：`~/.gstack/projects/DanmakuListener/tasks-eng-review-20261008-100932.jsonl`（8 条，T1-T8 权威版；CEO 阶段任务清单以计划 markdown 交付，聚合以本文件为准）。

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 7 | ISSUES OPEN | mode: HOLD_SCOPE, 2 critical gaps（发送异常穿透 500；前端中止后结果不可见）——补救已批准（T2/T4），待实施闭环 |
| Outside Review | codex（CEO+Eng 两阶段各一） | Independent 2nd opinion | 2 | UNAVAILABLE | gpt-6-astra 400 InvalidParameter（本机已知问题，修复=GSTACK_CODEX_MODEL 或修 ~/.codex/config.toml）；无完成的外部评审 |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 8 | ISSUES OPEN | 3 issues（3 条 Critical Path 测试面），2 critical gaps（同 CEO，补救已批准）；scope accepted as-is |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | SKIPPED | 无 UI scope（快照 scope 命中 1 < 阈值 2） |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | SKIPPED | 非开发者工具/非 AI 代理主用户（scope dxRequired=false） |

**OUTSIDE COVERAGE:** codex / plan-review（CEO+Eng 两阶段）/ unavailable（模型 400，无完成外部评审，不计 findings）。
**VERDICT:** CEO + ENG 均 ISSUES OPEN——缺陷已定位、补救与测试已批准规划（任务 T1-T3 闭环后复验）；eng gate 未过，实施后需复验。
**APPROVED:** 2026-10-08 最终批准门（D2）=A 按原样批准——T1-T8 任务与 8 项裁定全部生效，T1 取证诊断即可开工。

NO UNRESOLVED DECISIONS
