# 美团直播弹幕监听 Runbook

## 技术路线

mapi 网关 HTTP 轮询直连（`i.meituan.com/mapi/dzu/live/livestudiobaseinfo.bin`），
无需登录 cookie、无需浏览器、无需签名（`csecplatform=4/csecversion=2.4.0` 为
H5 场景固定安全参数；`sharekey` 为观众侧通用分享 key）。引擎：`poll:meituan`。

- 轮询间隔 1.5-2s，响应为**全量倒序快照** `messageVO.msgs[]`，按 `commentId` 有界去重
- 消息判别：顶层 `msgType`（实测 2=聊天→DANMU；其余类型待在播样本校准）
- `liveInfoVo.liveLikeCount/liveHeat` → ROOM_STATS（值变化才 emit）

## 房间参数

| 形态 | 示例 | 说明 |
| --- | --- | --- |
| live_id 数字 | `9496370` | 场次级 ID |
| 分享短链 | `http://dpurl.cn/xxxx` | 运行期 302 解析 liveid |
| 美团链接 | `https://mlive.meituan.com/...?liveid=...` | 正则提取 |

**live_id 是场次级**（与 1688 feedId 同性质）：每次开播产生新 live_id，
下播即失效。重新获取：直播间分享链接（App 分享 → 复制链接）。

## 消息类型支持矩阵

| 类型 | 状态 | 备注 |
| --- | --- | --- |
| DANMU | ✅ 实测 | msgType=2 |
| ROOM_STATS | ✅ 实测 | 点赞数/热度（观看数字段未见） |
| ENTER_ROOM / LIKE / GIFT | ⏳ 待校准 | 快照中应存在对应 msgType，等在播房间样本 |

## 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `meituan.poll.live_ended` | 场次结束/ live_id 无效（endTime 有值或 code!=0） | 开播后重新复制分享链接 |
| 长时间无弹幕 | 场次冷清 | 确认直播中；接口为 1.5s 轮询，延迟正常 |
| 响应非 JSON | 美团网关风控/变更 | 抓 `meituan_snapshot.json`（tools/meituan_smoke.py --dump）比对结构 |

## 参考

- 协议来源：markadc/meituan-live（HTTP 轮询开源实现，2025 实测）
- 商业佐证：BarrageGrab README 支持矩阵（美团 wss/浏览器/系统代理四模式）
- 安全边界：只监听；不发送弹幕；不调用 startlive/stoplive/商品管理等主播端接口
