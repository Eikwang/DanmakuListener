# 虎牙发送协议直连重构计划（2026-10-09）

## Implementation plan

### 背景与证据链（全部本会话实验实证）

- 验收实测：虎牙自动化发送（headless_new 常驻会话）被服务端**静默吞弹幕**——框架受理提交（输入框清空）、本地乐观渲染出现、但服务端不广播（F8 监听流核查无回环）、直播间不上屏。headed 真窗口同自动化操作**能过**（对比实验：人工「123」与自动「[M0] auto-compare」双双进聊天流）。
- 排除项（逐一实验排除）：元素定位（用户 devtools 实测修正 #pub_msg_input+#msg_send_bt 后仍吞）、登录会话（官方流程登录成功且保窗验证）、stealth 指纹包（7 信号伪装注入后仍吞）、房间开播状态（在播房间 152746 复测仍吞）。
- **根因判定：虎牙风控对 headless=new 浏览器形态的会话级静默吞**（headless 指纹识别后整会话弹幕静默丢弃；headed 真窗口不受影响）。行为拟人化实验（stealth 包）已证明指纹层伪装不解决——检测在会话/环境信誉层。
- **通道捕获突破**：虎牙 web 发弹幕走 **HTTP POST / WS 至 `cdnws.api.huya.com`，Tars 编码请求（baseinfo=base64 在 URL）**——与监听侧协议同构（仓库已有 huya Tars 解码基础设施）。人工发送的聊天帧已捕获（含 live:1199658761581 房间标识与弹幕文本，截断样本）。
- 用户决策记录：方案 A（登录窗转正，PR #11）已实施并实测——登录态保活成立；headless 对抗（实验 1 stealth 包）用户裁定穷尽后失败；**用户最终裁定：协议直连重构（重新分析、不基于旧经验）**。

### 技术方案：协议直连发送（脱离浏览器）

虎牙发送整体切换为**纯 Python 协议直连**（与监听引擎同构）：

1. **帧结构逆向**：完整捕获聊天发送帧（payload 无截断+多样本对齐）→ 用仓库 Tars 解码器拆字段（live_id/文本/seq/timestamp/签名字段识别）→ 多帧 diff 确定可变区与固定区。
2. **发送器实现**：纯 Python WS 客户端（wss://cdnws.api.huya.com，携带 profile 登录 cookie）→ 注册/心跳帧（已捕获样本）→ 聊天帧构造器（huya_codec 扩展 send 方向）→ 发送+回执判定。
3. **登录态方案**：profile 持久 cookie 作为 WS 握手凭证；会话失效检测（服务端静默吞的识别——发送后 N 秒无回显计 unknown 并告警）→ 触发可见登录窗（复用 login_takeover 流程重建 cookie）。
4. **形态收益**：无浏览器 = 无 headless 指纹问题 = 完全后台静默运行（用户「完全后台」诉求在协议直连下真正达成）。

### 风险与边界

- 聊天帧可能含**动态签名/时间戳令牌**（页面 JS 生成）——若存在且不可逆向，协议直连被阻断，回退方案=headed minimized 形态（T6 实证）。逆向阶段第一步即验证此风险。
- 风控对抗累积效应：协议直连的发送仍可能被行为风控标记（与 DOM 自动化同账号）——成功率需实测监控（周报机制已有）。
- 逆向工程合规边界：与监听侧协议同源同性质（自运营直播间使用）。

### 实施任务

- [ ] **T1 (P1, human: ~30min / CC: ~15min)** — 完整帧捕获：v3 捕获脚本（payload 无截断+同一消息 3 次采样），Tars 字段 diff 表
- [ ] **T2 (P1, human: ~1h / CC: ~30min)** — 帧结构逆向：Tars 解码器拆字段、识别动态区（签名/timestamp）、可行性裁决（有动态签名→回退 headed 方案并归档）
- [ ] **T3 (P1, CC: ~40min)** — 纯 Python 发送器：WS 连接+注册/心跳+聊天帧构造（huya_codec 扩展）
- [ ] **T4 (P1, CC: ~15min)** — 实发验证：发送→直播间上屏+监听流回环双确认
- [ ] **T5 (P2, CC: ~20min)** — 登录失效检测（发送后无回显计 unknown+告警）→ 触发 login_takeover 重建 cookie
- [ ] **T6 (P2, CC: ~10min)** — 周报接入（协议直连发送成功率监控）

### 判定标准

- T2 裁决「可行」→ T3/T4 实施 → 虎牙 ✅（协议直连形态，完全后台达成）
- T2 裁决「不可行」（动态签名无法逆向）→ 回退 headed minimized（T6 形态+新定位器）→ 虎牙 ✅（ headed 形态）

### 非目标（NOT in scope）

- 快手/小红书/京东/视频号的发送验收（主线继续，互不阻塞）
- 1688 发送的 shadow-drop 对抗（已有卡片跟踪）
- 淘宝/斗鱼/B站（已验收通过）

## Review record

（/autoplan 评审进行中）

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | PENDING | 待评审 |
| Outside Review | codex | Independent 2nd opinion | 0 | UNAVAILABLE | gpt-6-astra 400（本机已知） |
| Eng Review | `/plan-eng-review` | Architecture & tests | 0 | PENDING | 待评审 |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | SKIPPED | 无 UI scope |
| DX Review | `/plan-devex-review` | DX gaps | 0 | SKIPPED | 非开发者工具 |

**OUTSIDE COVERAGE:** codex / unavailable（gpt-6-astra 400，本机已知问题）。
**VERDICT:** 评审进行中。

NO UNRESOLVED DECISIONS
