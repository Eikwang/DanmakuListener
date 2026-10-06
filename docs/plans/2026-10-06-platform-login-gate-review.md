<!-- /autoplan restore point: "C:\\Users\\admin\\.gstack\\projects\\DanmakuListener\\main-autoplan-restore-20261006-093146.md" -->
## Implementation plan
# Implementation plan：补齐平台登录门槛（添加直播间统一登录检测闭环）

## 问题陈述

用户实测发现：添加直播间时，部分平台不会检测登录状态、不会弹出登录页面。
要求审查十二平台的登录覆盖，完善**除美团外**缺失平台的登录逻辑
（美团无登录入口，用户裁定豁免）。

## 调查结论（2026-10-06 代码审查 + 2026-10-05 全量复测文档）

现有登录闭环分两层：
- **bridge 层**（`bridge._login_gate`，2026-10-05 三分支收口）：bilibili / kuaishou / douyin
  —— 添加直播间时检测 cookie 存在性，缺失则置 `login_required` 状态并弹登录窗口，登录后自动 start。
- **引擎层**（受控页面引擎自治）：pdd（cookie 值变化判定 → 可见窗口扫码 → 降级重登）、
  1688（unb cookie 判定 → 可见窗口登录）、wechat_channels（登录跳转检测 → NEEDS_LOGIN/可见窗口扫码）。

十二平台登录矩阵：

| 平台 | 登录需求（实测依据） | 现状 | 判定 |
| --- | --- | --- | --- |
| bilibili | 游客可收六类；登录可选增强 | ✅ bridge 层闭环 | 已覆盖 |
| kuaishou | 强制登录（游客拒绝推送） | ✅ bridge 层闭环 | 已覆盖 |
| douyin | 礼物只推登录观众 | ✅ bridge 层闭环 | 已覆盖 |
| pdd | 弹幕仅登录会话推送 | ✅ 引擎层闭环+降级重登 | 已覆盖 |
| 1688 | 聊天弹幕仅登录可见 | ✅ 引擎层闭环 | 已覆盖 |
| wechat_channels | 后台必须登录 | ✅ 引擎层 NEEDS_LOGIN 闭环 | 已覆盖 |
| **taobao** | **小号扫码**（测试计划与 1688/拼多多同组归类） | ❌ **无任何登录逻辑**——游客 profile 直接提凭证，失败只抛 `topic_failed`，无登录引导 | **缺口（必修）** |
| meituan | 无登录入口 | — | 用户裁定豁免 |
| douyu | 游客可收四类（TCP STT 直连，登录态无协议注入路径） | 无登录逻辑 | **用户裁定 B：实现检测+弹窗闭环**（登录态存文件备用） |
| huya | 游客可收三类（Tars 直连，登录态无协议注入路径） | 无登录逻辑 | **用户裁定 B：实现检测+弹窗闭环**（登录态存文件备用） |
| jd | 游客会话可收弹幕（实测注释） | 无登录逻辑 | **用户裁定 B：实现 1688 式登录闭环**（稳定性增强） |
| xiaohongshu | 观众侧无需登录（设备 cookie a1 自动种下） | 无登录逻辑 | **用户裁定 B：实现 1688 式登录闭环**（稳定性增强） |

## 变更方案

### 1. taobao 补登录闭环（必修，对齐 1688 引擎层模式）

`danmaku_listener/engines/protocol/taobao.py`：

- **登录判定**：新增 `_has_login_cookie(context)` —— 阿里系统一 `unb` cookie
  存在且有值（与 live1688.py 同判定；淘宝与 1688 同为阿里系账号体系）。
  **判定边界（spec 审查 1.1）**：unb 是账号标识而非会话令牌，仅用于**首次登录检测**
  （未登录 → 弹窗）；**不得**用于会话失效重登判定（pdd 2026-10-05 已实证
  cookie 存在性判定在会话作废场景失真并改用值变化检测）。
  `_wait_login_visible` 期间打登录后新增 cookie **名与变更布尔**日志（Eng F2 修订口径：
  pdd.py 真实形态只打名不打值——值仅用于判定；确需值时记 名称+长度+sha256 前 8 位掩码，
  unb 同样掩码），供后续收紧判定。
- **并发协调（Eng F1，切片 1 必修）**：persistent context 单实例——per-profile
  `asyncio.Lock` 登录协调器串行化全部 context 启动（无头提取与可见窗口互斥）；
  第二个待登录房间排队，轮到时**先重查 unb**（前一房间登录可能已覆盖，直接免弹窗）；
  **打开可见窗口前必须先关闭同房间无头 context**（1688 NeedLoginVisible 撕裂会话同款时序，
  live1688.py L233 先例）。
- **凭证阶段接入**：`_fetch_credentials` 打开页面后检测登录态；未登录 →
  可见窗口（headless=False）打开直播间页，emit 系统消息
  "淘宝直播间需要登录——已弹出浏览器，请登录淘宝/阿里账号（扫码）"，
  阻塞等待登录（unb 出现，超时 300s）→ 登录态入 persistent profile → 关窗回无头 → 继续提凭证。
  **超时策略（spec 审查 1.3 + 第 2 轮 C1 + Eng F3/F4/F8）**：同一房间累计 2 次超时后停止自动弹窗
  （首登与重登共用该预算），降级无头游客模式继续尝试（保持既有行为）+ ENGINE_STATUS 提示
  "登录未完成——已按游客模式尝试，可停止该房间后重新添加以再次触发登录窗口"；
  登录成功后超时计数清零。**等待循环每轮检查 _stop_flags**（Eng F3——用户停止房间立即
  关窗中断等待，不让窗口挂满 300s；pdd 现状无此检查，taobao 新流程必须有）；
  **捕获窗口关闭异常（TargetClosedError）按"用户直接关窗"分支处理**——计数+1 + 降级提示，
  不得冒泡成 topic_failed（Eng F4——否则预算永远不计）；
  **锁存键=room_id**（Eng F8——引擎实例跨房间共享，锁存不得吞掉其他房间的提示）；
  300s 登录等待与既有 attempt 等待档位（无头 45s/可见 240s，taobao.py L136）的嵌套关系：
  登录窗口是独立 deadline，不套用 240s 档位。
- **会话失效重登（三轮审查收敛，spike 驱动定型）**：淘宝降级会话的帧形态未实证，
  且两项候选证据已被 dump/pdd 实证排除——淘宝统计帧 ~4s 一帧恒在流（taobao_dump.jsonl
  21.3h/223 帧实证）、观看数=累计 UV（下播后仍 >0，onlineCount 恒 0，taobao.py 自校准），
  均不可作活跃/在播证据；pdd 实证（2026-10-05）：会话作废后 enter/notice 帧继续推送、
  弹幕/点赞停推——若淘宝同为 enter 存活型，"无业务消息"计数永不满足，触发器成死代码。
  因此：
  **T0 实施前置 spike（三臂实验；仅阻塞切片 2——切片合并门见下，CEO F8）**：
  **臂 1（guest 归因，CEO F2）**：全新 guest profile 首次提凭证，观测 topic_failed
  归因到底是登录门还是滑块门（taobao.py L122 注释自证滑块验证存在）——
  若为滑块门，登录窗流程需带滑块处理，且"必须登录"前提重审；
  **臂 2（降级帧形态）**：作废登录会话（手段按优先级：账号改密踢会话 > 服务端踢下线 >
  本地删 token cookie 模拟；任一手段成功即达成 spike，CEO F4），
  dump 观测哪些类停推/存活、统计帧行为、status==3 是否推送；
  **增补观测（Eng F5）：死会话+冷清房间+App 重启冷启动场景**——实证登录态会话即使冷清
  是否仍有 enter 心跳（若有，"启动 N 分钟零 enter"可作冷启动活性信号，消除触发器 (i)
  在冷启动死会话下的死代码形态）；
  **臂 3（游客 unb 存在性，CEO F3）**：日志确认全新 guest 态 unb 是否存在
  （若游客也种 unb，首登判定重设计）。
  三臂结论写入实现注释，触发器按臂 2 实测形态二选一定型：
  (i) **enter 存活型**（pdd 同构预期）：90s 证据窗口内"弹幕/礼物曾流入后完全静默，
  同时 enter/统计仍存活"→ 判定疑似降级 → **无头复验（自然复用下一重建轮），连续 2 个
  证据窗口命中才弹重登**（Eng F5——单窗口会把"曾活跃后自然冷场"误判降级抢焦点弹窗；
  连续 2 轮统一 (i)/(ii) 的计数语义）。业务帧证据门槛=窗口前弹幕/礼物曾流入，
  杜绝冷清房间误弹——统计帧不参与判定；
  (ii) **全停推型**：退化为重建轮失败计数器（连续 2 轮凭证重建后无任何帧 → 弹重登）。
  spike 同步确认下播帧形态（status==3 若推送则作为重登排除条件）。
  触发时把证据快照（窗口内各帧类计数）随日志/ENGINE_STATUS 带出（CEO F6——
  防对单次 spike 观测过拟合，帧律变化后可反推）。
  **切片合并门（CEO F8 + Eng F7 修订）**：**臂 1（guest 归因）先行且为切片 1 合并门**——
  若实证 topic_failed 主因是滑块门而非登录门，切片 1 前提重审（臂 1 成本近零）；
  切片 1 = 首登闭环 + registry 声明 + 文案 + 单测；切片 2 = 重登触发器，随臂 2 结论合入；
  臂 2/3 延期不阻塞切片 1（臂 1 通过后）。
  **预算与生命周期（CEO F5 修订）**：首登/重登共用每房间 2 次超时预算
  （用户直接关窗=超时一次），计数为**内存态，App 重启清零**（不持久化——
  重启后首个触发即自愈，杜绝"锁存一次后永久静默死亡"）；
  预算耗尽后 ENGINE_STATUS 提示**每引擎会话启动各提示一次**（不随触发刷屏）：
  "消息中断疑似登录过期——停止该房间后重新添加可重新触发登录窗口"；
  stop/重新添加清零全部计数；登录成功清零。
  重登可见窗口超时 300s（同首登），打开直播间页。重登判定用独立 90s 证据窗口观测，
  **不改动契约 O 的 30s last_msg_box 静默语义**（现有静默计时仍按任何 powermsg 帧刷新，
  消除双计时器歧义）。每轮记录登录 cookie 名+变更布尔日志（Eng F2 口径，不打值）。
- 失败路径改造：`topic_failed` 错误文案补充"未登录"分支指引
  （归因措辞以 spike 臂 1 结论为准）。
- **ENGINE_STATUS 登录生命周期事件词表（CEO F1）**：统一事件词（taobao 首用，
  后续平台复用）——`login.first_login` / `login.relogin_triggered` /
  `login.timeout_budget_exhausted` / `login.degraded_detected`；
  证据窗口实现为 taobao.py 内独立纯函数（可单测）；跨平台原语泛化 defer
  （第二个消费者出现时再抽取，P5 explicit）。
- **registry 声明（spec 审查 1.2 + Eng F9）**：`PLATFORM_WARNINGS` 补 taobao 条目
  "淘宝直播受控页面——需淘宝/阿里账号登录，首次添加自动弹登录窗口"；
  **一并补齐 1688 条目**（同为需登录引擎层平台却无警告条，一行成本消内部不一致）。

### 2. douyu / huya / jd / xiaohongshu 登录闭环（用户裁定 B，2026-10-06 批准门驳回收窄）

**用户权威裁定**：批准门 cycle 1 选择 B——驳回"游客可听不加弹窗"的收窄建议，
四平台按用户原话字面实现登录检测+弹窗。（审查的"实测游客可听"结论保留为事实记录：
- douyu/huya 为 TCP 协议直连，账号 cookie 无注入路径（登录态不进协议连接）；
- jd/xiaohongshu 为受控页面，实测游客会话可达协议边界——登录态作为稳定性增强。）

实现形态（分类）：
- **jd / xiaohongshu（受控页面，对齐 1688 模式）**：登录 cookie 判定
  （jd：pt_key/pt_pin 有值；xiaohongshu：web_session 有值）→ 未登录弹可见窗口
  打开直播间页 → 登录态入 persistent profile → 关窗回无头继续。
  共用预算/超时/stop 语义与 taobao 切片 1 一致（2 次内存态预算、300s 窗口、
  每轮检查 _stop_flags、TargetClosedError 按关窗分支）。
- **douyu / huya（TCP 直连，协议无注入路径）**：登录检测=cookie 文件登录态判定
  （douyu：dedeuserid 有值；huya：登录 cookie 判定——spike 期确认具体 cookie 名，
  初版用"cookie 文件存在且非空设备 ID 之外有登录态 cookie"宽判定+日志校准）→
  无登录态弹可见窗口打开网页版登录页（douyu: www.douyu.com/login；
  huya: www.huya.com）→ 用户登录后登录 cookie 存 cookie 文件 → 声明已登录。
  **诚实边界注释（写进实现与文档）**：登录态不进 TCP 协议连接（协议边界）——
  闭环价值=统一登录门槛 UX + 未来协议支持时 cookie 已就绪；
  消息增益依赖平台未来在协议层引入身份通道。
- registry.PLATFORM_WARNINGS：四平台条目改/补"支持账号登录增强——首次添加自动弹登录窗口"
  （jd/xiaohongshu 修订既有条目；douyu/huya 新增条目；taobao/1688 条目同批）。
- `docs/testing/full_platform_test_plan.md` 登录盘点表更新：四平台从"游客可测"
  改为"游客可测+登录增强闭环（2026-10-06 用户裁定）"，标注判定依据与**实测日期**（CEO F9）。

### 3. 前端透出确认（不新增功能，验证既有路径）

淘宝是引擎层登录平台：添加直播间返回 `success + running`（**不返回**
`login_required`——那是 bridge 层三分支 bilibili/kuaishou/douyin 的响应形状），
登录闭环在后台异步发生。验证链路（spec 审查 2.3 修正）：
添加淘宝直播间 → 添加成功（响应含 taobao 新警告条）→ 数秒内弹可见登录窗口
+ ENGINE_STATUS 系统消息（前端 alert 区渲染）→ 登录后自动开始监听。

## 测试计划

- 单测（tests/unit/test_taobao_protocol.py 扩展，判定逻辑仿 pdd 纯函数模式）：
  `_has_login_cookie` 判定（unb 有/无/空值）、登录等待超时路径、超时 2 次后降级不弹窗、
  预算耗尽 ENGINE_STATUS 锁存一次不刷屏、stop/重新添加清零计数、直接关窗=超时一次、
  enter 存活型窗口判定（弹幕/礼物曾流入→静默+enter/统计存活→触发）、
  业务帧从未流入的冷清房间不触发（统计在流不算证据）、全停推型重建计数触发、
  登录成功后计数清零。
- **T0 spike（三臂，实施前置；仅阻塞切片 2）**：臂 1 guest 归因 + 臂 2 作废会话帧形态 +
  臂 3 游客 unb 存在性 → 定型触发器分支 (i)/(ii) → 实测形态沉淀为回归用例。
- 实测（需用户配合，切片 1）：清除/备份 taobao_profile 后添加淘宝直播间 → 弹可见窗口 →
  扫码登录 → 自动开始监听。
- 实测（需用户配合，切片 2）：监听中手动作废登录会话 → 按 spike 定型的触发器 →
  自动弹窗重登。
- 回归：`python -m pytest tests/ -q` —— 以实施当日 `pytest --collect-only` 数为基线，
  只增不减（spec 审查 3.1：硬编码基线已过时，不再引用固定数字）。

## NOT in scope

- 已 defer 至 TODOS.md（0G 决议 #4，2026-10-06）：登录健康度面板（前端 UI）；
  登录超时重试按钮；cookie 目录 README。
- 美团登录（用户裁定：无登录入口，不需要登录）。
- 斗鱼/虎牙协议级 cookie 注入（协议无此通道——弹窗闭环已按用户裁定实现，登录态存
  cookie 文件备用；让登录态真正影响消息流需平台协议支持，非本次可解）。
- 战略备忘 defer（CEO F10）：前端内嵌二维码替代 OS 弹窗（与 0G#4 面板同址）；
  淘宝开放平台/官方弹幕通道评估（长线抗风控正道）。
- 部署声明（CEO F7，实施时写入部署文档）：taobao/pdd/1688 登录事件需 attended 会话；
  无人值守场景依赖游客降级 + ENGINE_STATUS（路径已有）。

## What already exists

- 登录窗口基建：bilibili_login.py / kuaishou_login.py / douyin_login.py（可见窗口+cookie 判定+超时降级）。
- 引擎层登录闭环参考实现：live1688.py `_has_login_cookie`/`_wait_login_visible`（阿里系同源，直接对齐）。
- 前端 login_required / NEEDS_LOGIN / ENGINE_STATUS 三条透出通道全部就绪。
- 拼多多降级检测（`is_degraded_window`）作为会话失效重登的参考语义。


<!-- autoplan-accepted:ceo -->
- taobao 登录闭环放引擎层（taobao.py 内部，对齐 live1688 模式）：首次登录检测 `_has_login_cookie`（unb cookie 存在且有值，仅用于首登——不得用于会话失效判定，pdd 2026-10-05 已实证存在性判定失真）→ 未登录弹可见窗口 `_wait_login_visible`（超时 300s，登录后新增 cookie 名与值变化全量打日志，pdd.py 同款）→ 登录态入 persistent profile → 关窗回无头 → 重提凭证。超时策略：同房间累计 2 次超时后停止自动弹窗，降级无头游客尝试 + ENGINE_STATUS 提示可停止重加以再触发。
- 会话失效重登（spike 驱动定型，三轮审查收敛）：淘宝降级帧形态未实证且统计帧（~4s 一帧恒在流）/观看数（累计 UV，下播后>0）已被实证排除出证据体系——T0 实施前置 spike（blocking）：作废会话实测降级帧形态，定型触发器：(i) enter 存活型（pdd 同构）→ 90s 证据窗口"弹幕/礼物曾流入后静默+enter/统计存活"判定（业务帧证据门槛防冷清误弹，统计不参与）；(ii) 全停推型 → 连续 2 轮重建失败计数；spike 同步确认 status==3 下播帧形态（推送则作排除条件）。首登/重登共用每房间 2 次超时预算（关窗=超时一次），耗尽后 ENGINE_STATUS 锁存提示一次不刷屏；stop/重新添加清零计数，登录成功清零；重登窗口 300s 打开直播间页；重登判定用独立 90s 证据窗口，不改动契约 O 的 30s last_msg_box 语义。单测覆盖：判定三分支 + 超时降级 + 两型触发器 + 冷清不触发 + 预算锁存 + 关窗语义 + 成功清零 + spike 形态回归。
- taobao `topic_failed` 错误文案补"未登录"分支指引；registry.PLATFORM_WARNINGS 补 taobao 条目（需登录，首次添加自动弹登录窗口）。
- douyu/huya/jd/xiaohongshu 登录策略声明：registry.PLATFORM_WARNINGS 中 huya/jd/xiaohongshu 修订既有条目追加"游客可听，无需登录"、douyu 新增条目；docs/testing/full_platform_test_plan.md 盘点表标注判定依据。（对用户原话的收窄——User Challenge 排队至 Phase 4，未裁定前按此实施并保留原需求记录）
- meituan 登录豁免（用户原话裁定：无登录入口，不需要登录）。
- 契约 v1 消息形状不变；登录等待仅新增 ENGINE_STATUS 系统消息与可见窗口行为。taobao 为引擎层平台：添加返回 running，登录后台异步（不返回 login_required——bridge 层三分支专属形状）。
- 回归基线：以实施当日 pytest --collect-only 数为基线只增不减（不引用固定数字）。
- CEO 声部发现收口（2026-10-06，单声部——Codex unavailable）：spike 扩为三臂（臂 1 guest 归因：topic_failed 可能是滑块门；臂 2 作废会话帧形态；臂 3 游客 unb 存在性——CEO F2/F3/F4）；预算计数内存态 + App 重启清零 + 锁存改每引擎会话启动各提示一次（F5，杜绝锁存后永久静默死亡）；切片合并门——切片 1（首登闭环+registry+文案+单测）先行合入，切片 2（重登触发器）随 spike，spike 延期不阻塞切片 1（F8）；触发时证据快照（窗口内帧类计数）随日志带出（F6）；ENGINE_STATUS 登录生命周期事件词表 4 常量 + 证据窗口独立纯函数、跨平台泛化 defer（F1）；盘点表声明带实测日期（F9）；attended 部署声明 + 战略备忘 defer（F7/F10）；登录弹窗文案中性化（F2——归因未实证前不把推断发给终端用户）。
<!-- /autoplan-accepted:ceo -->

<!-- autoplan-accepted:eng -->
- taobao 切片 1 必修并发协调（Eng F1）：per-profile asyncio.Lock 串行化全部 context 启动；第二待登录房间排队且轮到先重查 unb；开可见窗前先关同房间无头 context（1688 NeedLoginVisible 同款时序）。验证：双房间并发添加实测 + 单测锁时序。
- 日志口径（F2）：登录 cookie 只打名+变更布尔，不打值；确需值用 名称+长度+sha256 前 8 位掩码（unb 同）。
- stop 语义（F3）：登录等待循环每轮检查 _stop_flags，命中立即关窗退出；补 stop 中断单测。
- 关窗异常（F4）：捕获 TargetClosedError 按"用户关窗"分支（计数+1+降级提示），不冒泡 topic_failed。
- 触发器计数统一（F5）：连续 2 个 90s 证据窗口命中才弹重登（第一窗口命中后的重建轮即无头复验）；spike 臂 2 增补死会话+冷清+重启冷启动观测。
- 测试 seam（F6）：等待循环时钟（monotonic）与 cookie 读取抽象为可注入参数；补响应形状断言（success+running 绝不含 login_required）、契约 O 30s last_msg_box 不变回归、stop 中断三用例。
- 切片合并门修订（F7）：臂 1 先行且为切片 1 合并门（topic_failed 主因若是滑块门则前提重审）。
- 锁存键=room_id（F8）；登录等待为独立 deadline 不套 240s 档位。
- registry 一并补 1688 警告条（F9，消"需登录平台必有警告条"内部不一致）。
- **用户权威裁定（批准门 cycle 1，2026-10-06 选 B）**：驳回"四平台游客可听不加弹窗"收窄——douyu/huya/jd/xiaohongshu 按用户原话字面实现登录检测+弹窗闭环：jd/xiaohongshu 对齐 1688 模式（jd：pt_key/pt_pin 有值；xiaohongshu：web_session 有值→可见窗口→persistent profile）；douyu/huya cookie 文件登录态检测（douyu：dedeuserid 有值；huya：登录 cookie 名 spike 期确认，初版宽判定+日志校准）+弹网页登录页（douyu: www.douyu.com/login；huya: www.huya.com），登录态存 cookie 文件（诚实边界注释：不进 TCP 协议连接）；registry 四条目改"登录增强，首次添加自动弹登录窗口"；测试文档同步更新。审查的"游客可听"实测结论保留为事实记录。
<!-- /autoplan-accepted:eng -->
## Review record

## Sections 1-11 审查记录（CEO Phase，SELECTIVE EXPANSION）

**Section 1: Architecture Review** — 变更集中在 taobao.py 单文件（登录闭环 3 函数 + 状态计数器）+ registry 声明。架构图：
```
add_room(taobao) ──> bridge.start ──> engine.start(room)
                                          │
                                          v
                                   _run_room 循环
                     ┌────────────────────┴──────────────────┐
                     v                                       v
            _fetch_credentials（每轮）                 mtop 轮询监听
                     │                                       │
              _has_login_cookie?                     30s 无消息（契约 O）
              ├─ 有 ─> 提凭证 ─> 监听                        │
              └─ 无 ─> _wait_login_visible（≤300s）    整轮重建 ──┐
                       │ 登录/超时                            │
                       v                                     v
              预算(2,内存态)耗尽? ─ 否 ─> 弹窗循环       90s 证据窗口(spike 定型)
                       └─ 是 ─> 游客降级+每会话一次提示      └─ 降级 ─> 重登弹窗（共用预算）
```
数据流四路径：Happy（有 cookie 直接跑）/ Nil（unb 缺失→弹窗）/ Empty（unb 空值→视为未登录）/ Error（topic_failed→未登录分支文案+backoff）。耦合：无新增模块间耦合（引擎自治）；单点失败=taobao_profile 损坏（现状已存在，非本次引入，runbook 覆盖）。裁定：**OK，无新 finding**——凭证阶段开浏览器的拓扑是既有模式（1688 同款），登录窗口与无头会话互斥已由 persistent context 单实例保证（0I HOUR 4-5 已分析）。

**Section 2: Error & Rescue Map** — 新增 codepath 错误清单：
```
METHOD/CODEPATH            | WHAT CAN GO WRONG           | EXCEPTION CLASS
_has_login_cookie          | context.cookies() 抛异常     | playwright Error
_wait_login_visible        | 用户 300s 未登录/直接关窗     | TimeoutError(内部信号)
登录窗口期间 context 并发   | persistent context 单实例冲突 | playwright Error
预算耗尽后触发器            | 计数溢出/类型错误            | 逻辑 bug
spike 阻塞切片 2            | 手段全部失败                 | 实验失败
EXCEPTION CLASS      | RESCUED? | RESCUE ACTION                | USER SEES
playwright Error     | Y        | try/except 返回 False→按未登录| 正常弹窗路径
TimeoutError         | Y        | 计入预算→降级游客+ENGINE_STATUS | 降级提示
context 并发冲突      | Y        | NeedLoginVisible 式信号中断会话 | 窗口打开
spike 失败            | Y        | 切片 1 照常交付（合并门）        | 无感知
```
无 catch-all；每条救援有用户可见信号。裁定：**OK**。C3（第 3 轮）已把预算耗尽改"每会话一次提示"，消除永久静默。

**Section 3: Security & Threat Model** — 新攻击面评估：登录窗口打开的是直播间公开页（非敏感页）；cookie 全量日志（pdd 同款）可能把登录 cookie 值写进日志——**WARNING**：日志级别须为 debug 且不得含完整 value（对齐 pdd 现有做法的实际风险面——pdd 打印的是 name 集合与新 cookie 名，非 value 全文；淘宝实现保持同口径：记录 name 与"是否变化"，value 打码）。裁定：**接受并落为实施约束**（写进 accepted 义务的日志口径）。无新端点、无 PII 新流向。

**Section 4: Data Flow & Interaction Edge Cases** — 状态机（预算计数器）：
```
[新房间] --添加--> budget=2, degraded=0
  --登录超时--> budget=1 --再超时--> budget=0 --> 锁存提示(每会话)
  --登录成功--> budget=2（清零）
  --spike定型触发器判定降级--> 弹重登（消耗预算同上）
  --stop/重新添加--> 全部清零
  --App 重启--> 内存态清零
```
异步序：登录窗口任务与轮询任务的竞争由"凭证阶段串行"消除（每轮 _fetch_credentials 内联等待，无并发 await 交叉）； ENGINE_STATUS 与窗口打开的顺序（先 emit 再开窗，前端先见提示）在实现时保持。边界：双击添加（bridge 重复检查 409 已有）、重启恢复（stopped→手动 start 走同一路径）。裁定：**OK**。

**Section 5: Code Quality Review** — 判定/等待/触发器实现为独立纯函数（accepted 义务已载明），复用 live1688/pdd 模式无重复抽象（P4：不预抽跨平台原语）。命名直白（_has_login_cookie/_wait_login_visible 与 1688 同名同义）。裁定：**OK**。

**Section 6: Test Review** — 测试图（新增 codepath→测试类型）：判定三分支（单测）/超时降级（单测）/预算生命周期（单测）/两型触发器（单测，参数化帧律——CEO F6）/spike 形态回归（集成）/全链路（用户实测）。2am Friday 测试=预算耗尽降级不弹窗；敌意 QA=统计帧恒流+业务帧从未流入的冷清房间；混沌=登录窗口期间杀浏览器进程（context 关闭→按超时处理）。回归基线动态（只增不减）。裁定：**OK，测试清单已闭合**。

**Section 7: Performance Review** — 90s 证据窗口为内存计数（帧分类计数器，O(1)/帧）；登录窗口期间轮询暂停（可接受——该房间本来无消息）；无 N+1/新连接池压力。裁定：**OK**。

**Section 8: Observability & Debuggability** — ENGINE_STATUS 生命周期词表 4 常量（F1）+ cookie 变化日志（S3 打码口径）+ 触发时证据快照（F6）。三周后可从日志重建：何时弹窗、为何判定降级、预算消耗轨迹。裁定：**OK**（词表让 0G#4 健康面板有直接数据源）。

**Section 9: Deployment & Rollout Review** — 切片合并门（F8）：切片 1 独立交付，切片 2 随 spike；回滚=引擎独立文件，revert 单文件即回退；attended 部署声明（F7）写入部署文档。裁定：**OK**。

**Section 10: Long-Term Trajectory Review** — 技术债：spike 结论依赖帧律（F6 证据快照对冲）；路径依赖：无（taobao 模块独立）；可逆性 5/5（新增代码不改动既有契约 O 语义）；词表为后续平台登录统一铺路（F1 的 10x 支点）。裁定：**OK**。

**Section 11: Design & UX** — SKIPPED（无 UI scope；快照 scope matchCount=0）。


## Eng Phase 审查记录（SELECTIVE EXPANSION 延续，MODE=FULL_REVIEW）

**Step 0 Scope Challenge**：子问题全映射既有代码（1688 判定/窗口、pdd 降级语义与日志、bridge 门槛、_emit_system_status）。复杂度：5 文件 / 0 新类 → 跳过 B。发现 3 项：
- [P2] (8/10) taobao.py:369 last_msg_box 语义迁移风险 → 已由 accepted 义务"独立 90s 证据窗口、不改动契约 O"收口。Dispositions: accepted（既有约束）。
- [P2] (7/10) registry.py:46-66 声明无消费方校验、可漂移 → F9 实测日期戳对冲，自动探测 defer（0G#4）。Dispositions: accepted（声明性+对冲）。
- [P3] (6/10) bridge.py:539 重复检查与逃生路径核查 → stop 后 stopped 状态可重加 ✓ 无缺口。Dispositions: rejected（无变更）。
结果：**scope accepted as-is**。

**Sections 1-4**：
1. Architecture：3 个生产失败场景（风控拦截可见浏览器→臂 1 实证+中性文案兜底；context 被外部杀→按超时预算处理；登录后仍无消息→业务帧门槛不满足不误弹+日志可反推）全有处理。分布检查：无新 artifact。0 issues。
2. Code Quality：DRY rubric——淘宝/1688 同构判定，消费者=1 且跨引擎层级（ControlledPageEngine vs BaseEngine），提取共享 helper 收益<抽象成本 → 不提取（对齐 CEO F1 defer）。命名与 1688 同名同义。0 issues。
3. Test Review：pytest 框架（tests/ 动态基线）。测试图 13 路径全 GAP（计划新增代码）——11 单测/spike 回归 + 2 实测；测试计划 artifact 已写盘（admin-main-eng-review-test-plan-20261006-104740.md）。无 LLM/eval 路径。无既有测试过时。
4. Performance：90s 证据窗口 O(1)/帧内存计数；登录窗口期间该房间轮询暂停（本无消息）；cookie 判定 O(n) 每凭证轮一次。0 issues。

**ENG DUAL VOICES — CONSENSUS TABLE**

```
  Dimension                           Claude  Codex  Consensus
  1. Architecture sound?               是(F1高必修) N/A  N/A (outside unavailable)
  2. Test coverage sufficient?         是(F6补seam) N/A N/A
  3. Performance risks addressed?      是      N/A    N/A
  4. Security threats covered?         是(F2修口径) N/A N/A
  5. Error paths handled?              是(F3/F4) N/A  N/A
  6. Deployment risk manageable?       是(切片门) N/A N/A
```
Codex 两次调用均失败（gpt-6-astra 模型 400 InvalidParameter）——outside_status: unavailable，六格 N/A 永不 CONFIRMED。单声部 critical 一票否决制。

## Eng Implementation Tasks
Synthesized from this review's findings. Run with Claude Code or Codex; checkbox as you ship.

- [ ] **T1 (P1, human: ~3h / CC: ~20min)** — taobao 引擎 — 切片 1 首登闭环（判定+可见窗口+预算内存态+词表 4 常量+中性文案）
  - Surfaced by: 计划 §1 + CEO F2/F5 + Eng S2（last_msg_box 解耦约束）
  - Files: danmaku_listener/engines/protocol/taobao.py
  - Verify: python -m pytest tests/unit/test_taobao_protocol.py -q（新增用例全绿）+ 实测清 profile 添加→弹窗→扫码→自动监听
- [ ] **T2 (P1, human: ~30min / CC: ~5min)** — registry — taobao 警告条新增 + 四平台"游客可听，无需登录"声明（修订 3/新增 1）
  - Surfaced by: 计划 §2 + spec 1.2
  - Files: danmaku_listener/engines/registry.py
  - Verify: python -c "from danmaku_listener.engines.registry import PLATFORM_WARNINGS; assert 'taobao' in PLATFORM_WARNINGS and 'douyu' in PLATFORM_WARNINGS"
- [ ] **T3 (P1, human: ~15min / CC: ~5min)** — 测试文档 — 登录盘点表标注判定依据+实测日期
  - Surfaced by: 计划 §2 + CEO F9
  - Files: docs/testing/full_platform_test_plan.md
  - Verify: 人工核对表内日期与声明一一对应
- [ ] **T4 (P1, human: ~2h / CC: ~15min)** — 单测 — 切片 1 判定三分支/超时降级/预算生命周期
  - Surfaced by: Eng S3 测试图（11 GAP 中的切片 1 部分）
  - Files: tests/unit/test_taobao_protocol.py
  - Verify: python -m pytest tests/unit/test_taobao_protocol.py -q
- [ ] **T5 (P2, human: ~1h / CC: ~20min)** — spike — 三臂实验脚本+结论写入实现注释（前置切片 2）
  - Surfaced by: 计划 §1 T0 spike（CEO F2/F3/F4）
  - Files: tools/（临时脚本）、taobao.py（注释）
  - Verify: spike 三臂结论落档；任一作废手段成功即达成
- [ ] **T6 (P2, human: ~2h / CC: ~30min)** — taobao 引擎 — 切片 2 重登触发器（spike 定型分支）+ 冷清不触发用例
  - Surfaced by: 计划 §1 spike 分支 (i)/(ii) + Eng S3 测试图
  - Files: danmaku_listener/engines/protocol/taobao.py、tests/unit/test_taobao_protocol.py
  - Verify: 实测作废会话→触发器→自动弹窗重登；参数化帧律回归
- [ ] **T7 (P3, human: ~15min / CC: ~5min)** — 部署文档 — attended 会话声明（taobao/pdd/1688 登录事件需人在场）
  - Surfaced by: CEO F7
  - Files: docs/advanced.md（或部署相关文档）
  - Verify: 文档含无人值守降级行为说明

顺序实施（单主模块 taobao.py），无并行化机会。T5→T6 依赖；其余独立。

## Eng Failure Modes Registry

```
CODEPATH                | FAILURE MODE            | RESCUED? | TEST? | USER SEES?      | LOGGED?
首登判定                | 游客误有 unb（臂 3）     | Y(实证)  | Y     | 中性文案弹窗     | Y
登录窗口                | 超时/关窗/被杀           | Y        | Y     | 降级提示         | Y
重登触发器              | 帧律漂移/冷清误弹        | Y        | Y     | 证据快照提示     | Y
预算生命周期            | 永久静默（已修 F5）      | Y        | Y     | 每会话一次提示   | Y
spike                   | 作废手段全失败           | Y(切片门)| N/A   | 切片 1 照常交付  | Y
契约 O 静默计时          | 双计时器歧义            | Y(解耦)  | Y     | 无感知           | Y
```
CRITICAL GAPS: 0。

## Eng Completion summary
- Step 0: Scope Challenge — scope accepted as-is
- Architecture Review: 0 issues found
- Code Quality Review: 0 issues found（1 提取裁定：不提取）
- Test Review: diagram produced, 13 gaps identified（11 单测/spike 回归 + 2 实测，全部为计划新增路径）
- Performance Review: 0 issues found
- NOT in scope: written（6 项）
- What already exists: written
- TODOS.md updates: 5 items（已自动写入 TODOS.md）
- Failure modes: 0 critical gaps flagged
- Unresolved decisions: 0（User Challenge 归 Phase 4 批准门，非本阶段决策）
- Outside voice: codex unavailable（gpt-6-astra 模型 400，两次）
- Parallelization: sequential（单主模块，无并行化机会）
- Lake Score: N/A（0 个覆盖型 0D 选择）

## CEO DUAL VOICES — CONSENSUS TABLE

```
  Dimension                             Claude  Codex   Consensus
  1. Premises valid?                    复核属实  N/A     N/A (outside unavailable)
  2. Right problem to solve?            是+泛化建议 N/A    N/A
  3. Scope calibration correct?         正确     N/A      N/A
  4. Alternatives sufficiently explored? 切片建议  N/A     N/A
  5. Competitive/market risks covered?  平台反制  N/A     N/A
  6. 6-month trajectory sound?          词表铺路  N/A     N/A
```
Codex 外部声部 unavailable（gpt-6-astra 模型 400）——六格 N/A，永不标 CONFIRMED。Claude 声部无 critical，2 high（F2/F5）已收口。**[subagent-only]** 标记。

## Failure Modes Registry

```
CODEPATH                    | FAILURE MODE           | RESCUED? | TEST? | USER SEES?        | LOGGED?
首登判定                     | unb 误判（游客有 unb）   | Y(臂3实证)| Y    | 弹窗异常→中性文案  | Y
登录窗口                     | 300s 超时/关窗          | Y        | Y    | 降级提示           | Y
预算耗尽                     | 永久静默（已修）         | Y(F5)    | Y    | 每会话一次提示     | Y
重登触发器                   | 帧律漂移失效            | Y(F6快照) | Y(参数化)| ENGINE_STATUS  | Y
spike                       | 手段全失败              | Y(F8切片) | N/A  | 切片1照常交付      | Y
topic_failed 归因错误        | 滑块门误报未登录         | Y(臂1)   | Y    | 中性文案+重审前提  | Y
```
CRITICAL GAPS：0（全部 RESCUED=Y 且 USER SEES 非 Silent）。

## Dream state delta

CURRENT（7 平台有登录闭环、淘宝靠幸运 cookie）→ THIS PLAN（12/12 登录策略全覆盖：11 平台闭环/声明 + 美团豁免；新部署从零可自助；登录生命周期可观测）→ 12-MONTH IDEAL（平台接入=协议+登录策略两接口；健康度面板；全平台会话失效自动恢复）。本计划把"新平台接入的登录维度"从逐个考古变成词表+证据窗口原语可复用的起点（delta 的 60%——原语泛化待第二个消费者）。

## Completion Summary

```
  +====================================================================+
  |            MEGA PLAN REVIEW — COMPLETION SUMMARY                   |
  +====================================================================+
  | Mode selected        | SELECTIVE EXPANSION（autoplan 指定）         |
  | System Audit         | 登录矩阵全查：7 有闭环/1 缺口/3 免声明/1 豁免 |
  | Step 0               | SELECTIVE EXPANSION；4+6 项 0D 裁定          |
  | Section 1  (Arch)    | 0 issues（拓扑为既有模式）                    |
  | Section 2  (Errors)  | 5 error paths mapped, 0 GAPS                 |
  | Section 3  (Security)| 1 WARNING（cookie 日志打码口径）→ 已落约束    |
  | Section 4  (Data/UX) | 状态机 1 张，0 unhandled                      |
  | Section 5  (Quality) | 0 issues（纯函数+复用模式）                   |
  | Section 6  (Tests)   | 清单闭合，spike 形态回归补齐                  |
  | Section 7  (Perf)    | 0 issues                                     |
  | Section 8  (Observ)  | 词表+快照+日志（0G#4 数据源就绪）             |
  | Section 9  (Deploy)  | 切片合并门+attended 声明                      |
  | Section 10 (Future)  | Reversibility: 5/5, debt items: 0            |
  | Section 11 (Design)  | SKIPPED（no UI scope）                       |
  +--------------------------------------------------------------------+
  | NOT in scope         | written（6 items）                           |
  | What already exists  | written                                     |
  | Dream state delta    | written                                     |
  | Error/rescue registry| 5 rows, 0 CRITICAL GAPS                     |
  | Failure modes        | 6 total, 0 CRITICAL GAPS                    |
  | TODOS.md updates     | 5 items（实施时补记）                        |
  | Scope proposals      | 4 proposed, 3 accepted, 1 deferred          |
  | CEO plan             | written（本文件 Review record）              |
  | Outside voice        | codex unavailable（模型 400）→ subagent-only |
  | Lake Score           | N/A（0 个覆盖型 0D 选择）                    |
  | Diagrams produced    | 3（架构/状态机/登录闭环流）                   |
  | Stale diagrams found | 0                                           |
  | Unresolved decisions | 1（User Challenge——见 Phase 4 批准门）       |
  +====================================================================+
```

**Unresolved Decisions**：User Challenge 1 项（douyu/huya/jd/xiaohongshu 登录策略收窄）呈报 Final Approval Gate。

<!-- autoplan-accepted:ceo -->
- taobao 登录闭环放引擎层（taobao.py 内部，对齐 live1688 模式）：首次登录检测 `_has_login_cookie`（unb cookie 存在且有值，仅用于首登——不得用于会话失效判定，pdd 2026-10-05 已实证存在性判定失真）→ 未登录弹可见窗口 `_wait_login_visible`（超时 300s，登录后新增 cookie 名与值变化全量打日志，pdd.py 同款）→ 登录态入 persistent profile → 关窗回无头 → 重提凭证。超时策略：同房间累计 2 次超时后停止自动弹窗，降级无头游客尝试 + ENGINE_STATUS 提示可停止重加以再触发。
- 会话失效重登（spike 驱动定型，三轮审查收敛）：淘宝降级帧形态未实证且统计帧（~4s 一帧恒在流）/观看数（累计 UV，下播后>0）已被实证排除出证据体系——T0 实施前置 spike（blocking）：作废会话实测降级帧形态，定型触发器：(i) enter 存活型（pdd 同构）→ 90s 证据窗口"弹幕/礼物曾流入后静默+enter/统计存活"判定（业务帧证据门槛防冷清误弹，统计不参与）；(ii) 全停推型 → 连续 2 轮重建失败计数；spike 同步确认 status==3 下播帧形态（推送则作排除条件）。首登/重登共用每房间 2 次超时预算（关窗=超时一次），耗尽后 ENGINE_STATUS 锁存提示一次不刷屏；stop/重新添加清零计数，登录成功清零；重登窗口 300s 打开直播间页；重登判定用独立 90s 证据窗口，不改动契约 O 的 30s last_msg_box 语义。单测覆盖：判定三分支 + 超时降级 + 两型触发器 + 冷清不触发 + 预算锁存 + 关窗语义 + 成功清零 + spike 形态回归。
- taobao `topic_failed` 错误文案补"未登录"分支指引；registry.PLATFORM_WARNINGS 补 taobao 条目（需登录，首次添加自动弹登录窗口）。
- douyu/huya/jd/xiaohongshu 登录策略声明：registry.PLATFORM_WARNINGS 中 huya/jd/xiaohongshu 修订既有条目追加"游客可听，无需登录"、douyu 新增条目；docs/testing/full_platform_test_plan.md 盘点表标注判定依据。（对用户原话的收窄——User Challenge 排队至 Phase 4，未裁定前按此实施并保留原需求记录）
- meituan 登录豁免（用户原话裁定：无登录入口，不需要登录）。
- 契约 v1 消息形状不变；登录等待仅新增 ENGINE_STATUS 系统消息与可见窗口行为。taobao 为引擎层平台：添加返回 running，登录后台异步（不返回 login_required——bridge 层三分支专属形状）。
- 回归基线：以实施当日 pytest --collect-only 数为基线只增不减（不引用固定数字）。
- CEO 声部发现收口（2026-10-06，单声部——Codex unavailable）：spike 扩为三臂（臂 1 guest 归因：topic_failed 可能是滑块门；臂 2 作废会话帧形态；臂 3 游客 unb 存在性——CEO F2/F3/F4）；预算计数内存态 + App 重启清零 + 锁存改每引擎会话启动各提示一次（F5，杜绝锁存后永久静默死亡）；切片合并门——切片 1（首登闭环+registry+文案+单测）先行合入，切片 2（重登触发器）随 spike，spike 延期不阻塞切片 1（F8）；触发时证据快照（窗口内帧类计数）随日志带出（F6）；ENGINE_STATUS 登录生命周期事件词表 4 常量 + 证据窗口独立纯函数、跨平台泛化 defer（F1）；盘点表声明带实测日期（F9）；attended 部署声明 + 战略备忘 defer（F7/F10）；登录弹窗文案中性化（F2——归因未实证前不把推断发给终端用户）。
<!-- /autoplan-accepted:ceo -->

<!-- autoplan-accepted:eng -->
- taobao 切片 1 必修并发协调（Eng F1）：per-profile asyncio.Lock 串行化全部 context 启动；第二待登录房间排队且轮到先重查 unb；开可见窗前先关同房间无头 context（1688 NeedLoginVisible 同款时序）。验证：双房间并发添加实测 + 单测锁时序。
- 日志口径（F2）：登录 cookie 只打名+变更布尔，不打值；确需值用 名称+长度+sha256 前 8 位掩码（unb 同）。
- stop 语义（F3）：登录等待循环每轮检查 _stop_flags，命中立即关窗退出；补 stop 中断单测。
- 关窗异常（F4）：捕获 TargetClosedError 按"用户关窗"分支（计数+1+降级提示），不冒泡 topic_failed。
- 触发器计数统一（F5）：连续 2 个 90s 证据窗口命中才弹重登（第一窗口命中后的重建轮即无头复验）；spike 臂 2 增补死会话+冷清+重启冷启动观测。
- 测试 seam（F6）：等待循环时钟（monotonic）与 cookie 读取抽象为可注入参数；补响应形状断言（success+running 绝不含 login_required）、契约 O 30s last_msg_box 不变回归、stop 中断三用例。
- 切片合并门修订（F7）：臂 1 先行且为切片 1 合并门（topic_failed 主因若是滑块门则前提重审）。
- 锁存键=room_id（F8）；登录等待为独立 deadline 不套 240s 档位。
- registry 一并补 1688 警告条（F9，消"需登录平台必有警告条"内部不一致）。
- **用户权威裁定（批准门 cycle 1，2026-10-06 选 B）**：驳回"四平台游客可听不加弹窗"收窄——douyu/huya/jd/xiaohongshu 按用户原话字面实现登录检测+弹窗闭环：jd/xiaohongshu 对齐 1688 模式（jd：pt_key/pt_pin 有值；xiaohongshu：web_session 有值→可见窗口→persistent profile）；douyu/huya cookie 文件登录态检测（douyu：dedeuserid 有值；huya：登录 cookie 名 spike 期确认，初版宽判定+日志校准）+弹网页登录页（douyu: www.douyu.com/login；huya: www.huya.com），登录态存 cookie 文件（诚实边界注释：不进 TCP 协议连接）；registry 四条目改"登录增强，首次添加自动弹登录窗口"；测试文档同步更新。审查的"游客可听"实测结论保留为事实记录。
<!-- /autoplan-accepted:eng -->
<!-- autoplan-baseline-edits:eng {"sourceSha256":"b01d5ef911a9cf2eec7a1bd7e2aac2e7cbbbdd0ec90d53c16a22f6f57842454f","replacements":[{"oldText":"  `_wait_login_visible` 期间把登录后新增 cookie 名与值变化全部打日志\n  （pdd.py `_wait_login_visible` 同款做法，非 1688——1688 无此日志），供后续收紧判定。","newText":"  `_wait_login_visible` 期间打登录后新增 cookie **名与变更布尔**日志（Eng F2 修订口径：\n  pdd.py 真实形态只打名不打值——值仅用于判定；确需值时记 名称+长度+sha256 前 8 位掩码，\n  unb 同样掩码），供后续收紧判定。"},{"oldText":"- **凭证阶段接入**：`_fetch_credentials` 打开页面后检测登录态；未登录 →","newText":"- **并发协调（Eng F1，切片 1 必修）**：persistent context 单实例——per-profile\n  `asyncio.Lock` 登录协调器串行化全部 context 启动（无头提取与可见窗口互斥）；\n  第二个待登录房间排队，轮到时**先重查 unb**（前一房间登录可能已覆盖，直接免弹窗）；\n  **打开可见窗口前必须先关闭同房间无头 context**（1688 NeedLoginVisible 撕裂会话同款时序，\n  live1688.py L233 先例）。\n- **凭证阶段接入**：`_fetch_credentials` 打开页面后检测登录态；未登录 →"},{"oldText":"  **超时策略（spec 审查 1.3 + 第 2 轮 C1）**：同一房间累计 2 次超时后停止自动弹窗\n  （首登与重登共用该预算），降级无头游客模式继续尝试（保持既有行为）+ ENGINE_STATUS 提示\n  \"登录未完成——已按游客模式尝试，可停止该房间后重新添加以再次触发登录窗口\"；\n  登录成功后超时计数清零。","newText":"  **超时策略（spec 审查 1.3 + 第 2 轮 C1 + Eng F3/F4/F8）**：同一房间累计 2 次超时后停止自动弹窗\n  （首登与重登共用该预算），降级无头游客模式继续尝试（保持既有行为）+ ENGINE_STATUS 提示\n  \"登录未完成——已按游客模式尝试，可停止该房间后重新添加以再次触发登录窗口\"；\n  登录成功后超时计数清零。**等待循环每轮检查 _stop_flags**（Eng F3——用户停止房间立即\n  关窗中断等待，不让窗口挂满 300s；pdd 现状无此检查，taobao 新流程必须有）；\n  **捕获窗口关闭异常（TargetClosedError）按\"用户直接关窗\"分支处理**——计数+1 + 降级提示，\n  不得冒泡成 topic_failed（Eng F4——否则预算永远不计）；\n  **锁存键=room_id**（Eng F8——引擎实例跨房间共享，锁存不得吞掉其他房间的提示）；\n  300s 登录等待与既有 attempt 等待档位（无头 45s/可见 240s，taobao.py L136）的嵌套关系：\n  登录窗口是独立 deadline，不套用 240s 档位。"},{"oldText":"  (i) **enter 存活型**（pdd 同构预期）：90s 证据窗口内\"弹幕/礼物曾流入后完全静默，\n  同时 enter/统计仍存活\"→ 判定降级 → 弹重登（对齐 pdd is_degraded_window 证据窗口模式；\n  业务帧证据门槛=窗口前弹幕/礼物曾流入，杜绝冷清房间误弹——统计帧不参与判定）；","newText":"  (i) **enter 存活型**（pdd 同构预期）：90s 证据窗口内\"弹幕/礼物曾流入后完全静默，\n  同时 enter/统计仍存活\"→ 判定疑似降级 → **无头复验（自然复用下一重建轮），连续 2 个\n  证据窗口命中才弹重登**（Eng F5——单窗口会把\"曾活跃后自然冷场\"误判降级抢焦点弹窗；\n  连续 2 轮统一 (i)/(ii) 的计数语义）。业务帧证据门槛=窗口前弹幕/礼物曾流入，\n  杜绝冷清房间误弹——统计帧不参与判定；"},{"oldText":"  dump 观测哪些类停推/存活、统计帧行为、status==3 是否推送；\n  **臂 3（游客 unb 存在性，CEO F3）**","newText":"  dump 观测哪些类停推/存活、统计帧行为、status==3 是否推送；\n  **增补观测（Eng F5）：死会话+冷清房间+App 重启冷启动场景**——实证登录态会话即使冷清\n  是否仍有 enter 心跳（若有，\"启动 N 分钟零 enter\"可作冷启动活性信号，消除触发器 (i)\n  在冷启动死会话下的死代码形态）；\n  **臂 3（游客 unb 存在性，CEO F3）**"},{"oldText":"  **切片合并门（CEO F8）**：切片 1 = 首登闭环 + registry 声明 + 文案 + 单测\n  （不依赖 spike 结论，独立可交付用户可见价值）先行合入；\n  切片 2 = 重登触发器，随 spike 结论合入；spike 延期不阻塞切片 1。","newText":"  **切片合并门（CEO F8 + Eng F7 修订）**：**臂 1（guest 归因）先行且为切片 1 合并门**——\n  若实证 topic_failed 主因是滑块门而非登录门，切片 1 前提重审（臂 1 成本近零）；\n  切片 1 = 首登闭环 + registry 声明 + 文案 + 单测；切片 2 = 重登触发器，随臂 2 结论合入；\n  臂 2/3 延期不阻塞切片 1（臂 1 通过后）。"},{"oldText":"- **registry 声明（spec 审查 1.2）**：`PLATFORM_WARNINGS` 补 taobao 条目\n  \"淘宝直播受控页面——需淘宝/阿里账号登录，首次添加自动弹登录窗口\"。","newText":"- **registry 声明（spec 审查 1.2 + Eng F9）**：`PLATFORM_WARNINGS` 补 taobao 条目\n  \"淘宝直播受控页面——需淘宝/阿里账号登录，首次添加自动弹登录窗口\"；\n  **一并补齐 1688 条目**（同为需登录引擎层平台却无警告条，一行成本消内部不一致）。"},{"oldText":"  **不改动契约 O 的 30s last_msg_box 静默语义**（现有静默计时仍按任何 powermsg 帧刷新，\n  消除双计时器歧义）。每轮记录登录 cookie 值日志辅助诊断。","newText":"  **不改动契约 O 的 30s last_msg_box 静默语义**（现有静默计时仍按任何 powermsg 帧刷新，\n  消除双计时器歧义）。每轮记录登录 cookie 名+变更布尔日志（Eng F2 口径，不打值）。"},{"oldText":"### 2. douyu / huya / jd / xiaohongshu 登录策略声明（User Challenge 候选）\n\n四个平台实测游客可收目标消息，且：\n- douyu/huya 为 TCP 协议直连，账号 cookie 无注入路径（登录无从生效）；\n- jd/xiaohongshu 为受控页面，实测游客会话可达协议边界。\n\n计划处置：**不加登录弹窗**（弹窗与实测结论冲突——多一步用户操作、无消息增益、可能引入风控），\n在 `registry.PLATFORM_WARNINGS` 中补充\"游客可听，无需登录\"声明\n（spec 审查备忘：huya/jd/xiaohongshu 为**修订既有条目**追加该声明，douyu 为新增条目），\n并在 `docs/testing/full_platform_test_plan.md` 登录盘点表标注判定依据与**实测日期**\n（CEO F9 最低成本失效探测——声明过时可追溯；自动探测 defer 与 0G#4 面板同址）。\n此为对用户原话（\"完善除美团外其它平台缺失的登陆逻辑\"）的收窄，Final Approval Gate 呈报裁定。","newText":"### 2. douyu / huya / jd / xiaohongshu 登录闭环（用户裁定 B，2026-10-06 批准门驳回收窄）\n\n**用户权威裁定**：批准门 cycle 1 选择 B——驳回\"游客可听不加弹窗\"的收窄建议，\n四平台按用户原话字面实现登录检测+弹窗。（审查的\"实测游客可听\"结论保留为事实记录：\n- douyu/huya 为 TCP 协议直连，账号 cookie 无注入路径（登录态不进协议连接）；\n- jd/xiaohongshu 为受控页面，实测游客会话可达协议边界——登录态作为稳定性增强。）\n\n实现形态（分类）：\n- **jd / xiaohongshu（受控页面，对齐 1688 模式）**：登录 cookie 判定\n  （jd：pt_key/pt_pin 有值；xiaohongshu：web_session 有值）→ 未登录弹可见窗口\n  打开直播间页 → 登录态入 persistent profile → 关窗回无头继续。\n  共用预算/超时/stop 语义与 taobao 切片 1 一致（2 次内存态预算、300s 窗口、\n  每轮检查 _stop_flags、TargetClosedError 按关窗分支）。\n- **douyu / huya（TCP 直连，协议无注入路径）**：登录检测=cookie 文件登录态判定\n  （douyu：dedeuserid 有值；huya：登录 cookie 判定——spike 期确认具体 cookie 名，\n  初版用\"cookie 文件存在且非空设备 ID 之外有登录态 cookie\"宽判定+日志校准）→\n  无登录态弹可见窗口打开网页版登录页（douyu: www.douyu.com/login；\n  huya: www.huya.com）→ 用户登录后登录 cookie 存 cookie 文件 → 声明已登录。\n  **诚实边界注释（写进实现与文档）**：登录态不进 TCP 协议连接（协议边界）——\n  闭环价值=统一登录门槛 UX + 未来协议支持时 cookie 已就绪；\n  消息增益依赖平台未来在协议层引入身份通道。\n- registry.PLATFORM_WARNINGS：四平台条目改/补\"支持账号登录增强——首次添加自动弹登录窗口\"\n  （jd/xiaohongshu 修订既有条目；douyu/huya 新增条目；taobao/1688 条目同批）。\n- `docs/testing/full_platform_test_plan.md` 登录盘点表更新：四平台从\"游客可测\"\n  改为\"游客可测+登录增强闭环（2026-10-06 用户裁定）\"，标注判定依据与**实测日期**（CEO F9）。"},{"oldText":"- 斗鱼/虎牙协议级 cookie 注入（协议无此通道，非本次可解）。","newText":"- 斗鱼/虎牙协议级 cookie 注入（协议无此通道——弹窗闭环已按用户裁定实现，登录态存\n  cookie 文件备用；让登录态真正影响消息流需平台协议支持，非本次可解）。"},{"oldText":"- jd/xiaohongshu/douyu/huya 的可选登录增强（游客已达协议边界，收益为零）。\n","newText":""},{"oldText":"| douyu | 游客可收四类（TCP STT 直连，无 cookie 注入路径） | 无登录逻辑 | 实测不需要登录（见 User Challenge） |\n| huya | 游客可收三类（Tars 直连，无 cookie 注入路径） | 无登录逻辑 | 实测不需要登录（见 User Challenge） |\n| jd | 游客会话可收弹幕（实测注释） | 无登录逻辑 | 实测不需要登录（见 User Challenge） |\n| xiaohongshu | 观众侧无需登录（设备 cookie a1 自动种下） | 无登录逻辑 | 实测不需要登录（见 User Challenge） |","newText":"| douyu | 游客可收四类（TCP STT 直连，登录态无协议注入路径） | 无登录逻辑 | **用户裁定 B：实现检测+弹窗闭环**（登录态存文件备用） |\n| huya | 游客可收三类（Tars 直连，登录态无协议注入路径） | 无登录逻辑 | **用户裁定 B：实现检测+弹窗闭环**（登录态存文件备用） |\n| jd | 游客会话可收弹幕（实测注释） | 无登录逻辑 | **用户裁定 B：实现 1688 式登录闭环**（稳定性增强） |\n| xiaohongshu | 观众侧无需登录（设备 cookie a1 自动种下） | 无登录逻辑 | **用户裁定 B：实现 1688 式登录闭环**（稳定性增强） |"}]} -->
<!-- autoplan-baseline-edits:ceo {"sourceSha256":"4828e874cba38ad34d4e4ed5e6afaa3f11dd123130573c4228c4bc6b78250df8","replacements":[{"oldText":"### 1. taobao 补登录闭环（必修，对齐 1688 引擎层模式）\n\n`danmaku_listener/engines/protocol/taobao.py`：\n\n- **登录判定**：新增 `_has_login_cookie(context)` —— 阿里系统一 `unb` cookie\n  存在且有值（与 live1688.py 同判定；淘宝与 1688 同为阿里系账号体系）。\n  `_wait_login_visible` 期间把登录后新增 cookie 名全部打日志（1688 同款做法），供后续收紧判定。\n- **凭证阶段接入**：`_fetch_credentials` 打开页面后检测登录态；未登录 →\n  可见窗口（headless=False）打开直播间页，emit 系统消息\n  \"淘宝需要登录（弹幕仅登录会话推送）——已弹出浏览器，请用淘宝/阿里账号扫码登录\"，\n  阻塞等待登录（unb 出现，超时 300s）→ 登录态入 persistent profile → 关窗回无头 → 继续提凭证。\n- **会话失效重登**：`_run_room` 凭证重建轮（30s 无消息触发的整轮重建）复用同一检测\n  —— profile 登录态被服务端作废的场景自动弹窗重登（对齐 pdd 降级检测语义）。\n- 失败路径改造：`topic_failed` 错误文案补充\"未登录\"分支指引。\n\n### 2. douyu / huya / jd / xiaohongshu 登录策略声明（User Challenge 候选）\n\n四个平台实测游客可收目标消息，且：\n- douyu/huya 为 TCP 协议直连，账号 cookie 无注入路径（登录无从生效）；\n- jd/xiaohongshu 为受控页面，实测游客会话可达协议边界。\n\n计划处置：**不加登录弹窗**（弹窗与实测结论冲突——多一步用户操作、无消息增益、可能引入风控），\n在 `registry.PLATFORM_WARNINGS` 中为四平台补充\"游客可听，无需登录\"声明，\n并在 `docs/testing/full_platform_test_plan.md` 登录盘点表标注判定依据。\n此为对用户原话（\"完善除美团外其它平台缺失的登陆逻辑\"）的收窄，Final Approval Gate 呈报裁定。\n\n### 3. 前端透出确认（不新增功能，验证既有路径）\n\n淘宝新闭环的系统消息走既有 ENGINE_STATUS 通道（前端 alert 区已渲染），\n无需前端改动；验证添加淘宝直播间 → login_required 文案 → 弹窗 → 登录后自动监听全链路。\n\n## 测试计划\n\n- 单测：taobao `_has_login_cookie` 判定（unb 有/无/空值）、登录等待超时路径。\n- 实测（需用户配合）：清除/备份 taobao_profile 后添加淘宝直播间 → 弹可见窗口 →\n  扫码登录 → 自动开始监听；监听中手动作废登录会话 → 自动弹窗重登。\n- 回归：`python -m pytest tests/ -q` 基线 515 passed 不回退。","newText":"### 1. taobao 补登录闭环（必修，对齐 1688 引擎层模式）\n\n`danmaku_listener/engines/protocol/taobao.py`：\n\n- **登录判定**：新增 `_has_login_cookie(context)` —— 阿里系统一 `unb` cookie\n  存在且有值（与 live1688.py 同判定；淘宝与 1688 同为阿里系账号体系）。\n  **判定边界（spec 审查 1.1）**：unb 是账号标识而非会话令牌，仅用于**首次登录检测**\n  （未登录 → 弹窗）；**不得**用于会话失效重登判定（pdd 2026-10-05 已实证\n  cookie 存在性判定在会话作废场景失真并改用值变化检测）。\n  `_wait_login_visible` 期间打登录后新增 cookie **名与变更布尔**日志（Eng F2 修订口径：\n  pdd.py 真实形态只打名不打值——值仅用于判定；确需值时记 名称+长度+sha256 前 8 位掩码，\n  unb 同样掩码），供后续收紧判定。\n- **并发协调（Eng F1，切片 1 必修）**：persistent context 单实例——per-profile\n  `asyncio.Lock` 登录协调器串行化全部 context 启动（无头提取与可见窗口互斥）；\n  第二个待登录房间排队，轮到时**先重查 unb**（前一房间登录可能已覆盖，直接免弹窗）；\n  **打开可见窗口前必须先关闭同房间无头 context**（1688 NeedLoginVisible 撕裂会话同款时序，\n  live1688.py L233 先例）。\n- **凭证阶段接入**：`_fetch_credentials` 打开页面后检测登录态；未登录 →\n  可见窗口（headless=False）打开直播间页，emit 系统消息\n  \"淘宝直播间需要登录——已弹出浏览器，请登录淘宝/阿里账号（扫码）\"，\n  阻塞等待登录（unb 出现，超时 300s）→ 登录态入 persistent profile → 关窗回无头 → 继续提凭证。\n  **超时策略（spec 审查 1.3 + 第 2 轮 C1 + Eng F3/F4/F8）**：同一房间累计 2 次超时后停止自动弹窗\n  （首登与重登共用该预算），降级无头游客模式继续尝试（保持既有行为）+ ENGINE_STATUS 提示\n  \"登录未完成——已按游客模式尝试，可停止该房间后重新添加以再次触发登录窗口\"；\n  登录成功后超时计数清零。**等待循环每轮检查 _stop_flags**（Eng F3）；\n  **捕获窗口关闭异常按\"用户直接关窗\"分支处理**——计数+1+降级提示，不冒泡成 topic_failed（Eng F4）；\n  **锁存键=room_id**（Eng F8）；登录等待为独立 deadline，不套用 240s 档位。\n- **会话失效重登（三轮审查收敛，spike 驱动定型）**：淘宝降级会话的帧形态未实证，\n  且两项候选证据已被 dump/pdd 实证排除——淘宝统计帧 ~4s 一帧恒在流（taobao_dump.jsonl\n  21.3h/223 帧实证）、观看数=累计 UV（下播后仍 >0，onlineCount 恒 0，taobao.py 自校准），\n  均不可作活跃/在播证据；pdd 实证（2026-10-05）：会话作废后 enter/notice 帧继续推送、\n  弹幕/点赞停推——若淘宝同为 enter 存活型，\"无业务消息\"计数永不满足，触发器成死代码。\n  因此：\n  **T0 实施前置 spike（三臂实验；仅阻塞切片 2——切片合并门见下，CEO F8）**：\n  **臂 1（guest 归因，CEO F2）**：全新 guest profile 首次提凭证，观测 topic_failed\n  归因到底是登录门还是滑块门（taobao.py L122 注释自证滑块验证存在）——\n  若为滑块门，登录窗流程需带滑块处理，且\"必须登录\"前提重审；\n  **臂 2（降级帧形态）**：作废登录会话（手段按优先级：账号改密踢会话 > 服务端踢下线 >\n  本地删 token cookie 模拟；任一手段成功即达成 spike，CEO F4），\n  dump 观测哪些类停推/存活、统计帧行为、status==3 是否推送；\n  **增补观测（Eng F5）：死会话+冷清房间+App 重启冷启动场景**——实证冷清时是否仍有 enter 心跳；\n  **臂 3（游客 unb 存在性，CEO F3）**：日志确认全新 guest 态 unb 是否存在\n  （若游客也种 unb，首登判定重设计）。\n  三臂结论写入实现注释，触发器按臂 2 实测形态二选一定型：\n  (i) **enter 存活型**（pdd 同构预期）：90s 证据窗口内\"弹幕/礼物曾流入后完全静默，\n  同时 enter/统计仍存活\"→ 判定疑似降级 → **无头复验（复用下一重建轮），连续 2 个证据窗口\n  命中才弹重登**（Eng F5——统一 (i)/(ii) 计数语义，防\"曾活跃后自然冷场\"误弹）。\n  业务帧证据门槛=窗口前弹幕/礼物曾流入，杜绝冷清房间误弹——统计帧不参与判定；\n  (ii) **全停推型**：退化为重建轮失败计数器（连续 2 轮凭证重建后无任何帧 → 弹重登）。\n  spike 同步确认下播帧形态（status==3 若推送则作为重登排除条件）。\n  触发时把证据快照（窗口内各帧类计数）随日志/ENGINE_STATUS 带出（CEO F6——\n  防对单次 spike 观测过拟合，帧律变化后可反推）。\n  **切片合并门（CEO F8 + Eng F7）**：**臂 1 先行且为切片 1 合并门**（若 topic_failed\n  主因是滑块门，切片 1 前提重审）；切片 2 随臂 2 结论合入；臂 2/3 延期不阻塞切片 1。\n  **预算与生命周期（CEO F5 修订）**：首登/重登共用每房间 2 次超时预算\n  （用户直接关窗=超时一次），计数为**内存态，App 重启清零**（不持久化——\n  重启后首个触发即自愈，杜绝\"锁存一次后永久静默死亡\"）；\n  预算耗尽后 ENGINE_STATUS 提示**每引擎会话启动各提示一次**（不随触发刷屏）：\n  \"消息中断疑似登录过期——停止该房间后重新添加可重新触发登录窗口\"；\n  stop/重新添加清零全部计数；登录成功清零。\n  重登可见窗口超时 300s（同首登），打开直播间页。重登判定用独立 90s 证据窗口观测，\n  **不改动契约 O 的 30s last_msg_box 静默语义**（现有静默计时仍按任何 powermsg 帧刷新，\n  消除双计时器歧义）。每轮记录登录 cookie 值日志辅助诊断。\n- 失败路径改造：`topic_failed` 错误文案补充\"未登录\"分支指引\n  （归因措辞以 spike 臂 1 结论为准）。\n- **ENGINE_STATUS 登录生命周期事件词表（CEO F1）**：统一事件词（taobao 首用，\n  后续平台复用）——`login.first_login` / `login.relogin_triggered` /\n  `login.timeout_budget_exhausted` / `login.degraded_detected`；\n  证据窗口实现为 taobao.py 内独立纯函数（可单测）；跨平台原语泛化 defer\n  （第二个消费者出现时再抽取，P5 explicit）。\n- **registry 声明（spec 审查 1.2 + Eng F9）**：`PLATFORM_WARNINGS` 补 taobao 条目\n  \"淘宝直播受控页面——需淘宝/阿里账号登录，首次添加自动弹登录窗口\"；**一并补齐 1688 条目**。\n\n### 2. douyu / huya / jd / xiaohongshu 登录策略声明（User Challenge 候选）\n\n四个平台实测游客可收目标消息，且：\n- douyu/huya 为 TCP 协议直连，账号 cookie 无注入路径（登录无从生效）；\n- jd/xiaohongshu 为受控页面，实测游客会话可达协议边界。\n\n计划处置：**不加登录弹窗**（弹窗与实测结论冲突——多一步用户操作、无消息增益、可能引入风控），\n在 `registry.PLATFORM_WARNINGS` 中补充\"游客可听，无需登录\"声明\n（spec 审查备忘：huya/jd/xiaohongshu 为**修订既有条目**追加该声明，douyu 为新增条目），\n并在 `docs/testing/full_platform_test_plan.md` 登录盘点表标注判定依据与**实测日期**\n（CEO F9 最低成本失效探测——声明过时可追溯；自动探测 defer 与 0G#4 面板同址）。\n此为对用户原话（\"完善除美团外其它平台缺失的登陆逻辑\"）的收窄，Final Approval Gate 呈报裁定。\n\n### 3. 前端透出确认（不新增功能，验证既有路径）\n\n淘宝是引擎层登录平台：添加直播间返回 `success + running`（**不返回**\n`login_required`——那是 bridge 层三分支 bilibili/kuaishou/douyin 的响应形状），\n登录闭环在后台异步发生。验证链路（spec 审查 2.3 修正）：\n添加淘宝直播间 → 添加成功（响应含 taobao 新警告条）→ 数秒内弹可见登录窗口\n+ ENGINE_STATUS 系统消息（前端 alert 区渲染）→ 登录后自动开始监听。\n\n## 测试计划\n\n- 单测（tests/unit/test_taobao_protocol.py 扩展，判定逻辑仿 pdd 纯函数模式）：\n  `_has_login_cookie` 判定（unb 有/无/空值）、登录等待超时路径、超时 2 次后降级不弹窗、\n  预算耗尽 ENGINE_STATUS 锁存一次不刷屏、stop/重新添加清零计数、直接关窗=超时一次、\n  enter 存活型窗口判定（弹幕/礼物曾流入→静默+enter/统计存活→触发）、\n  业务帧从未流入的冷清房间不触发（统计在流不算证据）、全停推型重建计数触发、\n  登录成功后计数清零。\n- **T0 spike（三臂，实施前置；仅阻塞切片 2）**：臂 1 guest 归因 + 臂 2 作废会话帧形态 +\n  臂 3 游客 unb 存在性 → 定型触发器分支 (i)/(ii) → 实测形态沉淀为回归用例。\n- 实测（需用户配合，切片 1）：清除/备份 taobao_profile 后添加淘宝直播间 → 弹可见窗口 →\n  扫码登录 → 自动开始监听。\n- 实测（需用户配合，切片 2）：监听中手动作废登录会话 → 按 spike 定型的触发器 →\n  自动弹窗重登。\n- 回归：`python -m pytest tests/ -q` —— 以实施当日 `pytest --collect-only` 数为基线，\n  只增不减（spec 审查 3.1：硬编码基线已过时，不再引用固定数字）。"},{"oldText":"## NOT in scope\n\n- 美团登录（用户裁定：无登录入口，不需要登录）。","newText":"## NOT in scope\n\n- 已 defer 至 TODOS.md（0G 决议 #4，2026-10-06）：登录健康度面板（前端 UI）；\n  登录超时重试按钮；cookie 目录 README。\n- 美团登录（用户裁定：无登录入口，不需要登录）。"},{"oldText":"- jd/xiaohongshu/douyu/huya 的可选登录增强（游客已达协议边界，收益为零）。\n\n## What already exists","newText":"- jd/xiaohongshu/douyu/huya 的可选登录增强（游客已达协议边界，收益为零）。\n- 战略备忘 defer（CEO F10）：前端内嵌二维码替代 OS 弹窗（与 0G#4 面板同址）；\n  淘宝开放平台/官方弹幕通道评估（长线抗风控正道）。\n- 部署声明（CEO F7，实施时写入部署文档）：taobao/pdd/1688 登录事件需 attended 会话；\n  无人值守场景依赖游客降级 + ENGINE_STATUS（路径已有）。\n\n## What already exists"}]} -->

<!-- AUTONOMOUS DECISION LOG -->
## Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|-------|----------|----------------|-----------|-----------|----------|
| 1 | ceo-0D | 淘宝登录闭环放引擎层（对齐 live1688） | Mechanical | P3/P5 | 凭证阶段才开浏览器，bridge 无法轻量探测；1688 模式同源可复制 | bridge 层三分支扩展 |
| 2 | ceo-0D | 首登判定用 unb cookie；会话失效不用存在性判定 | Mechanical（spec 1.1 修订） | P3 | unb 是账号标识非会话令牌，作废后仍有值；pdd 已实证并改值变化检测 | 存在性判定用于重登 |
| 3 | ceo-0D（spec 1.1） | 重登触发器=连续 2 轮重建失败且非下播 | Taste→mechanical | P5/P3 | 简单显式，不依赖未实证的游客推送行为，无需值基线管理 | pdd 式值变化对比（需基线管理）；降级窗口启发式（淘宝无对照实证） |
| 4 | ceo-0D（spec 1.3） | 超时 2 次后停止自动弹窗降级游客 | Mechanical | P3 | 反复弹窗骚扰用户；游客尝试+提醒保底信号 | 每 backoff 轮重弹 |
| 7 | ceo-0D（第 2 轮 C1/C2/C4） | 重登触发器三条件：2 轮重建 + ROOM_STATS 观看数>0 + 预算未耗尽；首登/重登共用 2 次超时预算，成功清零 | Mechanical | P1/P5 | 关闭降级模式死循环与冷清房间误弹；观看数>0 一并解决非下播信号来源 | 触发器无视降级状态（死循环）；独立下播判定（无信号来源） |
| 8 | ceo-0D（第 3 轮） | 重登触发器改 spike 驱动定型：T0 作废会话实测帧形态 → enter 存活型用 pdd 式证据窗口（业务帧证据门槛）/ 全停推型用重建计数；统计帧与观看数排除出证据体系；预算耗尽锁存提示一次；TODOS.md 三条 defer 实施时补记 | Mechanical（实证驱动） | P1 + Claimed Limitations Need Evidence | dump 实证（统计 4s 一帧、观看数=累计 UV）与 pdd 实证（enter 存活反例）推翻第 2 轮假设；残余不确定性转为实施前置实证 | 直接拍死 pdd 式判定（淘宝形态未实证）；维持统计门槛（零区分度）；引入 status==3 独立判定（映射未实证） |
| 9 | ceo-voice | Claude CEO F1-F11 全部裁定：F2/F5 为阻塞收口（spike 三臂 + 预算内存态），F1/F6/F8/F9 随实施吸收，F7/F10 记档 defer | Taste→mechanical | P1/P3 | CEO 发现均有 dump/代码实证背书；Codex unavailable 单声部 | 维持 spike 单臂；锁存持久化 |
| 10 | eng-voice | Claude Eng F1-F9 裁定：F1 并发协调进切片 1（高危必修）；F2/F3/F4/F6 实现义务；F5 连续 2 轮统一计数；F7 臂 1 先行门；F9 补 1688 | Mechanical | P1（F1 为真实缺陷——多房间并发是产品常态） | persistent context 单实例锁实证；pdd 日志真实形态核验 | 维持逐房间独立 context（成本高）；单窗口触发（误弹） |
| 11 | gate-cycle1 | **用户裁定 B**：驳回四平台收窄（User Challenge 1 被用户否决）——四平台实现登录检测+弹窗闭环；新增 T8/T9 任务 | **用户权威裁定** | 用户指令优先 | 用户在批准门明确选择忠于原话字面；"游客可听"实测结论保留为记录 | A（收窄）——被用户驳回 |
| 12 | gate-cycle2 | **用户批准（选 A）**：计划含四平台登录闭环全部批准，开始实施 | 用户权威裁定 | — | 两轮批准门收敛 | — |
| 13 | 实施 | T1-T9 全部落地（2026-10-06）：taobao 切片 1+2（登录闭环/预算/词表/重登骨架）、registry 12 平台警告条、测试文档标注、jd/xhs 1688 式闭环、douyu/huya cookie 文件闭环、spike 脚本（tools/login_spike_taobao.py）、attended 部署声明；测试 557→560 只增不减 | 实施 | P1 | 审查收敛后的既定范围 | — |

## Reviewer Concerns（0H 第 3 轮收敛记录）

- 重登触发器最终形态待 T0 spike 定型（enter 存活型 → pdd 式证据窗口；全停推型 → 重建计数）——残余风险已显式化为实施前置 blocking 步骤，非文档假设。
- TODOS.md 三条 defer 条目（健康度面板/重试按钮/README）在实施阶段补写（第 3 轮 Feasibility #1 悬挂引用的处置）。
- 质量轨迹：R1 7/10 → R2 7/10 → R3 6/10（分数下降源于审查深度递进与 dump 实证引入，非质量退化；R3 确认 C1/C3/C5/C6/C7 实质解决，Scope/Feasibility 两维 PASS）。

## 0I Temporal Interrogation（实施者时间轴，SELECTIVE EXPANSION）

- **HOUR 1（地基）**：taobao.py 是 BaseEngine 直连子类（非 ControlledPageEngine）——登录窗口用 launch_persistent_context(taobao_profile, headless=False) 复用同一 profile；`_emit_system_status` 已就位（L248）直接用。
- **HOUR 2-3（核心逻辑歧义）**：spike 前先落两个判定函数骨架（enter 存活型窗口判定 / 重建计数器），spike 后接线二选一——避免 spike 后返工结构；unb 判定对齐 pdd `_login_cookie_values` 模式（遍历全量 cookie）。
- **HOUR 4-5（集成意外）**：persistent context 单实例——登录窗口期间不能并发跑无头凭证提取，须用 NeedLoginVisible 式信号中断当前会话、登录后重开（1688 同款，live1688.py L232/L405 有先例）；taobao 引擎层平台不走 bridge._login_gate，`_rooms` 状态由 bridge 常规 start 记录，登录进度只走 ENGINE_STATUS。
- **HOUR 6+（打磨/测试）**：spike 用临时脚本（参考 tools/ 下协议监听工具形态）dump 降级帧形态；spike 形态沉淀为回归用例；防"关窗即崩"——可见窗口 context.close() 后主循环须能继续（1688 先例处理过窗口被误关）。
| 5 | ceo-0G | taobao 失败文案补未登录指引 + registry 条目 | Mechanical | P1 | 同一修复爆炸半径内，<1d CC | 无 |
| 6 | ceo-0G | 登录健康度面板/超时重试按钮/cookie README → defer | Scope (defer) | P3 | UI 范围大或收益低，进 TODOS.md | 纳入本计划 |


## 实测缺陷修复轮（2026-10-06 14:25-14:45 用户实测，第二轮 /autoplan）

用户全平台实测发现 4 组缺陷，根因调查与修复（全部证据驱动）：

| # | 现象 | 根因（实证） | 修复 | 验证 |
|---|------|------------|------|------|
| F-dy | 抖音 `No module named 'quickjs'`→数据缺口 | 运行解释器未装 quickjs（runtime312 9/28 已有；用户服务进程用了另一解释器——依赖已入 requirements，属环境缺装非代码缺陷） | 两个解释器补装 quickjs；重启服务生效 | DouyinSigner 自检 OK；2 个既有 quickjs 测试由 F 转 P |
| F-bili | 停止监听时 `sent 1000` WARNING 噪音 | _run_room 内层逐 URL 异常处理无停止短路（外层有、内层漏） | bilibili.py 内层 except 加 `_is_stopping` 静默 return | 全量回归过 |
| F-jd/xhs | 登录窗弹出后转瞬关闭 | `_cookies()` 少 await——`context.cookies()` 返回 coroutine，baseline 读取 TypeError → except → window_closed → 窗口即关（**复现脚本实证**：RuntimeWarning coroutine never awaited → outcome=window_closed elapsed=1.4s） | controlled_base+taobao 两处 `_cookies` 改 async 兼容注入（同步 list/coroutine） | 修复后登录窗正常保持等待 |
| F-dy/hy | 斗鱼/虎牙不弹窗，`AttributeError: '_emit_system_status'` | BaseEngine 无该方法（ControlledPageEngine/taobao 各自有） | BaseEngine 增 `_emit_system_status`（形状与子类一致，后续可收敛） | douyu/huya 门槛恢复 |

**顺带发现（测试基建）**：huya lifecycle 单测真实起 `_run_room` → 登录门槛弹真窗 → stop 的 cancel 落点不同致 chromium 泄漏 → pytest 间歇性退出挂起（exit=124，5/5 复现；对照原版 3/3 正常）。修复：lifecycle 测试 stub `ensure_cookie_file_login`（单测不起真浏览器）。

回归：**566 passed 全过**（基线 560→566；抖音 2 个 quickjs 测试转正）。

| 14 | 实测修复轮 | 4 组缺陷修复（quickjs 环境/stop 短路/cookies await/BaseEngine emit）+ 测试基建修复 | Mechanical | P5+evidence | 复现脚本与对照实验实证根因 | 登录原因假设（jd/xhs 闪退与登录无关） |

## 实测缺陷修复轮 2（2026-10-06 15:45 用户实测斗鱼/虎牙）

| # | 现象 | 根因（实证） | 修复 |
|---|------|------------|------|
| F-hy2 | 虎牙"房间页未找到 tid" | 房间 158924 **未开播**（TT_ROOM_DATA isOn:false，tid 全 0）——原错误信息误导 | _fetch_tid_sync 先判开播状态：未开播报"开播后自动开始监听（持续重试）"，与"不存在"区分 |
| F-dy2 | 斗鱼弹窗打开旧房间页 185357 | **douyu.com/login 被斗鱼 302 重定向到直播间页**（curl 实证 final URL=185357）——非会话恢复 | login_url 改 passport.douyu.com（登录域名，200 实证） |
| F-dy3 | 登录后关窗→登录态丢失→每房间要两轮"登录+重启"才收到弹幕 | 轮询 2s 间隔可能没抓到登录 cookie 用户就关窗→关窗异常分支不存档→cookie 文件空→下次又弹窗（两轮=预算 2 的两次机会，与用户操作流程吻合） | 关窗异常分支用**最后已知 cookie** 判定+存档（login ok recovered from window close）——登录关窗不丢登录态 |

回归：566 passed 全过。

## 实测缺陷修复轮 3（2026-10-06 16:20-17:05 用户实测斗鱼/小红书，实机 probe 实证）

| # | 现象 | 根因（实机 probe 实证） | 修复 | 实机验证 |
|---|------|----------------------|------|---------|
| F-dy4 | 斗鱼每房间要两轮"登录+重启"第三次才收到弹幕 | 判定名 dedeuserid **不存在**——实机 probe（用户登录）抓 36 cookie：真实登录态=acf_uid/acf_auth 家族；判定永不命中→永不存档→预算耗尽才跳过弹窗直接监听（=用户看到的"第三次"） | LOGIN_COOKIE_NAMES["douyu"]=("acf_uid","acf_auth")；用户刚登录的真实登录态已转正式存档 | 24422 实机监听 90s 收 91 条（弹幕/进场/在线人数实时）✓ |
| F-xhs1 | 小红书未登录即显示"登录成功"（弹窗秒关） | 游客态基线 11 cookie **自带 web_session**（匿名会话）——web_session 有值即命中→立即虚假 logged_in | LOGIN_COOKIE_NAMES["xiaohongshu"]=("id_token",)（登录后新增的 JWT；游客无） | 570484250124682724 实机监听 60s：无弹窗（登录判定生效），ENTER 35/ROOM_STATS 1/LIKE 3/DANMU 1 ✓ |

cookie 名校准工具沉淀：tools/douyu_cookie_probe.py、tools/xhs_cookie_probe.py（实机 probe 模式——登录前后差异集实证，杜绝调研猜测名）。回归 566 passed 全过。

| 15 | 实测修复轮 3 | 斗鱼/小红书登录判定名实机校准（probe 差异集）+ 登录态注入 | Mechanical（实证驱动） | Claimed Limitations Need Evidence | 用户登录实机抓取；双态判定验证（登录 True/游客 False） | 继续用调研猜测名 |
