# 全平台监听测试方案（v2 · 2026-10-02）

> 一轮测试（10-01/02）已完成 12 平台首轮回归 + 礼物映射全量接入。
> 本版为**二轮完整回归**方案：验证礼物名/价格、上一轮修复项、剩余问题项。

> 十二平台引擎已全部开发完成并各自实测通过。本方案用于**系统化全平台回归测试
> 与消息信息校准**——按卡片逐平台执行，按模板反馈结果。

## 一、测试目标

1. **回归验证**：每个平台在当前代码基线上可稳定监听（消息流动 + 持续 ≥5 分钟）
2. **信息校准**：确认每类消息的关键字段正确（昵称/内容分离、计数、礼物名等）
3. **边界行为**：下播/断网/登录过期的表现符合三段式语义

## 二、验收标准（每平台通用）

| 项 | 通过标准 |
| --- | --- |
| 连接 | 启动后 ≤60s 出现首条业务消息或 ROOM_STATS |
| 消息 | 下方卡片「预期矩阵」中 ✅ 类型全部出现且字段正确 |
| 稳定 | 连续监听 ≥5 分钟无 GAP/ERROR（弹幕稀疏平台可放宽到观察统计流动） |
| 下播 | 主播下播后出现三段式错误（ROUTE_FAILED）或静默提示，而非静默挂死 |

## 三、测试前准备（一次性，约 10 分钟）

```powershell
cd D:\AI\DanmakuListener
# 1. 当前 Python 环境（EDTalk runtime312）依赖齐全性
python -c "import websockets, protobuf, loguru, playwright; print('deps OK')"
# 2. 全量单测基线
python -m pytest tests/ -q    # 预期 515 passed（2 个 quickjs 失败为既有环境项，可忽略）
# 3. 小号登录态盘点（已有 profile 的平台免扫码）
ls cookie/
```

**小号/素材清单**：

| 平台 | 需要的账号/素材 |
| --- | --- |
| B站/斗鱼/虎牙/抖音/京东 | 无需登录（游客可测） |
| 快手 | 小号登录（首次弹扫码） |
| 淘宝/1688/拼多多 | 小号扫码（persistent profile 已有则免） |
| 小红书 | 游客可测（链接带 xsec_token） |
| 视频号 | **小号开播**（实名已完成 ✓） |
| 各平台直播间 | 每平台至少 1 个在播直播间链接/ID（测试时获取） |

## 四、测试分组与顺序

- **A 组·直连轻量**（无需浏览器）：斗鱼 → B站 → 虎牙 → 抖音
- **B 组·受控页面**（无头浏览器）：淘宝 → 1688 → 小红书 → 京东 → 拼多多
- **C 组·登录开播**：快手 → 视频号

每组测完休息一下再继续；单平台卡片执行约 5-10 分钟。

## 五、逐平台测试卡片

### A1. 斗鱼（douyu）——✅ 验收通过（2026-10-05）

```powershell
python tools/protocol_listen.py douyu <房间号> --duration 300 --dump-all
```
- 房间号示例：斗鱼直播间 URL `www.douyu.com/xxxxx` 中的数字
- 操作：发弹幕 → 送礼物 → 观察在线人数
- 预期：`DANMU`、`GIFT`、`ENTER_ROOM`(uenter)、`ROOM_STATS`(oun 在线数 + rss 人气值)
- **验收结论**：弹幕/礼物/进场/在线人数四类全通（TCP 明文 STT 直连）。
  在线人数载体 `oun.un`（dump 实证实时推送）；**点赞/关注无房间级 STT
  推送——协议边界**（关系链事件不进弹幕服务器消息流，采样含点赞对照
  实证）；诊断通道 raw_hook 已就位（未映射 STT 帧落盘）

### A2. B站（bilibili）——✅ 验收通过（2026-10-05）

```powershell
python tools/protocol_listen.py bilibili <房间号> --duration 300 --dump-all
```
- 操作：发弹幕 → 送礼物 → 关注/分享 → 观察在线观众数
- 预期：`DANMU`、`GIFT`(SEND_GIFT_V2)、`ENTER_ROOM`(INTERACT_WORD_V2+ENTRY_EFFECT)、
  `LIKE`(LIKE_INFO_V3_CLICK)、`SOCIAL follow`(f5=2/3 归一)、`ROOM_STATS`(在线)
- **验收结论**：六类消息全通（游客模式，无需登录）。关键实证：
  ①B站礼物/进场切 V2 protobuf——无 schema 递归解码器补映射
  （SEND_GIFT_V2 f10.f2=礼物名协议自带）；②关注与进场共用 INTERACT_WORD
  族，f5=msg_type 分发（1=进场/2=关注/3=分享，分享按裁定归一为关注）；
  ③uid=0 为正常游客路径；④comet 服务端定期轮换连接（1000 断开自动重连，
  正常现象）

### A3. 虎牙（huya）——✅ 验收通过（2026-10-04）

```powershell
python tools/protocol_listen.py huya <房间号> --duration 300 --dump-all
```
- 操作：发弹幕 → 送礼物 → 观察贵宾进场（"XXX驾临直播间"）
- 预期：`DANMU`、`GIFT`(189 项映射+getPropsList 在线表)、`ENTER_ROOM`(6110 贵宾横幅，附 noble 贵族称号/mount 坐骑)
- **验收结论**：弹幕/礼物/贵宾进场全通（Tars TCP 直连）。VipEnterBanner
  布局递归解码实证（tag1=昵称/tag3{tag3}=贵族称号/tag15{tag1}=坐骑；
  tag2 为会话 tid 非用户 uid——不映射）；普通观众无独立进场横幅（协议无此推送）

### A4. 抖音（douyin）——✅ 验收通过（2026-10-03）

```powershell
python tools/dy_sign_smoke.py <房间号> --duration 300 --dump-all
```
- 操作：发弹幕 → 点赞 → 送礼物 → 观察房间信息
- 预期：`DANMU`、`ENTER_ROOM`、`LIKE`、`SOCIAL`、`GIFT`(102 项映射)、`ROOM_STATS`
- **验收结论**：入场/弹幕/点赞/关注/礼物/房间信息全通。关键实证：
  ①SDK 参数对齐页面 WS（1.0.15+uid 派生大数）后消息集合从"仅弹幕"
  恢复完整；②礼物事件只推登录观众（游客连接 1223 条零礼物铁证）——
  登录闭环（扫码一次 cookie 持久化）后打通；③displayType=1 为累计
  观看类，payload 键 viewer_count 对齐前端；④在线观众走
  RoomUserSeqMessage（每 2-6s，total=在线/totalUser=累计 UV），2026-10-04
  实测在线显示正常

### B1. 淘宝（taobao）—— ✅ 验收通过（2026-10-03）

```powershell
python tools/taobao_smoke.py <直播间链接或ID> --duration 300 --dump-all
```
- 操作：发弹幕 / 观察房间信息
- 预期：`DANMU`、`ENTER_ROOM`、`ROOM_STATS`(观看数)
- **验收结论**：入场/弹幕/房间信息全通（mtop 双通道 powermsg 拉取）；
  观看数语义校准同 1688（onlineCount 恒 0 → totalCount/pageViewCount）

### B2. 1688 —— ✅ 验收通过（2026-10-03）

```powershell
python tools/live1688_smoke.py "<直播间链接>" --duration 300 --dump-all
```
- **注意**：feedId 场次级——下播失效，需重新复制直播间链接
- 操作：发弹幕 / 让人进出直播间（触发入场横幅）
- 预期：`DANMU`(昵称/内容分离)、`ROOM_STATS`(观看数)、`ENTER_ROOM`(入场横幅)
- **验收结论**：弹幕/房间信息/入场全通。房间信息语义校准（onlineCount 恒 0，
  观看人数取 totalCount/累计浏览取 pageViewCount）；入场唯一载体为 DOM 横幅
  `DIV.biz-info-message-container`（pull 通道无入场消息，MutationObserver
  探测实证）；昵称脱敏形态（站点行为，正常）

### B3. 小红书（xiaohongshu）

```powershell
python tools/xiaohongshu_smoke.py 570478706428621902 --duration 300 --dump-all
```
- 链接务必加引号（含 `&`）；直播中发弹幕/点赞/送礼
- 预期：`DANMU`、`ENTER_ROOM`、`LIKE`(praise)、`GIFT`(gift_dock_and_effect)、`SOCIAL`(follow/share)
- **验收结论**（2026-10-03）：入场/关注/点赞/礼物/弹幕全通；praise 帧协议
  无昵称——引擎会话内 user_id→昵称学习表反查（refresh 观众名单/弹幕/
  进场/关注/礼物帧学习），未命中回退"有人"

### B4. 京东（jd）——✅ 验收通过（2026-10-03）

```powershell
python tools/jd_smoke.py <liveId> --duration 180 --dump-all
```
- 独立站 `zhibo.jd.com/liveroom?liveId=xxx`，游客可测
- 操作：发弹幕 → 点赞
- 预期：`DANMU`(viewer_send_message)、`ENTER_ROOM`(聚合形态)、`LIKE`(thumbs_up)、`ROOM_STATS`
- **验收结论**：入场/弹幕监听通过（咚咚 IM 明文 JSON，页面自建
  live-ws4 连接免 liveauth 签名）；点赞帧无昵称（聚合帧协议限制）

### B5. 拼多多（pdd）——✅ 验收通过（2026-10-03）

```powershell
python tools/pdd_smoke.py "<直播间分享链接>" --duration 300 --dump-all
```
- 首次弹扫码窗口登录（profile 已有登录态则免）；业务消息仅入场/弹幕/点赞/关注
- 操作：发弹幕 → 点赞 → 关注
- 预期：`DANMU`(live_chat)、`ENTER_ROOM`、`LIKE`、`SOCIAL`(favorite 关注)、`ROOM_STATS`(观看/点赞总数)
- **验收结论**：入场/点赞/关注/弹幕/房间信息全部监听通过（含系统通道
  cookie_dir 配置链修复验证）；titan wss 四层解码稳定
- **会话降级语义（2026-10-05 补）**：登录会话被服务端作废后（cookie 文件
  仍在）服务端降级为游客推送——只剩 live_audience_num/live_chat_notice(enter)，
  弹幕/点赞/关注/点赞总数全部停推（raw_hook 113 条实证）。引擎已加降级
  检测（观众活跃+互动帧全无 90s 判定）→ 自动弹可见窗口重登；重登检测
  改为 cookie 值变化判定。

### C1. 快手（kuaishou）——✅ 验收通过（2026-10-03）

```powershell
python tools/protocol_listen.py kuaishou 3xz96kaifhw8ec4 --duration 300 --dump-all
```
- 首次弹扫码登录（登录态持久化）
- 操作：发弹幕/送礼/点赞
- 预期：`DANMU`、`LIKE`、`GIFT`（名称+快币价值，92 项映射表）
- **验收结论**：监听通过；新礼物"猫粮"（ID 164，1 快币）映射已补——未知
  ID 回退显示编号的机制正常，发现新礼物按此流程补表

### C2. 视频号（wechat_channels）——✅ 验收通过（2026-10-03）

```powershell
python tools/wxsp_smoke.py dw --duration 180 --dump-all
```
- **前置：小号开播中**；无头常驻模式（登录态过期自动弹可见窗口扫码）
- 操作：直播间发弹幕/点赞/送礼/让朋友进出
- 预期：`DANMU`、`ENTER_ROOM`、`LIKE`、`GIFT`(含微信币价值)、`SOCIAL`(关注/粉丝等级)、`ROOM_STATS`、`LIVE_STATUS_CHANGE`
- **验收结论**：弹幕/进场/关注/礼物/总点赞量全部正常；点赞人昵称**严格帧
  驱动**（微信后台偶发推帧，4 次点赞约 1 帧带昵称——协议边界，见 runbook
  "协议边界"节）；观看人数为当前在线口径（后台无累计字段）
- 诊断：serve 启动前 `$env:WXSP_RAW_DUMP = "wxsp_serve_dump.jsonl"`
  → 系统端 live/msg 原始响应落盘

## 六、系统通道验收（冒烟通过后做）

AUTOlive 前端逐平台添加房间（**选项式：平台下拉 + 房间号/链接**，2026-10-05
R2 改版），确认：
1. 三区消息落位：左=弹幕、右上=礼物/点赞/关注、右下=入场/房间信息，
   行格式 `[平台]内容`（如 `[抖音]余一一：主播太有趣了`）
2. 房间列表显示 `[平台名] 房号 状态`，启动/停止/移除按钮正常
3. 房间持久化：添加后重启 serve，列表恢复为「已停止」，可按需启动
4. 登录类平台弹出扫码入口正常
5. `ws_listen.py` 作为消费端替身核对线格式：

```powershell
python tools/ws_listen.py --count 50
```

**✅ 系统通道复测通过（2026-10-05，全部平台）**：前端 v8（全新视觉 +
选项式添加 + 房间持久化按需启停 + 三区显示 + 链接自动识别）全平台实测
通过。当日修复三项随复测收官：①美团 dpurl.cn 短链添加（302 归一 live_id）；
②链接型 room_id 打散 REST 路径致按钮失效（encodeURIComponent 防御）；
③拼多多登录会话服务端作废降级（游客只推入场+观看数）→ 降级检测自动弹窗
重登。多平台并发监听（美团/小红书/拼多多同挂）验证通过。

## 七、信息校准汇总表（测试时重点观察）

**礼物映射已全量接入（2026-10-02）**：虎牙 189 项/快手 92 项/抖音 102 项/
斗鱼 79 项/B站 69 项（编号→名称+价格）；视频号 69 项/小红书 115 项
（名称→价格）；GIFT 消息统一带 `gift_value`（平台币原值 × 数量）。

| 平台 | 二轮校准项 | 记录方式 |
| --- | --- | --- |
| B站 | 礼物名是否正确显示 + 未映射 cmd 日志 | 送礼观察 + `unmapped cmds` 行 |
| 抖音 | 礼物是否出现（method 可观测性）| 送礼观察 + `first-seen method` 行 |
| 斗鱼 | 礼物名/价格 | 送礼对照 dump |
| 美团 | ✅ 协议边界确认（2026-10-05）：弹幕/房间统计（点赞/热度）全通；**进场不进轮询接口**——走 Pike WS 签名保护通道（四轮采样+页面 CDP 抓帧实证，见 TODOS.md #2），dpurl.cn 短链添加已支持 | — |
| 小红书 | ✅ 验收通过（2026-10-03）：五类消息全通+praise 昵称反查，见 B3 节 | — |
| 拼多多 | ✅ 验收通过（2026-10-03）：入场/点赞/关注/弹幕/房间信息全通，见 B5 节 | — |
| 视频号 | ✅ 验收通过（2026-10-03）：严格帧驱动点赞 + 在线口径观看数，见 C2 节 | — |
| 京东 | ✅ 验收通过（2026-10-03）：入场/弹幕全通，见 B4 节 | — |

## 八、问题反馈模板

```
平台：<platform>
现象：<一句话——如"弹幕收到但昵称为空">
操作：<你做了什么——如"发弹幕'测试123'后无输出">
控制台：<相关日志片段（含 ERROR/DEBUG 行）>
时间：<HH:MM>
```

**全部 12 平台冒烟脚本均支持 `--dump-all`**，dump 文件统一 `<platform>_dump.jsonl`
（B站/斗鱼/虎牙/快手走 `protocol_listen.py --dump-all` 写 `<platform>_dump.jsonl`；
1688 为 `1688_dump.jsonl`；抖音为 `douyin_dump.jsonl`）。反馈时提及文件已生成即可，
我直接读取分析。dump 格式统一 `{"ts":..,"kind":"raw|wire","data":..}`。

## 九、稳定性加时项（全部通过后选做）

任选 3 个主力平台同时挂机监听 30 分钟（各自独立终端），观察：
1. 无 GAP/ERROR 洪泛
2. 内存无明显增长（任务管理器观察 python 进程）
3. 下播后的三段式表现
