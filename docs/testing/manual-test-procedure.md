# 弹幕监听系统 手工测试流程

> 版本：2026-09-28 ｜ 适用：契约 v1 实现后的首次端到端手工验证
> 前置阅读：[docs/contract/schema.md](../contract/schema.md)（消息语义）、[docs/integration/autolive-integration-readiness.md](../integration/autolive-integration-readiness.md)（平台就绪矩阵）
>
> 测试原则：**从离线到在线**（先不依赖真实直播间验证通道与格式，再逐平台实测）。
> 每个步骤标注 [预期输出]，与实际不符时记入 §8 问题记录模板。

---

## §0 测试环境准备（约 5 分钟）

- [ ] **0.1** 在仓库根目录 `D:\AI\DanmakuListener` 打开终端（PowerShell 或 CMD）
- [ ] **0.2** 确认 Python ≥3.11：`python --version`
- [ ] **0.3** 依赖已安装（首次执行）：
      `set PYTHONUTF8=1 && python -m pip install -r requirements.txt -q`
      （含中文注释的 requirements 必须带 `PYTHONUTF8=1`，否则 GBK 解码报错）
- [ ] **0.4** Playwright 浏览器内核（视频号/浏览器引擎需要，首次执行）：
      `python -m playwright install chromium`
- [ ] **0.5** 验证 CLI 三入口可用：
      `python -m danmaku_listener contract`
      [预期输出] JSON：`"contract_version": "1.0.0"` 与三个文档路径

---

## §1 自动化回归（一键，约 1 分钟）

- [ ] **1.1** 单元测试全量：`python -m pytest tests/unit/ -q`
      [预期] `609 passed`（或更多）
- [ ] **1.2** 集成测试：`python -m pytest tests/integration/ -q`
      [预期] `10 passed`
- [ ] **1.3** 契约漂移检查：`python scripts/export_contract.py --check`
      [预期] `contract schema in sync`
      ❌ 若报 drift：契约模型与 Schema 不同步，停止测试并反馈（勿手改 schema.json）

---

## §2 离线冒烟：fixtures 回放（无需真实直播间，约 2 分钟）

验证推送格式与 TTHW，不依赖网络与开播状态。

- [ ] **2.1** 离线回放演示：
      `python -m danmaku_listener listen --replay docs/contract/examples/demo.jsonl --speed 20`
      [预期 stdout] 12 行 JSON，首行 `"type": "ENGINE_STATUS"`，含 DANMU/GIFT/SUPER_CHAT/GAP 等完整消息类型
      [预期 stderr] `[tthw] first message after <N> ms`（N 应 < 1000）与 `[replay] 12 messages`
- [ ] **2.2** 检查 JSON 字段完整性（任取一行）：
      必含 `contract_version/category/type/platform/room_id/seq/timestamp/engine/payload`
- [ ] **2.3** 重复执行 2.1 两遍，确认输出序列一致（回放确定性）

---

## §3 WS 推送通道测试（serve + 消费助手，约 5 分钟）

验证 AUTOlive 将来使用的真实通道：token 鉴权、广播、慢消费行为。

- [ ] **3.1** 终端 A 启动服务（回放作为消息源）：
      `python -m danmaku_listener serve --replay docs/contract/examples/demo.jsonl`
      [预期] 启动横幅 JSON：`"ws": "ws://127.0.0.1:8765/ws"`、`"auth": "loopback-only"`（未配 token）
- [ ] **3.2** 终端 B 启动消费助手：
      `python tools/ws_listen.py --count 5`
      [预期 stderr] `[connected]` + `[tthw] first message after <N> ms`；
      [预期 stdout] 5 行契约 JSON 后自动退出
- [ ] **3.3** token 鉴权负向测试：重启服务并在启动前设置
      `set DANMAKU_TOKEN=test123`，然后：
      - 无 token 连接：`python tools/ws_listen.py`
        [预期] `[error] ... 401/ConnectionClosed`（拒绝）
      - 正确 token：`python tools/ws_listen.py --token test123 --count 3`
        [预期] 正常收到消息
- [ ] **3.4** 断开重连：消费助手运行中直接 Ctrl+C，再重新连接
      [预期] 服务端日志显示 consumer disconnected/connected；**不重放**历史消息
      （契约投递语义：重连不重放，缺口由 GAP 报知）
- [ ] **3.5** 测试完成后关闭终端 A（Ctrl+C）

---

## §4 平台真实连接测试（逐平台，依赖真实网络）

> 按 [就绪矩阵](../integration/autolive-integration-readiness.md) 分级：
> ✅ 可实测（B站/斗鱼）｜⚠️ 需前置条件（抖音/快手/视频号）｜❌ 暂不承诺（虎牙 draft）

### 4A B站协议直连（✅ 优先测，约 10 分钟）

- [ ] **4A.1** 选一个**正在直播**的 B站房间（直播间页 URL 中房间号；可直接用
      `https://live.bilibili.com/<房间号>` 人工确认有弹幕滚动）
- [ ] **4A.2** 协议直连（绕过旧路由，直接驱动阶段 1 引擎）：
      `python tools/protocol_listen.py bilibili <房间号> --duration 60`
      [预期 stdout] 契约 JSON 流（DANMU/ENTER_ROOM/ROOM_STATS 等），首行带
      `"protocol_version": "bilibili-1"`
      [预期 stderr] `[tthw] first message after <N> ms`（**目标 < 1000ms，验收口径 <1s**）
- [ ] **4A.3** 记录一分钟消息条数（[done] 行），与直播间人工观察的弹幕频率比对数量级
- [ ] **4A.4** 下播边界测试（可选）：用一个**未开播**房间执行
      [预期] `no_message` 或 `start_timeout` 三段式错误（reason/fix/docs），无 JSON 崩溃
- [ ] **4A.5** 旧路由冒烟（浏览器引擎，验证兼容层）：
      `python -m danmaku_listener listen bilibili:<房间号> --timeout 30`
      [预期] Playwright 启动并进入直播间（stdout JSON 流）。**注意**：该路径是旧引擎，
      内存行为不代表新协议引擎，仅验证兼容层未破坏

### 4B 斗鱼协议直连（✅，约 10 分钟）

- [ ] **4B.1** 选一个正在直播的斗鱼房间（`https://www.douyu.com/<房间号>`）
- [ ] **4B.2** `python tools/protocol_listen.py douyu <房间号> --duration 60`
      [预期] 契约 JSON 流（DANMU 带 `badge_name/badge_level` 粉丝牌字段），
      `"protocol_version": "douyu-1"`
- [ ] **4B.3** 观察 45s+ 运行不中断（心跳周期 45s，验证心跳维持连接）

### 4C 抖音代理模式（⚠️ 需环境前置）

- [ ] **4C.1** 部署前置检测：`python scripts/preflight.py --platforms douyin`
      [预期] JSON 报告含人工确认项（根 CA 安装、直播伴侣版本、hook 知情确认）
- [ ] **4C.2** 按合规清单（docs/ops/compliance-review.md §4）完成证书安装与伴侣版本核对
- [ ] **4C.3** 打开抖音直播间（浏览器或直播伴侣），验证代理捕获：
      现有链路 `python -m danmaku_listener listen douyin:<房间号> --timeout 30`
      [预期] 代理注册 + JSON 流（protobuf 解析路径）
- [ ] **4C.4** 异常路径：错误房间号执行，确认三段式错误而非栈崩溃

### 4D 快手协议直连（⚠️ 重点验证项）

- [ ] **4D.1** 确认游客 token 获取方式（**本项未验证**：签名接口见计划 Open Questions）。
      已知 token 后用注入方式测试：
      ```python
      # tools 或 REPL 中：
      from danmaku_listener.engines.protocol.kuaishou import KuaishouProtocolEngine
      engine = KuaishouProtocolEngine(token_provider=lambda rid: "<你的token>")  # 需 async
      ```
- [ ] **4D.2** 未获取 token 前执行 `protocol_listen` 类测试会得到明确报错：
      `快手需要游客 token（token_provider 未配置...）`——确认该报错清晰（这本身是测试点）

### 4E 视频号受控后台（⚠️ 需实测校准）

- [ ] **4E.1** 准备微信登录态（storageState 文件或首次扫码）
- [ ] **4E.2** 启动引擎（非 headless 便于观察）：
      ```python
      from danmaku_listener.engines.wechat_channels import WechatChannelsEngine
      engine = WechatChannelsEngine(headless=False)
      ```
      [预期] 打开 `channels.weixin.qq.com/platform/live/liveBuild`；
      未登录 → 触发 NEEDS_LOGIN（stderr 提示 + interactive_login 载荷）
- [ ] **4E.3** 扫码后观察自动恢复（`login recovered` 事件）
- [ ] **4E.4** 弹幕接口字段与 `FEED_API_PATTERN` 校准记录（如实测不符，记录响应样例反馈）

### 4F 虎牙（❌ 暂不承诺）

协议 draft（huya-0-draft）：连接/生命周期可跑，但 **payload 不解析**（无消息输出为预期）。
仅验证引擎启动与重连循环：`python -m pytest tests/unit/test_huya_protocol.py -q`（已覆盖）。

---

## §5 系统行为验证（GAP / 重连 / 有界会话）

- [ ] **5.1 断线 GAP**：4A 正常收流中，**断开网络**（禁用网卡/拔线）10 秒再恢复
      [预期] stderr 出现重连日志；恢复后若输出 GAP 消息（reason=network），窗口时间
      与断网时段吻合。注意：B站重连依赖 getDanmuInfo 重新获取 token
- [ ] **5.2 下播裁剪**：对一个即将下播的房间持续监听
      [预期] 下播（LIVE_STATUS_CHANGE live=false）后断线**不应**产生 GAP
- [ ] **5.3 有界会话重建**（视频号/兜底，4h 太长可临时把
      `session_lifetime_seconds` 调小验证）：到期自动重建且前后有
      ENGINE_STATUS `session rebuilt` 事件
- [ ] **5.4 慢速重试**：对一个不存在的房间启动（4A.4 同场景）
      [预期] 每 ~15s 一次重连尝试（慢速封顶），错误不会终止进程

---

## §6 性能验收观测（对照计划验收标准）

- [ ] **6.1 内存基线**：空 serve 运行 10 分钟，任务管理器观察 RSS
      [参考] 预算基线 54.1MB（docs/ops/budget-baseline.md）；应无持续增长趋势
- [ ] **6.2 延迟抽检**：4A 运行中，对比弹幕在直播间页面出现的时间与 JSON 输出的
      `timestamp`（秒级口径，人工抽 5 条估读）
      [验收] 体感 <1s（R3-4 精确口径在契约 v1 定义后落地）
- [ ] **6.3 长稳观察（可选，对照 24h 门禁）**：过夜挂 4A，第二天检查
      内存无显著增长（漂移 ≤10% 门禁）+ 进程存活 + 无未处理异常日志
- [ ] **6.4 压测（可选）**：多开若干协议直连进程聚合观察系统总内存 ≤1.2GB 口径

---

## §7 通过标准汇总

| 项 | 通过条件 |
|---|---|
| 自动化回归 | §1 三项全绿 |
| 离线冒烟 | §2 输出完整契约 JSON、TTHW <1s |
| WS 通道 | §3 鉴权正反向 + 重连不重放 |
| B站直连 | §4A 真实弹幕 JSON 流 + TTHW <1s + 下播错误路径清晰 |
| 斗鱼直连 | §4B 真实弹幕 + 45s 心跳稳定 |
| 抖音 | §4C 环境确认 + 代理捕获（依赖前置完成度） |
| 快手/视频号/虎牙 | §4D/4E/4F 按矩阵边界确认行为与报错清晰 |

---

## §8 问题记录模板

每发现一个问题复制一份填写：

```
### 问题 <编号>
- 发现步骤：§<x.y>
- 平台/命令：<执行的完整命令>
- 预期：<文档 [预期] 内容>
- 实际：<实际现象，粘贴关键 stderr/stdout 片段>
- 复现率：必现 / 偶发 (N/M 次)
- 影响：阻塞 / 降低体验 / 观察项
- 附件：日志文件路径（logs/ 下）
```

测试全部完成后把本文件中勾选状态与 §8 记录反馈给开发侧（或直接进入
/bug-fix 工作流）。
