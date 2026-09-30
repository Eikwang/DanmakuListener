# 全平台监听测试方案（2026-09-30）

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

### A1. 斗鱼（douyu）

```powershell
python tools/protocol_listen.py douyu <房间号> --duration 300
```
- 房间号示例：斗鱼直播间 URL `www.douyu.com/xxxxx` 中的数字
- 操作：发弹幕 → 送一个礼物
- 预期：`DANMU`(user_name/content)、`GIFT`(gift_name/gift_count)
- 校准点：礼物名是否为可读名称（非类型编号）

### A2. B站（bilibili）

```powershell
python tools/protocol_listen.py bilibili <房间号> --duration 300
```
- 操作：发弹幕 → 送礼物 → （有条件的话）购买 SC
- 预期：`DANMU`、`GIFT`、`SUPER_CHAT`、`ENTER_ROOM`、`ROOM_STATS`
- 校准点：SC 金额字段、礼物名

### A3. 虎牙（huya）

```powershell
python tools/protocol_listen.py huya <房间号> --duration 300
```
- 操作：发弹幕 → 送礼物
- 预期：`DANMU`、`GIFT`
- **校准点（已知待办）：礼物名当前为类型编号**（如 `1`/`2`）——记录编号与
  实际礼物的对照表，用于补礼物映射

### A4. 抖音（douyin）

```powershell
python tools/dy_sign_smoke.py <直播间链接或ID> --duration 300
```
- 操作：发弹幕 → 点赞 → 送礼物
- 预期：`DANMU`、`LIKE`、`GIFT`
- 校准点：签名链路是否仍有效（签名资产失效报三段式）

### B1. 淘宝（taobao）

系统通道：AUTOlive 添加房间 `taobao:<直播间链接>`（mtop 双通道无独立冒烟工具）
- 操作：发弹幕
- 预期：`DANMU`、`ROOM_STATS`
- 校准点：无

### B2. 1688

```powershell
python tools/alive1688_smoke.py <feedId或直播间链接> --duration 300
```
- **注意**：feedId 场次级——下播失效，需重新复制直播间链接
- 操作：发弹幕（用小号在自己直播间或让朋友发）
- 预期：`DANMU`(昵称/内容分离)、`ROOM_STATS`(观看数)
- 校准点：昵称是否为脱敏形态（站点行为，正常）

### B3. 小红书（xiaohongshu）

```powershell
python tools/xiaohongshu_smoke.py "<直播间页链接>" --duration 300 --dump-all
```
- 链接务必加引号（含 `&`）；直播中发弹幕/点赞/送礼
- 预期：`DANMU`、`ENTER_ROOM`、`LIKE`(praise)、`GIFT`(gift_dock_and_effect)、`SOCIAL`(follow/share)
- 校准点：礼物计数在连击时是否正确

### B4. 京东（jd）

```powershell
python tools/jd_smoke.py <liveId或zhibo.jd.com链接> --duration 300
```
- 独立站 `zhibo.jd.com/liveroom?liveId=xxx`，游客可测
- 操作：发弹幕 → 点赞
- 预期：`DANMU`(viewer_send_message)、`ENTER_ROOM`(聚合形态)、`LIKE`、`ROOM_STATS`
- 校准点：进场聚合文案（"xx等N人来了"）是否可接受

### B5. 拼多多（pdd）

```powershell
python tools/pdd_smoke.py "<分享链接>" --duration 300 --dump-all
```
- 首次弹扫码窗口登录（profile 已有登录态则免）；业务消息仅入场/弹幕/点赞（已裁定）
- 操作：发弹幕 → 点赞
- 预期：`DANMU`(live_chat)、`ENTER_ROOM`、`LIKE`、`ROOM_STATS`(观看/点赞总数)

### C1. 快手（kuaishou）

```powershell
python tools/protocol_listen.py kuaishou <主播ID> --duration 300
```
- 首次弹扫码登录（登录态持久化）
- 操作：发弹幕
- 预期：`DANMU`
- 校准点：无

### C2. 视频号（wechat_channels）

```powershell
python tools/wxsp_smoke.py <备注名> --duration 600
```
- **前置：小号开播中**；浏览器窗口保持打开不要关闭（登录态靠存活页面续命）
- 操作：直播间发弹幕/点赞/送礼/让朋友进出
- 预期：`DANMU`、`ENTER_ROOM`、`LIKE`、`GIFT`(含微信币价值)、`SOCIAL`(粉丝等级)、`ROOM_STATS`、`LIVE_STATUS_CHANGE`
- 校准点：礼物 payload 的 reward 字段完整性

## 六、系统通道验收（冒烟通过后做）

AUTOlive 前端逐平台添加房间（`平台:房间参数`），确认：
1. 弹幕列表实时滚动、字段展示正确
2. 登录类平台弹出扫码入口正常
3. `ws_listen.py` 作为消费端替身核对线格式：

```powershell
python tools/ws_listen.py --count 50
```

## 七、信息校准汇总表（测试时重点观察）

| 平台 | 校准项 | 记录方式 |
| --- | --- | --- |
| 虎牙 | 礼物编号→名称对照 | 记录送礼时控制台编号+实际礼物名 |
| 抖音 | 签名资产有效性 | 若报三段式贴日志 |
| 1688 | 昵称脱敏形态确认 | 截图对照 |
| 小红书 | 礼物连击计数 | 送连击礼物观察 count |
| 京东 | 进场聚合文案 | 记录 content 样例 |
| 拼多多 | 点赞聚合数 | 连续点赞观察 count |
| 视频号 | 礼物字段完整性 | --dump-all 后发礼物 |

## 八、问题反馈模板

```
平台：<platform>
现象：<一句话——如"弹幕收到但昵称为空">
操作：<你做了什么——如"发弹幕'测试123'后无输出">
控制台：<相关日志片段（含 ERROR/DEBUG 行）>
时间：<HH:MM>
```

带 `--dump-all` 的平台（小红书/拼多多/京东）会把原始样本写
`*_raw.jsonl`——反馈时提及文件已生成即可，我直接读取分析。

## 九、稳定性加时项（全部通过后选做）

任选 3 个主力平台同时挂机监听 30 分钟（各自独立终端），观察：
1. 无 GAP/ERROR 洪泛
2. 内存无明显增长（任务管理器观察 python 进程）
3. 下播后的三段式表现
