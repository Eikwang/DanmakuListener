# DanmakuListener → AUTOlive 合并指南（v0.7.0）

> 目标：把独立开发完毕的 DanmakuListener v0.7.0 嵌入 AUTOlive。
> 基线差量：AUTOlive 副本滞留在 **v0.4.0（upstream 7e3aec8，2026-10-06 拷贝）**；
> 当前上游 **v0.7.0（3921e81）**，包内差量 **36 文件 +4713/-46 行**。
> 前置阅读：[autolive.md](autolive.md)（WS 消费契约，仍然全部有效）。

## 1. 集成模型（现状与建议）

- **分发方式**：清单式拷贝——AUTOlive 侧 `Scripts/copy_danmaku.py` 把本仓
  `danmaku_listener/` 整包 + `docs/contract/` 复制进 AUTOlive，写
  `COPY_MANIFEST.json`（内容 SHA256 版本戳）。**非 git submodule**。
- **运行方式（建议保持）**：独立进程 `python -m danmaku_listener serve --web`，
  AUTOlive 经两条通道消费——**WS 8765**（监听消息/回执推送）+ **REST 8086**
  （发送/重登/控制台）。不建议进程内 import 复用引擎：引擎持有浏览器子进程树
  与独立 asyncio 生命周期（ADR-001），耦合会互相拖累。
- **凭证边界**：`cookie/` 目录=引擎写、AUTOlive 只读（settings.py:64 既有约定）。

## 2. 本次差量的三大能力块（v0.4.0 → v0.7.0）

| 能力块 | 内容 | 关键文件 |
|---|---|---|
| 弹幕发送整包（AutoDanmu） | 10/12 平台发送+监听全通；REST/WS 双通道；15 回执码；审计/幂等/熔断 | `senders/`（14 文件全新）+ `web/app.py` send 路由 |
| 登录态工程（F1-F4） | F1 登录态快照/恢复（硬杀免疫）、F2 发送/监听 profile 互斥、F3 WS 帧服务端回环判定、F4 自发声回环；手动重登按钮 | `engines/login_state_store.py`、`web/relogin.py`、各引擎 send 钩子 |
| 滑块自动化与运维套件 | 淘宝 x5sec 简单滑块人味轨迹自动通过 + 有头窗口自动重试 + 双发防线；冷却 3s；四宫格控制台 | `senders/taobao_mtop.py`、`config/settings.py`、`web/static/*` |

完整文件清单（合并后 AUTOlive 侧 git diff 应与此一致）：

- **新增**：`senders/__init__.py`、`senders/{audit,base,bilibili,dom_transient,douyin,guard,huya,kuaishou_douyu,pipeline,registry,resident_session,taobao_mtop,wiring}.py`、`engines/login_state_store.py`、`engines/send_login.py`、`web/relogin.py`
- **修改**：`__init__.py`（0.7.0）、`__main__.py`、`config/{settings,config_store}.py`、`contract/models.py`（+96：COMMAND 类/回执载荷/R39 字段）、`engines/{login_gate,douyin_login,kuaishou_login,protocol/{controlled_base,jd,live1688,taobao,xiaohongshu},wechat_channels}.py`、`push/ws_server.py`、`web/static/{app.js,index.html,style.css}`

## 3. 合并步骤（六步）

### 步骤 1：前置检查

- 上游：DanmakuListener main ≥ `3921e81`（v0.7.0 tag 已推送）；全量测试 691 绿
- AUTOlive：工作区干净；停掉引用 danmaku_listener 的运行中进程

### 步骤 2：拷贝同步（AUTOlive 根目录执行）

```
python Scripts\copy_danmaku.py
```

- 预期输出两段 `[OK]`：`danmaku_listener`（文件数应 ≥ 100+15）与 `docs/danmaku_contract`
- 校验 `danmaku_listener/COPY_MANIFEST.json`：`content_sha256` 变化、`total_files`
  增至 ~115；`danmaku_listener/__init__.py` 的 `__version__ == "0.7.0"`

### 步骤 3：契约版本核对

```
python -m danmaku_listener contract
```

- 契约版本 `1.0.0` 不变（additive-only：新增 COMMAND 类、回执载荷、
  `sent_at`/`content` 字段——消费端忽略未知字段即正确）

### 步骤 4：配置对齐（AUTOlive 侧新增项）

`config/settings.py` 新增/变更的键（INI `[send]` 段 + 通用段）：

| 键 | 默认 | 说明 |
|---|---|---|
| `send_enabled_platforms` | 空 | 启用发送的平台逗号表（建议先 `bilibili` 冒烟） |
| `send_min_interval_seconds` | **3.0** | 限速间隔（v0.7.0 起 30→3；虎牙 35s 内置覆写） |
| `send_min_interval_overrides` | "" | 按平台覆写 JSON（如 `{"huya": 35}`） |
| `send_dry_run` | — | dry-run 开关（冒烟先开） |
| `send_max_length` / `send_dedup_window_seconds` / `send_circuit_threshold` | — | 长度/去重窗/熔断阈值 |
| `send_audit_file` / `send_idempotency_index` | persistence_data/ | 审计与幂等索引路径 |
| `send_window_mode` | headless_new | 发送窗口形态（headless_new 纯后台/minimized/foreground） |
| `ws_token_file` | — | 发送鉴权 token 文件（如 `persistence_data/send_token.txt`） |
| `web_port` | 8080（实跑 8086） | 测试控制台端口，与 ws_port 8765 隔离 |

依赖确认：`quickjs`/`psutil`/`playwright` 均已在主依赖（**无新增依赖**）。

### 步骤 5：运行时数据落位（关键——免全平台重扫码）

拷贝脚本**排除** `cookie/` 与 `persistence_data/`（EXCLUDE_DIRS）——运行时数据
需手动迁移到 AUTOlive 根的同名目录：

```
xcopy /E /I /H D:\AI\DanmakuListener\cookie        D:\AI\AUTOlive\cookie\
xcopy /E /I /H D:\AI\DanmakuListener\persistence_data D:\AI\AUTOlive\persistence_data\
copy  D:\AI\DanmakuListener\persistence_data\send_token.txt D:\AI\AUTOlive\persistence_data\
```

- `cookie/` 携带各平台现役登录态（profile + F1 快照）——迁移后**零重扫**
- `persistence_data/`：`send_audit.jsonl`（审计）/`send_idempotency.json`（幂等）/`send_token.txt`（鉴权）

### 步骤 6：启动与冒烟

```
python -m danmaku_listener serve --web     （AUTOlive 根；或沿用 start-service.bat 看门狗形态）
```

冒烟清单（逐项勾选）：

- [ ] `python -m danmaku_listener contract` 契约版本 1.0.0 一致
- [ ] 控制台 `http://127.0.0.1:<web_port>` 打开：房间列表四宫格（启动/删除/发送/登录）可见
- [ ] 添加房间 → 8765 WS 收到 `business` 消息（HEARTBEAT 10s 周期正常）
- [ ] `POST /api/send-danmu`（Bearer token）一发 B站 → 回执 SENT + 直播间可见单条
- [ ] 房间行"登录"按钮 → 确认后登录窗弹出 → 登录后自动恢复监听
- [ ] `persistence_data/send_audit.jsonl` 落 intent/result 行

## 4. 新能力接入指南（AUTOlive 消费侧义务）

### 4.1 发送 API

- `POST /api/send-danmu`：Bearer token（`persistence_data/send_token.txt`）；
  body `{platform, room_id, content, request_id?}`；**预算 60s**（超时后走对账）
- 回执四态：`sent` / `failed`（reason_code+fix_hint+docs_anchor 三段式）/
  `dry_run` / `unknown`（"可能已送达"——**禁止诱导盲重**）
- 对账：回执丢失时 `GET /api/send-results?request_id=`（60s 中止后 2s 宽限自动查）

### 4.2 R39 自发声去重（AUTOlive 侧义务）

滑块/重试形态下同一弹幕可能合法地出现两条回执路径——**消费端按
`payload.sent_at + payload.content` 去重**（契约 models.py F8/R39 字段已就位）。

### 4.3 推送新增消息

8765 流新增 `COMMAND` 回执与 `ENGINE_STATUS` 登录生命周期事件
（`login.first_login`/`login.timeout_budget_exhausted` 等）——按契约规则
忽略未知 type 即正确；建议 AUTOlive 界面呈现登录事件（引导操作人扫码）。

### 4.4 手动重登按钮（webui）

房间行"登录"按钮：清该平台登录载体（profile/快照/cookie 文件）→ 停该平台
在听房间 → 既有登录门自动弹窗 → 登录后自动恢复监听。虎牙/抖音为双载体
平台（监听+发送），将先后弹两个登录窗口。载体清单见 `web/relogin.py`
`PLATFORM_LOGIN_CARRIERS`。

### 4.5 冷却与风控

- 冷却默认 3s/平台（虎牙 35s 内置覆写）；AUTOlive 侧批量发送请自行叠加
  队列节奏，避免打满 RATE_LIMITED
- 淘宝 ~12h 周期性滑块已全自动通过（人味轨迹 + 无头→有头两级重试 +
  原请求响应捕获防双发）；连续失败回落人工路径时回执会带 fix_hint

## 5. 回滚

- AUTOlive 侧 git 管理 `danmaku_listener/` 副本：`git checkout <旧提交> -- danmaku_listener/ docs/danmaku_contract/` 即回 v0.4.0 基线（旧 COPY_MANIFEST.json 含基线 commit 7e3aec8 与内容戳可核对）
- 运行时数据（cookie/persistence_data）独立于代码，回滚不影响登录态

## 6. 相关文档

- WS 消费契约与背压/心跳：[autolive.md](autolive.md)
- 机读 Schema：[../contract/schema.json](../contract/schema.json)
- 发送运维手册：[../ops/send-runbook.md](../ops/send-runbook.md)
- 发送约束与边界：[../ops/adr-002-danmu-send-constraint-revision.md](../ops/adr-002-danmu-send-constraint-revision.md)
- 进程拓扑：[../ops/adr-001-engine-topology.md](../ops/adr-001-engine-topology.md)
- 变更明细：[../../CHANGELOG.md](../../CHANGELOG.md)（v0.7.0 段）
