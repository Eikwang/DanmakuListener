# 前端完善计划：多平台同步监听 + 添加体验 + 房间保存 + 三区显示

> 来源：/autoplan（2026-10-05，用户 4 条需求）
> 状态：**已实施（2026-10-05）**——D1 接受方向修正 + D2 批准实施；554 单测全绿；
> 端到端探针验证（选项添加/链接提取/跨平台共存/单房间启停/重启恢复）全通；
> AUTOlive 拷贝已同步（copy_danmaku.py，100 文件）。
> 基线：main @ ac10edd（12 平台全部收官，530 单测全绿）

## Implementation plan

### R1. 多平台同步监听（需求 1）

**用户原话**：现在只有添加多个同平台的房间进行监听，无法添加不同平台，请优化监听逻辑和消息链路，实现多个平台的实时监听能力。

**探针实证（2026-10-05 11:02，独立 serve 实例）**：
- `POST /api/rooms {"room":"bilibili:23058"}` → `{"success": true, "status": "running"}`
- `POST /api/rooms {"room":"douyu:74960"}` → `{"success": true, "status": "running"}`
- `GET /api/rooms` → 两房间共存。**后端引擎链路已完整支持跨平台并发**（bridge._engine_instances 按平台一实例、_rooms 按 platform:room 键、seq/GAP 按房间隔离）。

**真实根因（前端 UI 层）**：
1. **房间列表渲染 bug（实锤）**：`app.py api_get_rooms` 返回 `{"rooms": [dict,...]}`（数组），`app.js loadRooms` 用 `Object.keys(rooms)` 遍历——数组键为索引 "0"/"1"，界面显示索引数字而非房名，删除按钮 `key.split(":")` 解析出 `platform="0"` → **删除必 404**。多房间时列表 UI 全坏。
2. **输入格式负担**：唯一输入方式为 `douyin:55814568` 拼接格式（placeholder 只示例 bilibili），无平台选择、无链接识别。
3. **AUTOlive 拷贝滞后**：AUTOlive/danmaku_listener 为 10-03 12:03 拷贝（COPY_MANIFEST.json），主仓库 10-04/10-05 的 B站/斗鱼修复不在其中；修复完成后必须跑 `Scripts/copy_danmaku.py` 同步。

**修正方案**（引擎层零改动）：
- F1.1 修 loadRooms：按数组渲染，item 含 platform/room_id/status 全量字段（app.js）
- F1.2 房间行显示 `[平台中文名] 房号 + 状态点`，每行配 启动/停止 按钮（联动 R3）
- F1.3 三区显示后多平台消息自然分流可读（联动 R4）；统计面板 rooms 计数保留分房间视图
- F1.4 部署步：`python Scripts/copy_danmaku.py` 同步 AUTOlive + 重启 serve

### R2. 选项模式添加房间（需求 2）

**用户原话**：改为选项模式，只需要输入房间号或链接，然后选择平台即可添加监听任务。

**方案**：
- F2.1 index.html 添加表单改为：**平台下拉框（12 平台中文标签）+ 单输入框（房间号或链接）**
- F2.2 链接自动识别（后端统一解析，DRY+可测）：`platform_parser.py` 增加 `extract_from_link(text)`——URL 特征匹配平台并提取房间号，各平台链接格式：
  | 平台 | 链接特征 | 提取 |
  | --- | --- | --- |
  | douyin | `live.douyin.com/(\d+)` | 数字房号 |
  | douyu | `www.douyu.com/(\d+)` | 数字房号 |
  | bilibili | `live.bilibili.com/(\d+)` | 数字房号 |
  | huya | `huya.com/(\d+)` | 数字房号 |
  | jd | `zhibo.jd.com/liveroom?liveId=(\d+)` | liveId |
  | 1688 | `live.1688.com/zb/play.html?...feedId=(\d+)` | feedId（场次级） |
  | 其余 6 平台 | 链接结构多样/需登录态 | 前端仅自动选中平台，房号手填 |
- F2.3 API 兼容：`POST /api/rooms` 接受 `{room: "douyin:123"}`（旧格式保留）或 `{platform, room}`（新格式，room 可为纯房号或链接）；前端传 `{platform, room: 原始输入}`
- F2.4 前端粘贴链接时即时检测：输入框 oninput 对已识别平台自动选中下拉项并回填提取的房号（只做展示预填，后端仍是解析权威）

### R3. 房间保存与按需启停（需求 3）

**用户原话**：每次重启后房间信息就没有了，需要增加保存能力，添加好的房间一直保存在房间列表，可以按需启动&停止监听。

**方案**：
- F3.1 持久化：bridge 增加房间注册表文件读写（对齐既有 blocked_keywords.json 先例，`_load_blocked_keywords/_save_blocked_keywords` 同模式）；路径 `persistence_data/rooms.json`（persistence_data 已在 copy_danmaku.py 排除清单——运行数据不入组件分发，惯例一致）；原子写（tmp + rename）
- F3.2 生命周期语义（对齐用户"按需启动&停止"）：
  - 添加 → 启动监听 + 写入注册表（status=running）
  - 停止 → 引擎停 + 注册表保留（status=stopped）
  - 启动 → 引擎启 + status=running（登录类平台走既有登录闭环）
  - 移除（×）→ 引擎停 + 从注册表删除
  - 全部停止 → 全部 stopped，**列表保留**（语义变化：现 stop_all 清空内存列表）
  - serve 重启 → 读注册表，全部以 stopped 状态恢复到列表，**不自动启动**（按需语义；亦避免开机重连风暴）
- F3.3 新 API（additive）：
  - `POST /api/rooms/{platform}/{room_id}/stop`、`POST /api/rooms/{platform}/{room_id}/start`
  - `GET /api/rooms` 响应 item 增补 status 字段（现已有）
- F3.4 UI：房间行按钮组 `启动|停止`（按状态互斥显示）+ `×` 移除；错误容错——rooms.json 损坏时回退空列表并告警

### R4. 三区显示 + "[平台]内容"格式（需求 4）

**用户原话**：左边区域：显示弹幕信息；右边上部区域：显示礼物、点赞、关注信息；右边下部区域：显示入场、房间信息等其它信息。信息显示格式改为"[平台]信息内容"。

**方案**：
- F4.1 布局（style.css grid）：主区域改为两栏——左=弹幕流（大区），右列上下两卡（上=互动流：GIFT/LIKE/SOCIAL/SUPER_CHAT；下=信息流：ENTER_ROOM/ROOM_STATS/LIVE_STATUS_CHANGE）；现有左栏（房间管理+统计+设置+关键词）保留
- F4.2 app.js 重构渲染：`appendMessage(msg)` 按 type 路由三容器；各容器独立上限（弹幕 400/互动 200/信息 200）与独立自动滚动（沿用现有 autoScroll 全局开关，三区联动）
- F4.3 格式：`PLATFORM_NAMES = {douyin: "抖音", douyu: "斗鱼", bilibili: "B站", huya: "虎牙", kuaishou: "快手", taobao: "淘宝", "1688": "1688", meituan: "美团", xiaohongshu: "小红书", pdd: "拼多多", jd: "京东", wechat_channels: "视频号"}`；行格式 `[抖音]余一一：主播太有趣了`、`[斗鱼]成功男人 进入直播间`；类型以色点区分（沿用 TYPE_COLORS）；GAP 标记落弹幕区；告警仍走顶部 alert-bar
- F4.4 兼容细节：ROOM_STATS 三键渲染逻辑保留（在线/观看/点赞）；LIKE 无昵称回退"有人"保留；时钟差标注保留
- F4.5 静态资源缓存版本 v=5 → v=6

## What already exists（复用清单）
- `parse_room_spec`（platform:room 校验，R2 在其上增量）
- bridge 关键词文件持久化先例（R3 同模式）
- `PLATFORM_WARNINGS`（添加响应透出，前端已显示）
- 登录闭环（bilibili/kuaishou/douyin `*_login_then_start`，R3 启动按钮复用）
- `engine.validate_room_id`（R2 后端预校验已接）
- TYPE_COLORS 色板与三栏骨架（R4 布局演进而非重写）

## NOT in scope
- AUTOlive 主程序消费侧（asr/tts 联动、config.json danmaku_listener 节）——另立项
- 引擎层/协议层任何改动（12 平台已收官稳定）
- 代理控制、关键词屏蔽增强
- 房间分组/标签、消息导出

## Review record

### CEO 阶段（策略与范围）

**前提挑战（Premise Challenges）**：
- PC1（需求 1 前提证伪）：用户称"无法添加不同平台"。探针实证后端支持跨平台并发（B站+斗鱼同时 running）。真实瓶颈=前端列表渲染 bug（数组/对象错配→列表显示索引、删除 404）+ 格式输入负担。计划改以"修列表 bug + 选项模式 + 链接识别"达成用户目标，不重写消息链路。**方向修正需用户在 gate 确认**。
- PC2（需求 3 语义补充）：房间保存后"全部停止"语义从"清空列表"变为"全部停止但保留"——更符合运营直觉，但属行为变化，在 gate 说明。

**范围裁定**：四条需求全部落在 web 前端 + bridge 层；引擎层零改动。消息链路"优化"= UI 分区提升多平台可读性 + 列表修复，协议链路已验证无瓶颈。

** NOT in scope / What already exists / dream state delta**：见上节。

**Completion Summary（CEO）**：前提挑战 2 项（PC1 需 gate 确认方向修正）；范围收敛于前端+bridge；无新增平台承诺；无 Error & Rescue 新增项（登录闭环复用既有三段式）。

### Design 阶段（7 维度评分，1-10）
| 维度 | 现状 | 方案后 | 关键动作 |
| --- | --- | --- | --- |
| 信息层级 | 4（单流混杂） | 8 | 三区分类=用户心智模型直接落地 |
| 布局结构 | 6（三栏但中低效） | 8 | 主区两栏+右列上下卡 |
| 一致性 | 6 | 8 | PLATFORM_NAMES/色点统一 |
| 可操作性 | 4（列表索引错乱、删 404） | 9 | 行级启停/移除 + 选项式添加 |
| 状态可见 | 5 | 8 | 状态点+status 字段贯穿 |
| 文案语言 | 5（英文 type 徽章为主） | 8 | 中文平台名+格式化文案 |
| 缺陷修复 | — | — | loadRooms 数组渲染（必改） |

**已裁定问题**：①列表 bug 必修（F1.1）②"全部停止"按钮文案改"全部暂停"以匹配新语义 ③输入框 placeholder 更新为"房间号或直播间链接"。

### Eng 阶段（最后评审，覆盖全部前置修订）

**范围挑战（grounded in code）**：无扩大——全部改动面为 web/static 三件 + bridge.py + app.py + platform_parser.py + settings.py（可选 rooms_file 路径）。引擎/contract/push 层不动，530 单测基线不受影响。

**架构图（改动后）**：
```
浏览器（index.html+app.js v6+style.css）
  │  POST /api/rooms {platform,room}   GET /api/rooms   POST /api/rooms/{p}/{r}/start|stop
  ▼
aiohttp app.py ──> DanmakuBridge（_rooms + rooms.json 持久化）
  │                                    │ 按平台缓存引擎实例
  │                                    ▼
  │             bilibili/douyu/...12×engine（本轮零改动）
  ▼
PushServer.broadcast ──ws──> 前端 appendMessage 按 type 路由三容器
  [弹幕区] DANMU  [互动区] GIFT/LIKE/SOCIAL/SUPER_CHAT  [信息区] ENTER_ROOM/ROOM_STATS/LIVE_STATUS_CHANGE
```

**失败模式注册表**：
| 模式 | 风险 | 缓解 |
| --- | --- | --- |
| rooms.json 并发写 | 单事件循环内顺序化，无真竞态 | 原子写（tmp+rename）兜底 |
| rooms.json 损坏 | 启动崩溃 | try/except 回退空 + 告警条 |
| 重启自动重连风暴 | N 房间同时连 | 恢复为 stopped，按需启动（F3.2） |
| 旧 API 消费方 | ws_listen.py 等 | {room} 旧格式保留（F2.3 additive） |
| 前端缓存 | 旧 js 生效 | v=6 版本参数（F4.5） |
| 1688 feedId 场次级 | 保存的失效链接启动失败 | 启动报错透出 RoomError，行内提示重添加 |

**测试计划**：
- 单测（pytest，runtime312）：①platform_parser 链接提取 7 用例（douyin/douyu/bilibili/huya/jd/1688/非链接文本）②bridge 持久化 round-trip（add→file→新实例 load→stopped 恢复）③start/stop/remove API 状态迁移 ④stop_all 保留列表断言
- 手测（验收）：12 平台选项添加（链接/房号各半）、B站+斗鱼+抖音三房间并发 5 分钟无 GAP 洪泛、重启 serve 列表恢复 stopped、逐个启动验证监听恢复、三区消息落位与"[平台]"格式

**Completion Summary（Eng）**：改动面 7 文件，全部在前端+bridge 层；测试计划落 docs/testing（实施时补）；无 critical gap。

### 共识表
| 议题 | CEO | Design | Eng | 结论 |
| --- | --- | --- | --- | --- |
| 需求 1 根因 | 前端 bug 而非链路（探针证） | 列表重渲染 | API shape 双端修 | 修 UI，引擎不动 |
| 持久化位置 | bridge 文件（先例） | — | persistence_data/rooms.json | 一致 |
| 链接解析位置 | — | 前端预填 | 后端权威解析 | 双端（预填+权威） |
| 重启后行为 | 按需启动 | 状态点可见 | 防重连风暴 | stopped 恢复 |

## Decision Audit Trail

| # | 阶段 | 决策 | 分类 | 原则 | 理由 | 否决项 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | CEO | 需求 1 = 修前端列表 bug+选项模式，不重写消息链路 | Mechanical（探针实证） | P5 显式>聪明 | 后端已支持并发，链路无瓶颈 | 重构 bridge/引擎 |
| 2 | CEO | 引擎层零改动 | Mechanical | P4 DRY | 12 平台已收官，530 测试基线不动 | 顺手重构引擎 |
| 3 | CEO | AUTOlive 同步列为部署步 | Mechanical | P2 半径 | 拷贝分发模式，漏同步=修复不可见 | 各仓分别改 |
| 4 | Eng | 持久化=bridge json 文件 | Taste→推荐 | P3 务实 | 对齐 blocked_keywords 先例，最小实现 | SQLite/RoomStateStore 复用（语义不符：那是引擎 seq 状态） |
| 5 | Eng | 链接解析后端权威+前端预填 | Taste→推荐 | P1 完整 | 后端可测可复用，前端体验即时 | 仅前端正则 |
| 6 | Eng | 重启恢复 stopped 不自动连 | Mechanical | P5 显式 | 用户明说"按需启动"；防重连风暴 | 自动恢复全部监听 |
| 7 | Design | "全部停止"语义改为保留列表 | Taste→gate 说明 | P1 完整 | 用户"按需启停"语义的必然推论 | 保持清空（与 R3 矛盾） |

<!-- autoplan-accepted:ceo -->
- 需求 1 以"修前端列表渲染 bug + 选项模式添加 + 链接识别"实现多平台同步监听；引擎层与协议链路零改动（探针实证后端已支持跨平台并发）。
- 修复完成后必须执行 `python Scripts/copy_danmaku.py` 同步 AUTOlive 拷贝并重启 serve（漏同步=修复对用户不可见）。
- AUTOlive 主程序消费侧改造不在本计划范围。
<!-- /autoplan-accepted:ceo -->

<!-- autoplan-accepted:design -->
- 三区布局按用户指定：左=弹幕、右上=礼物/点赞/关注、右下=入场/房间信息；行格式"[平台中文名]内容"。
- 房间行为：添加即启动并保存；停止保留列表；移除才删除；serve 重启后列表恢复为 stopped 按需启动。
- "全部停止"文案与语义改为"全部暂停"（保留列表）。
<!-- /autoplan-accepted:design -->

<!-- autoplan-accepted:eng -->
- rooms.json 原子写（tmp+rename）+ 损坏回退空列表；路径 persistence_data/rooms.json（不入组件分发）。
- API additive：POST /api/rooms 同时接受 {room}（旧）与 {platform, room}（新）；新增 start/stop 路由；app.js 缓存版本 v=6。
- 单测覆盖：链接提取/持久化 round-trip/start-stop 迁移/stop_all 保留；全量 pytest 基线 530+ 通过。
<!-- /autoplan-accepted:eng -->
