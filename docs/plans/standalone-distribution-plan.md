<!-- /autoplan restore point: "C:\\Users\\admin\\.gstack\\projects\\DanmakuListener\\master-autoplan-restore-20260928-101735.md" -->
# Implementation Plan: 独立分发版（前端接轨新引擎 + 设置面板 + 分发准备）

Generated: 2026-09-28 | Branch: master | Status: DRAFT（CEO 记录完成，待 spec 评审与后续阶段）
上轮依据: docs/plans/web-test-console-plan.md（W1-W3 已交付：契约桥接+前端 v2+端到端验证）
用户裁定: web 前端从测试控制台升级为**独立弹幕监听系统的正式前端**（可分发产品）；AUTOlive 集成（8765 PushServer）保留为可选通道

## Implementation plan

### 目标

让 danmaku_listener 成为**独立可分发的弹幕监听系统**：
1. 前端与新引擎接轨——房间管理接入阶段 1-5 registry 引擎（B站/斗鱼/虎牙/快手/视频号协议直连），不再依赖旧浏览器路由
2. 相关参数可在前端设置——设置面板读写 TOML 配置（有界参数白名单）
3. 分发准备——pyproject 完善 + wheel 构建 + 安装即用

### 架构概览

```
浏览器（独立系统主界面，web_port 8080）
  ├── /static          → 前端 v3（房间管理接新引擎 + 设置面板 + 告警/统计已有）
  ├── /api/rooms       → 房间管理（升级：registry 引擎路由）
  ├── /api/config      → GET/PUT 参数设置（新增，白名单校验+TOML 持久化）
  ├── /api/status      → 引擎快照（已有）
  └── /ws              → 契约 v1 线格式（已有）
bridge.py → registry 引擎实例（每房间 start/stop/restart）
8765 PushServer（AUTOlive 可选集成通道，不变）
```

核心变更：**房间管理从旧 listener 路由切换到 registry 引擎**（上轮遗留：协议引擎未接入
web 可用路径）；配置读写 API + 前端设置面板；分发打包。

### 阶段分解

**阶段 S1：registry 引擎接入房间管理（含 spec 修复 1/3/4/8/9/10/11）**
1. **平台白名单对齐**（spec 问题 3）：`utils/platform_parser.py` SUPPORTED_PLATFORMS 更新——移除 taobao/weixin（无引擎，round2 C5：影响旧路径解析，记入 CHANGELOG 破坏性变更），加入 huya/wechat_channels；与 registry.PLATFORM_ENGINES 对齐
2. **add/remove/stop/restart 路由全切换**（spec 问题 8，round3 C-2 补齐）：`bridge.py` 的 add_room **与 remove_room/stop_all/房间重启** 一并切换到 registry 引擎实例缓存（否则新引擎房间无法停止——功能断裂）；registry 扩展 douyin 分支（DouyinProxyEngine 桥接）。**get_default_engine 契约**（round2 L2）：保留原样不动（旧 listener 路径仍用），bridge 不再调用它——无行为影响
3. **引擎粒度裁定**（spec 问题 11，round2 L4；round3 C-1 补尾部）：协议引擎（bilibili/douyu/huya/kuaishou）**每平台一实例**（BaseEngine 多房间设计），bridge 持有实例缓存 dict 复用；**生命周期尾部**：最后房间 stop 时实例保留于缓存但调用 stop(room_id) 断开该房间底层连接（无房间的协议引擎不维持连接——BaseEngine 语义天然支持，无空转重连流量）；视频号**每房间一实例**且随房间 stop **销毁实例**（释放 BrowserContext 防泄漏）；S1.10 补生命周期测试
4. **直通归一**（spec 问题 9；round3 L-2 补校验）：bridge 对引擎消息过滤/归一——**仅 `to_wire()` 形状输出**（含 category+type+完整信封字段）直通；其余一切（ad-hoc dict 如 reconnect_success、畸形 dict）包装为 ENGINE_STATUS（裁定理由：RECOVERED 需 after_seconds 必填，ad-hoc 无此时长数据）——**免检直通不存在**，防止碰巧带 category 键的畸形 dict 污染契约流；S1.5 测试覆盖
5. **行为保持**（spec 问题 10）：关键词过滤改作用于 UnifiedMessage 的 DANMU 载荷（content 检查）；引擎错误归一 ROUTE_FAILED 三段式；现有 web 行为（AC-007/AC-018/BR-005）等价保持并测试
6. **可用性 warnings**（spec 问题 4）：add_room 响应携带 warnings（huya=draft 待校准、kuaishou=游客 token 待验证、wechat_channels=接口结构待校准）；验收标准补充
7. **douyin 单进程语义**（spec 问题 6，round2 L3）：web 单进程模式**一律 501**（桥接预留——IPC 接线不在范围，即使代理进程在跑也无消息通路）；README 写明例外与双进程运维指引
8. **错误语义**（round1 问题 3 错误语义部分）：未注册平台 add_room → RoomError 400（含注册表清单），registry KeyError 捕获转译
9. 前端呈现（spec C1）：add_room 响应的 warnings/501 错误在前端房间列表与错误区显示（几行 JS）
10. 单元测试：registry 路由（**六平台**类型含 douyin 桥接分支）、房间生命周期、直通归一、warnings、douyin 501、平台白名单

**阶段 S2：设置面板（含 spec 修复 2/7/12）**
1. `GET /api/config`：白名单参数当前值（分组：通道 ws_port/web_port、引擎 max_rooms/fast_retry_max/slow_retry_cap_seconds、缓冲 bus_ring_capacity/bus_dedup_window_seconds、会话 session_lifetime_seconds）
2. `PUT /api/config`（round2 C3）：白名单校验 → 写入目标文件——默认写 `config.local.toml`；显式 --config 模式下**跟随 --config 文件写入**（GET 标注主导来源）；返回生效方式清单（**统一声明全部需重启**，spec 问题 12）。
   **TOML 键映射表**（round2 L1：与 load_toml_overrides 嵌套规则 `{节}_{键}==Settings字段` 一致）：
   | 参数 | TOML 写法 |
   |---|---|
   | ws_port | [ws] port |
   | web_port | [web] port |
   | bus_ring_capacity | [bus] ring_capacity |
   | bus_dedup_window_seconds | [bus] dedup_window_seconds |
   | max_rooms / fast_retry_max / slow_retry_cap_seconds / session_lifetime_seconds | 平铺键（无可用节前缀） |

   **写入策略**（round3 C-3）：引入 **tomlkit** 依赖（保留注释与键序重建文件，S3.2 依赖清单列入）；S2.6 增补用例「已含节的文件 + 平铺键追加」——平铺键必须写在首个节头之前（TOML 语法约束），tomlkit 天然保持位置
3. **serve 默认加载**（spec 问题 2，round2 C2；round3 L-1 补植入机制）：danmaku-serve 启动时默认加载 `config.local.toml`（显式 --config 优先，文件缺失静默）。植入机制：`get_settings` 改造为支持模块级覆盖实例（如 `set_settings(Settings(**overrides))` 设置模块变量，get_settings 优先返回之；lru_cache 无插入 API，不能只 cache_clear——round3 L-1），确保 web app/bridge/引擎全部拿到新值
4. **.gitignore 验证**（spec 问题 7）：坏行已在修复轮清理，本项为验证性检查（config.local.toml 忽略生效）
5. 前端设置面板（右栏「设置」区可折叠）：分组表单、保存按钮、重启提示、当前值回显、校验错误内联
6. 单元测试：GET/PUT 往返、白名单外拒绝、TOML 持久化+默认加载、校验错误结构、gitignore 有效性

**阶段 S3：独立分发准备（含 spec 修复 1/5）**
1. **web 包纳入分发**（spec 问题 1）：web/ 迁移为 `danmaku_listener/web/`（包内子模块），同步更新导入与测试；static/ 与 blocked_keywords.json 作 package_data 进 wheel
2. pyproject 完善：license/authors/readme/classifiers、extras 分组（douyin=mitmproxy、wechat=playwright、all）
3. `python -m build` 构建 wheel + 干净 venv 安装验证（`danmaku-serve --web` 可用）
4. **wechat_channels NEEDS_LOGIN 范围裁定**（spec 问题 5）：前端告警呈现已交付（上轮 W2 QR 渲染）；扫码回传交互列入后续（NOT in scope 增补）
5. README 快速开始重写（安装→启动→浏览器打开→添加房间；**抖音例外写明**：需独立代理进程，spec 问题 6）
6. CHANGELOG（v0.3.0：六平台引擎+契约 v1+测试控制台+独立分发）

### 验收标准

- 前端添加 `bilibili:<真实房间号>` → BilibiliProtocolEngine 真实直连（对照 tools/protocol_listen.py 行为），弹幕流渲染
- 前端添加 `douyu:<房间号>` → 同上（douyu-1）
- 设置面板修改 `bus_ring_capacity` → config.local.toml 出现该键 → 重启后 GET /api/config 回显新值
- `pip install dist/*.whl` 于干净 venv → `danmaku-serve --web` 一键启动完整系统
- add_room 响应含引擎可用性 warnings（huya/kuaishou/wechat_channels 平台）
- add_room(douyin) **一律返回 501** 与清晰提示（web 单进程模式无消息通路，无论代理进程是否在跑——round3 N-1 一致化；README 例外说明）
- 现有 619 测试无回归；新增测试全绿

### 依赖与前置

- registry 引擎（阶段 6 已交付）；contract.legacy（阶段 0）；PushServer 单源（上轮 W1）
- `python -m build` 需安装 build 包（分发验证时）

### 不在范围（NOT in scope）

- AUTOlive 集成变更（8765 PushServer 冻结）
- 弹幕发送能力（只监听）
- 消息持久化/历史存储
- 移动端适配
- 虎牙 payload 解析/快手 token 签名（协议实测项，引擎骨架已就绪）
- 视频号扫码回传交互（前端告警呈现已交付；回传列后续，spec 问题 5）
- 抖音 IPC 接线（web 单进程模式降级为桥接预留，独立进程运维见手册，spec 问题 6）


<!-- autoplan-accepted:ceo -->
- 房间管理路由切换：web 前端 add_room 按平台走 engines/registry.build_engine 新路由（不再经旧 listener 浏览器路由）；旧 DanmakuListener 保留给包导入用户（非 web 路径），web 测试同步更新
- 引擎可用性透明：add_room 响应携带 warnings（huya=draft 待抓包校准、kuaishou=游客 token 待验证、wechat_channels=接口结构待校准），前端可见
- config.local.toml 加入 .gitignore（本地配置不入库）
- 分发分层：核心 wheel 轻量（aiohttp+websockets+pydantic）；mitmproxy/playwright 走 extras 可选组（douyin/wechat_channels）
- AUTOlive 8765 PushServer 冻结不变；只监听边界不变
<!-- /autoplan-accepted:ceo -->


<!-- autoplan-accepted:design -->
- 设置面板右栏「设置」区可折叠：分组表单（通道/引擎/缓冲/会话）、数字输入+说明、保存按钮、重启提示、当前值回显、校验错误内联
- 继承上轮色板/字体栈/告警样式（无新增设计系统决策）
<!-- /autoplan-accepted:design -->


<!-- autoplan-accepted:dx -->
- 独立分发 DX：`pip install` → `danmaku-serve --web` → 浏览器一键链路；README 快速开始重写（安装/启动/添加房间/抖音例外）
<!-- /autoplan-accepted:dx -->


<!-- autoplan-accepted:eng -->
- bridge.py add/remove/stop/restart 全路由切换 registry 引擎实例缓存（协议每平台一实例+生命周期尾部裁定；视频号每房间销毁）
- 直通归一：仅 to_wire() 形状直通，其余包装 ENGINE_STATUS；关键词过滤作用于 DANMU 载荷
- douyin web 单进程一律 501（桥接预留）；README 双进程例外
- /api/config GET/PUT：白名单 8 参数、TOML 键映射表、tomlkit 写入、Settings 试构造校验、统一需重启声明
- config.local.toml 默认加载：get_settings 模块级覆盖实例植入
- 测试：registry 路由六平台/生命周期/直通归一/config 往返+持久化+默认加载/白名单拒绝/构建安装验证
<!-- /autoplan-accepted:eng -->
## Review record


## Design/DX/Eng 评审记录（2026-09-28，[single-model]，compact）

### Design（Phase 2，UI 面窄：设置面板）
- Pass 1 IA 7/10（设置面板右栏折叠区，复用既有三栏模式）；Pass 2 状态 7/10（校验错误内联已入计划）；Pass 3 Journey 6/10（设置→保存→重启提示弧线）；Pass 4 Slop 8/10（继承上轮色板与字体栈）；Pass 5 系统 8/10（复用变量）；Pass 6 响应式 7/10（继承）；Pass 7 无未决
- 义务块见下

### DX（Phase 2.5）
- 独立分发大幅改善 DX：`pip install` → `danmaku-serve --web` → 浏览器（一键链路）；GS 9/API 8/Docs 8（README 重写）/Upgrade 7（v0.2→v0.3 迁移指南已有基础）/DevEnv 9/Measure 7。Overall 9/10
- 无新发现（安装链路即本计划 S3 主体）

### Eng（Phase 3）
- Scope Challenge：~8 文件；registry 路由+配置 API+打包分层清晰；autoplan never reduce ✓ accepted as-is
- 发现与采纳：E1 add_room 旧 listener.start 调用残留清理（registry 路由下不再调用）；E2 rooms API 格式（dict，前端已兼容）；E3 config PUT 安全=loopback 无 token（与 WS 一致，可选 token 复用）；E4 tomlkit 写失败→临时文件+原子替换
- Failure Modes：bridge 映射遗漏→ENGINE_STATUS 兜底+单测；tomlkit 写失败→告警+保留旧配置；无 CRITICAL GAP
- 测试计划：registry 路由（六平台）/生命周期（add→stop→re-add 共享实例）/直通归一（to_wire 形状校验）/config GET-PUT 往返/TOML 持久化+默认加载/白名单拒绝/构建安装验证 → 并入测试计划工件

```
ENG DUAL VOICES — CONSENSUS TABLE: Codex unavailable（PATH 层 WinError 2，第 4 次）→ 6 维度 N/A；native 有条件通过
```

<!-- autoplan-accepted:design -->
- 设置面板右栏「设置」区可折叠：分组表单（通道/引擎/缓冲/会话）、数字输入+说明、保存按钮、重启提示、当前值回显、校验错误内联
- 继承上轮色板/字体栈/告警样式（无新增设计系统决策）
<!-- /autoplan-accepted:design -->

<!-- autoplan-accepted:dx -->
- 独立分发 DX：`pip install` → `danmaku-serve --web` → 浏览器一键链路；README 快速开始重写（安装/启动/添加房间/抖音例外）
<!-- /autoplan-accepted:dx -->

<!-- autoplan-accepted:eng -->
- bridge.py add/remove/stop/restart 全路由切换 registry 引擎实例缓存（协议每平台一实例+生命周期尾部裁定；视频号每房间销毁）
- 直通归一：仅 to_wire() 形状直通，其余包装 ENGINE_STATUS；关键词过滤作用于 DANMU 载荷
- douyin web 单进程一律 501（桥接预留）；README 双进程例外
- /api/config GET/PUT：白名单 8 参数、TOML 键映射表、tomlkit 写入、Settings 试构造校验、统一需重启声明
- config.local.toml 默认加载：get_settings 模块级覆盖实例植入
- 测试：registry 路由六平台/生命周期/直通归一/config 往返+持久化+默认加载/白名单拒绝/构建安装验证
<!-- /autoplan-accepted:eng -->

## 前端-分发轮次决策审计

| # | 阶段 | 决策 | 分类 | 原则 | 理由 |
|---|---|---|---|---|---|
| 1 | CEO | registry 路由全切换（含 remove/stop） | 机械 | P1 | spec C-2 功能断裂 |
| 2 | CEO | 引擎可用性 warnings | 机械 | P1 | CEO-2 |
| 3 | CEO | douyin web 单进程一律 501 | 机械 | P5 | spec L3/N-1 |
| 4 | CEO | 分发分层 extras | 机械 | P2 | CEO-4 |
| 5 | Eng | 直通归一 to_wire 形状校验 | 机械 | P1 | spec L-2 |
| 6 | Eng | config API 白名单+tomlkit+试构造校验 | 机械 | P1/P5 | spec C-3/L-1/L-3 |
| 7 | Eng | 参数统一需重启声明 | 机械 | P5 | spec 问题 12 |

## Reviewer Concerns（0H 规格评审 3 轮，7 项 round3 修复未经第 4 轮验证——如实标注）

round 1→2→3：6/10（13 项）→ 7/10（13 项）→ 7/10（7 项）。第 3 轮为上限，以下 7 项修复已写入计划但未经第 4 轮独立验证（评审员结论：「局部修订，不动摇架构」）：

- **C-1** 引擎生命周期尾部（实例保留缓存但断开连接；视频号随房间销毁）——S1.3
- **C-2** remove/stop/restart 路由全切换（功能断裂风险已闭）——S1.2
- **C-3** TOML 写入策略（tomlkit 依赖+S2.6 用例）——S2.2/S3.2
- **N-1** douyin 501 一致化（验收标准已改）——验收 6
- **L-1** settings 植入机制（模块级覆盖实例，非仅 cache_clear）——S2.3
- **L-2** 直通仅限 to_wire() 形状（防畸形 dict 污染）——S1.4
- **L-3** PUT 值校验规则（Settings 子集构造+错误转译）——S2.2/S2.6



<!-- autoplan-accepted:ceo -->
- 房间管理路由切换：web 前端 add_room 按平台走 engines/registry.build_engine 新路由（不再经旧 listener 浏览器路由）；旧 DanmakuListener 保留给包导入用户（非 web 路径），web 测试同步更新
- 引擎可用性透明：add_room 响应携带 warnings（huya=draft 待抓包校准、kuaishou=游客 token 待验证、wechat_channels=接口结构待校准），前端可见
- config.local.toml 加入 .gitignore（本地配置不入库）
- 分发分层：核心 wheel 轻量（aiohttp+websockets+pydantic）；mitmproxy/playwright 走 extras 可选组（douyin/wechat_channels）
- AUTOlive 8765 PushServer 冻结不变；只监听边界不变
<!-- /autoplan-accepted:ceo -->

## CEO 评审记录（2026-09-28）

- **0A 前提**：用户第三次方向裁定——从「AUTOlive 组件」升级为「独立可分发系统」。直接解决「监听系统被锁定在 AUTOlive 生态」的产品边界限制，与 12 个月理想态（可运营产品）一致 ✓
- **0B 复用**：registry（阶段 6）、contract.legacy（阶段 0）、TOML 配置面（阶段 0）、PushServer 单源（上轮 W1）——全部已交付，新代码集中在路由切换+配置 API+打包 ✓
- **0C 梦想态**：独立分发是「协议失效→适配→发布可运营流水线」的产品载体；AUTOlive 与独立部署双形态并存
- **发现**：CEO-1（中）旧路由切换兼容性→裁定 registry 新路由+web 测试更新；CEO-2（中）引擎可用性透明化（draft/token 平台加房间的用户困惑）→ add_room warnings；CEO-3（低）config.local.toml 入 gitignore；CEO-4（低）分发分层 extras
- **复杂度**：~8 文件（bridge/registry/设置 API/前端面板/pyproject/README），结构清晰分层（路由/配置/分发）


（评审流水线尚未开始——各阶段评审结论将写入本节。）
