# 发送功能运维手册（AutoDanmu，ADR-002）——适用于全部已启用平台

生成：/autoplan 批准计划 T10 | 2026-10-07

## 发送开关与配置（[send] 配置段）

| 键 | 默认 | 说明 |
|----|------|------|
| send_enabled_platforms | ""（全关） | 逗号分隔启用平台，如 `bilibili,taobao` |
| send_dry_run | true | 观察模式：只记录不实发（出口标准=连续 N 次抽检合格，R20） |
| send_min_interval_seconds | 30.0 | 限速键最小间隔 |
| send_rate_key | platform | 限速键口径：platform / platform_room（F4） |
| send_circuit_threshold | 5 | 连续失败熔断阈值 N |
| ws_token_file / DANMAKU_TOKEN | 无 | **未配置=发送/对账端点拒绝服务（F6）** |

## 常见失败与处置

| 现象（回执 reason_code） | 原因 | 处置 |
|--------------------------|------|------|
| AUTH_UNCONFIGURED | 未配置 token | 配置 token 后重启 |
| SENDER_DISABLED | 平台发送开关关闭 | config 启用后重启（重启生效） |
| CIRCUIT_OPEN | 连续 N 次失败熔断 | **人工重开**：排查平台侧（禁言/登录态/风控）后 enable |
| ROOM_NOT_LISTENED | 目标房间未监听 | 先在控制台添加并启动该房间 |
| RATE_LIMITED / DUPLICATE / TOO_LONG / KEYWORD_BLOCKED | 守卫命中（拒绝不排队） | AUTOlive 退避重试；调 send_min_interval / send_max_length / 关键词表 |
| PLATFORM_REJECTED | 平台侧拒绝 | 看 fix_hint 与引擎日志；登录态失效→重登（NEEDS_LOGIN 流程） |
| AUDIT_UNAVAILABLE | 审计写失败 | 检查 persistence_data/ 磁盘与权限；实发路径 fail-closed（R25） |
| ROUTE_UNVERIFIED | 发送路线未过 M0 探针 | 跑 tools/send_probes/ 对应平台探针 |

## 对账（AUTOlive 侧）

- 审计文件：`persistence_data/send_audit.jsonl`（权威记录，kind=intent/result 两行制）
- 重连后按 request_id 查询：`GET /api/send-results?request_id=<id>`（Bearer token）
- **自发声回环**：发送成功的弹幕会回到监听流——AUTOlive 必须按
  DANMU_SEND_RESULT 的 sent_at+content 在对账窗口去重自己的发声（F8/R39）

## 平台专项

- **B站**：cookie 需 SESSDATA+bili_jct；登录失效回执 PLATFORM_REJECTED(code=-101)→重登
- **受控页面组（淘宝/1688/小红书/京东/视频号）**：发送经由监听引擎实例（E5）——
  与监听共享 profile；发送期间监听可能瞬时不稳定属预期（F11，实测卡片有专项）
- **抖音/快手/斗鱼/虎牙**：路线待 M0 探针终判（tools/send_probes/）——
  回执 ROUTE_UNVERIFIED=探针未完成
