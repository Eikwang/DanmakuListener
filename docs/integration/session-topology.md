# 会话拓扑与登录载体（session topology）

> 2026-10-13 /autoplan 会话刷新编排计划交付物（S4-C）；数据源=12 平台代码审查（engines/senders/web 三路核验）。
> 用途：新平台接入、风控事件排查、重登/发送接线时的「哪个平台哪套会话」唯一事实源。

## 12 平台会话拓扑（监听 vs 发送）

| 平台 | 监听会话 | 发送会话 | 共享程度 | 重登（v2 编排）行为 |
|---|---|---|---|---|
| B站 | WS 直连游客 + `bilibili_cookies.txt`/`bilibili_storage_state.json` 增强 | 纯协议 HTTP，同 cookie 文件 | 文件级共享 | 清全清单→监听登录门重写；监听引擎读 storage_state 兜底（S5） |
| 斗鱼 | TCP 匿名直连（登录 cookie 仅存档） | 瞬态浏览器注入 `douyu_login_cookies.json` | 文件级共享 | 清文件→监听登录门重写→下次发送注入新 cookie |
| 快手 | WS 直连 + 浏览器 storage_state 取 token（登录必需） | 瞬态浏览器注入 `kuaishou_storage_state.json` | 文件级共享 | 同上（监听侧顺带续期写回） |
| **虎牙** | WS Tars 匿名直连（`huya_login_cookies.json` 仅存档） | 常驻浏览器 `cookie/huya_login_profile`（F1 快照） | **两套载体** | 重登直指发送侧：close→takeover 刷新 profile；监听匿名可听直启恢复；发送侧自然过期仍走懒弹自愈 |
| **抖音** | WS 直连游客 ttwid + `douyin_cookies.json`（礼物事件需登录） | 常驻浏览器 `cookie/douyin_profile`（bd_ticket_guard 指纹绑定） | **两套载体** | 单窗双喂：profile 登录→域白名单导出喂 `douyin_cookies.json`→恢复监听；降级两窗串行（`DANMU_RELOGIN_FORCE_TWO_WINDOW=1` 可回归） |
| 淘宝 | 受控页面 `taobao_profile` | 瞬态浏览器借同一 profile + `_profile_lock` | profile 级共享 | 清 profile→监听登录门；发送用新态 |
| 1688 | 受控页面 `1688_profile` | EngineHookSender 直写监听页 | 完全共享（同页） | 清 profile→监听登录门 |
| 小红书 | 受控页面 `xhs_profile`（游客可听） | EngineHookSender 同 profile F2 让位 | profile 级共享 | 同上 |
| 京东 | 受控页面 `jd_profile`（游客可听） | EngineHookSender 同 profile F2 让位 | profile 级共享 | 同上 |
| 视频号 | 受控后台 `wxsp_profile`（本人微信） | EngineHookSender 直写常驻后台页 | 完全共享（同页） | 同上 |
| 拼多多 | 受控页面 `pdd_profile`（登录必需） | 无 sender | — | 清 profile→监听登录门 |
| 美团 | HTTP 轮询直连（无需登录） | 无 sender | — | 不支持重登（ReloginUnsupported） |

## 载体分组与清理子集（重登编排）

- **profile 组**（淘宝/1688/小红书/京东/视频号/拼多多）：监听发送同 profile → 清全清单
- **文件组**（B站/斗鱼/快手）：sender 注入同一 cookie 文件 → 清全清单
- **双载体组**（抖音/虎牙）：发送侧 profile **不预清**（登录原地刷新，放弃时旧态不劣化）
  - huya 清理集=空；douyin 清理集=`douyin_cookies.json`
  - 全清单仍见 `PLATFORM_LOGIN_CARRIERS`（relogin.py——ReloginUnsupported 判定）

## AUTOlive 触发回路契约（§4.4 修正段）

```
侦测 NEEDS_LOGIN（SYSTEM_STATUS）或发送拒绝携 relogin_in_progress
  → POST /api/relogin  {platform, room_id}   [Bearer token]
  ← 同步段（立即）：{relogin_id, platform, rooms_stopped[], carriers_cleared[],
                     send_refresh, login_flows[], status_url}
  → 轮询 GET /api/relogin/status?id=<relogin_id>   [Bearer token；建议 2-5s]
  ← 异步段：{state, rooms[], send_refresh, login_flows, interruption_window, error?}
  终局处置：
    completed      → 恢复正常发送
    login_required → 提示人工完成登录后重跑重登（房间保持 stopped）
    failed         → 按 error 提示（恢复超时/编排错误）——重跑重登或手动启动房间
    superseded     → 停止轮询旧 id（已被新重登取代）
    404            → 记录不可得（重启即失/淘汰 10 条或 1h）：停止轮询按未知终局处理；
                     ⚠ 重 POST 会再次停房+弹登录窗——距上次已知活动超过轮询窗口时先确认真需重登
```

### 可复制示例

```bash
# 1) 发起重登（同步段——立即返回即时事实）
curl -s -X POST http://127.0.0.1:8086/api/relogin \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"platform":"douyin","room_id":"123"}'
# 200 → {"success":true,"relogin_id":"<uuid>","platform":"douyin",
#        "rooms_stopped":["123"],"carriers_cleared":["douyin_cookies.json"],
#        "send_refresh":"close_ok","login_flows":[{"side":"send","kind":"profile_login",
#        "triggered":true,"reused_existing":false}],
#        "status_url":"/api/relogin/status?id=<uuid>","msg":"..."}

# 2) 轮询异步段
curl -s "http://127.0.0.1:8086/api/relogin/status?id=<uuid>" -H "Authorization: Bearer $TOKEN"
```

五态样例（status 响应的 state 字段）：

```json
{"state": "completed", "rooms": [{"room_id": "123", "status": "running"}],
 "send_refresh": "refresh_ok", "interruption_window": {"started_at": 1760000000, "ended_at": 1760000180}, "error": null}
{"state": "login_required", "rooms": [{"room_id": "123", "status": "stopped"}],
 "send_refresh": "refresh_failed", "error": "抖音登录未完成（超时/关窗）——发送侧旧态保留，重跑重登即可（docs/integration/autolive-merge-v0.7.0.md §4.4）"}
{"state": "failed", "rooms": [{"room_id": "123", "status": "failed", "recovery_error": "房间启动失败"}],
 "send_refresh": "refresh_ok", "error": "恢复超时（非登录原因）——部分房间未回到监听，重跑重登或手动启动（docs/integration/autolive-merge-v0.7.0.md §4.4）"}
{"state": "superseded", "superseded_by": "<new-uuid>", "rooms": [{"room_id": "123", "status": "stopped"}],
 "send_refresh": "close_ok"}
（404）→ {"success": false, "error": "relogin_id 不可得（已淘汰或进程重启）——停止轮询按未知终局处理；..."}
```

### send_refresh 值 × 平台组 × 阶段判定表

| 值 | 出现平台组 | 阶段 | 含义 / 消费方动作 |
|---|---|---|---|
| `pending` | 双载体（理论态） | 同步段兜底 | 尚未 close——继续轮询 |
| `not_applicable` | 单载体 8 平台 | **终值** | 无独立发送会话；登录=房间恢复 |
| `close_ok` | 双载体 | 同步段即时 → 中间值 | 发送会话已关；**等待登录结果**（会被 refresh_* 覆盖） |
| `close_failed_stale_marked` | 双载体 | 同步段即时 → 中间值 | close 超时已标 stale（DX-D7 下次启动清理）；等待登录结果 |
| `refresh_ok` | 双载体 | **终值** | 发送侧登录已刷新 |
| `refresh_failed` | 双载体 | **终值** | 登录/导出失败——看 error（携 docs 锚点）；监听恢复不受影响；重跑重登即可 |

错误消息规范：problem + cause + fix + docs 锚点（差集报错与 refresh_failed 携指南 §4.4 锚点）。

### 平台行为一览（重登窗口预期）

| 平台 | 弹什么窗 | 发送侧何时刷新 | 房间恢复 |
|---|---|---|---|
| 抖音 | profile 登录窗（1 个） | 登录落地+导出成功后 | 登录落地后自动恢复 |
| 虎牙 | 发送登录窗（1 个，takeover） | takeover 成功后 | 触发即直启恢复（不等发送侧） |
| 其余 8 平台 | 监听登录窗（1 个，既有登录门） | 无独立发送侧（同载体） | 登录完成后自动恢复 |
| 抖音（降级开关） | 监听窗+发送窗（2 个串行） | profile 窗成功后 | 监听窗完成后恢复 |
