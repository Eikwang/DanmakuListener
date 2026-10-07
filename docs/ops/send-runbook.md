# 发送功能运维手册（AutoDanmu，ADR-002 + 修复计划 2026-10-07）——适用于全部已接线平台

生成：/autoplan 批准计划 T10/T5 | 2026-10-07 更新（T2 淘宝 mtop/T3 抖音常驻/T6 三平台接线）

## 发送开关与配置（[send] 配置段）

| 键 | 默认 | 说明 |
|----|------|------|
| send_enabled_platforms | ""（全关） | 逗号分隔启用平台，如 `taobao,douyin,huya` |
| send_dry_run | true | 观察模式：只记录不实发（出口标准=连续 N 次抽检合格，R20） |
| send_min_interval_seconds | 30.0 | 全局限速键最小间隔（秒） |
| send_min_interval_overrides | `{"huya": 35}`（内置默认） | **per-platform 限速覆写**（T6）——INI 提供 JSON 对象**按键合并**进内置默认（未被覆写的平台保留默认值；INI 同键值优先）。内置：虎牙 35s（10-14s 实测失败、35s 补发全过——样本=单账号单卡，部署后前两周观察误判率，CEO-F6） |
| send_session_idle_timeout_seconds | 1800 | 抖音常驻发送会话空闲自动关闭（秒）——空闲后首条发送含冷启动（实测 6.2s 全链路，<15s 阈值无需调整，CEO-F7） |
| send_window_mode | headless_new | 抖音会话形态：**headless_new（默认，T1 探针实证无桌面可运行）**/ minimized / foreground（DX-D9） |
| send_circuit_threshold | 5 | 连续失败熔断阈值 N |
| send_rate_key | platform | 限速键口径：platform / platform_room（F4） |
| ws_token_file / DANMAKU_TOKEN | 无 | **未配置=发送/对账端点拒绝服务（F6）** |

## 常见失败与处置

| 现象（回执 reason_code） | 原因 | 处置 |
|--------------------------|------|------|
| AUTH_UNCONFIGURED | 未配置 token | 配置 token 后重启 |
| SENDER_DISABLED | 平台发送开关关闭 | config 启用后重启（重启生效） |
| CIRCUIT_OPEN | 连续 N 次失败熔断 | **人工重开**：排查平台侧（禁言/登录态/风控）后 enable |
| RATE_COOLDOWN | T4 DOM 兜底滑块冷却期（含剩余秒数） | 冷却结束后自动恢复；勿反复重试撞墙 |
| ROOM_NOT_LISTENED | 目标房间未监听 | 先在控制台添加并启动该房间 |
| RATE_LIMITED / DUPLICATE / TOO_LONG / KEYWORD_BLOCKED | 守卫命中（拒绝不排队） | AUTOlive 退避重试；调 send_min_interval / send_max_length / 关键词表 |
| PLATFORM_REJECTED（detail 含 RGV587/x5sec/风控） | 平台风控拦截 | **降频稍后重试；勿重扫码**（登录态未失效——CEO-F4 ret 映射语义） |
| PLATFORM_REJECTED（fix_hint 含"登录"） | 登录态失效 | 按对应平台登录 CLI 重登（见下节） |
| AUDIT_UNAVAILABLE | 审计写失败 | 检查 persistence_data/ 磁盘与权限；实发路径 fail-closed（R25） |
| ROUTE_UNVERIFIED | 发送路线未过探针/页面 mtop 库缺失 | 跑对应平台探针（tools/send_probes/） |

## 凭证从零生成（DX-D1——三平台+抖音；发送侧从零配置闭环）

| 平台 | 命令 | 凭证形态 |
|------|------|---------|
| 快手 | `python -m danmaku_listener.engines.kuaishou_login [room_id]` | cookie/kuaishou_storage_state.json |
| 斗鱼 | `python -m danmaku_listener.engines.send_login douyu [room_id]` | cookie/douyu_login_cookies.json（acf_*） |
| 虎牙 | `python -m danmaku_listener.engines.send_login huya [room_id]` | cookie/huya_login_profile（persistent） |
| 抖音 | `python -m danmaku_listener.engines.douyin_login [room_id]` | cookie/douyin_profile（bd_ticket_guard 指纹绑定，扫码一次） |
| 淘宝 | 淘宝直播控制台登录（taobao_profile） | 引擎凭证提取链路自动 |

## 对账（AUTOlive 侧）

- 审计文件：`persistence_data/send_audit.jsonl`（权威记录，kind=intent/result 两行制）
- 重连后按 request_id 查询：`GET /api/send-results?request_id=<id>`（Bearer token）
- **自发声回环**：发送成功的弹幕会回到监听流——AUTOlive 必须按
  DANMU_SEND_RESULT 的 sent_at+content 在对账窗口去重自己的发声（F8/R39）

## 平台专项

- **B站**：cookie 需 SESSDATA+bili_jct；登录失效回执 PLATFORM_REJECTED(code=-101)→重登
- **淘宝（mtop page-eval，T2 主路线）**：sender 经引擎瞬态页 evaluate 调页面 mtop 库
  （`mtop.taobao.iliad.comment.publish`——页面 JS 现生成 bx-ua，**纯 HTTP 重放被
  RGV587 拒**，T1 判定）；滑块问题架构性消除；DOM 钩子 deprecated 保留（T4 参照）
- **抖音（常驻会话，T3）**：headless=new 形态（**无桌面要求**——"窗口闪烁属预期"
  旧表述作废）；per-room page 常驻+空闲 30min 自动关闭+close 失败自愈；登录失效
  信号=页面"需先登录"文本（重扫码）；**回显判定=get_by_text 穿透 shadow DOM**
  （聊天流已 shadow 化）；发送前 visibilityState 断言入日志（CEO-F3）
- **快手/斗鱼（瞬态注入，T6）**：storage_state/cookie 注入+headless=new（旧 headless
  被风控——"请求过快"/"错误代码22"）；斗鱼选择器=placeholder 精确特征前置（防搜索框误选）
- **虎牙（常驻会话第二实例，T6）**：headed minimized 窗口（可见但最小化，不影响桌面）；
  **35s 冷却**由 guard 覆写内置默认（发送间隔不足回执 RATE_LIMITED）；输入框
  #pub_msg_input 延迟挂载（渲染等待已内置）
- **受控页面组（1688/小红书/京东/视频号）**：发送经由监听引擎实例（E5）——
  与监听共享 profile；发送期间监听可能瞬时不稳定属预期（F11）
- **选择器失效自查（ENG-17）**：跑 `python tools/send_probes/dom_send_probe.py
  --platform <p> --room-url <url> --sends 1`——卡片 selector_notes dump 全部候选
  （found=命中/tried=不可见），按 found 字段更新 sender 候选序

## 运维节奏（每周）

1. **淘宝 mtop 重放健康检查（CEO-F4）**：
   `python tools/send_probes/taobao_mtop_capture.py --replay persistence_data/taobao-mtop-template.json --sends 1`
   ——ret 非 SUCCESS→端点/风控变化，排查后更新模板（capture 重抓）
2. **实发成功率周报（CEO-F13/ENG-7）**：统计 send_audit.jsonl 各平台
   sent/failed 比率；**快手/斗鱼/虎牙成功率跌破阈值→升级该平台常驻会话或登录链改造**
3. **平台政策监控（CEO-F10）**：风控突变/新规发布（AI 直播标注等）→重评发送策略；
   平台官方数字人工具成熟→发送层整体过时风险（战略级信号）

## cookie/ 目录语义（DX-D10）

- `*_storage_state.json`（快手）=Playwright storage_state 混合形态（cookies+origins）
- `*_login_cookies.json`（斗鱼/虎牙协议存档）=纯 cookie 数组/对象
- `*_profile/`（抖音/虎牙/淘宝等）=Chromium persistent 目录（指纹绑定）
- 三者同为登录态载体但结构互异——**sender 不通用**；文件均在 .gitignore 覆盖内
  （敏感凭证，勿入库、勿外传；清理时机=账号废弃时）

## 敏感文件说明（ENG-13）

- `persistence_data/taobao-mtop-template.json`（mtop 请求模板）——已脱敏
  （cookie/auth 头剔除），persistence_data/ 整目录 .gitignore 覆盖；T2 验收后可删
- 探针卡片 cards/*.json 含业务字段结构（无凭证）——可入库

## 发送链路安全与可靠性（既有义务存档）

- 全部 REST/WS 命令入口强制 Bearer token（web 旧 API 无鉴权为既有现状，新端点不得沿用）
- 过滤层含控制符/换行清洗；审计 fail-closed（实发路径审计失败=拒绝发送）
- per-profile 锁发送 acquire 带超时（busy 回执）；熔断恢复=人工重开
