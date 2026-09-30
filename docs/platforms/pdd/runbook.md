# 拼多多直播弹幕监听 Runbook

## 技术路线

受控 Playwright 页面 + 页内 WebSocket 二进制帧拦截。页面 JS 自行完成
wss 握手/入组/心跳/ACK（上行协议未公开——受控页面无需逆向），引擎只
解码下行（引擎：`page:pdd`，persistent profile `cookie/pdd_profile`）。

## 下行帧结构（2025 公开协议分析实证，四层解码）

1. 16 字节大端固定包头：magic i16 + cmd i16 + ctx i32 + reserve i32 + bodyLen i32
2. TitanPayload protobuf：field1=command(str) / field10=body(bytes) /
   field14=compress(varint)
3. compress==1 → body gunzip
4. MulticastLite protobuf：field1=bizType / field2=groupId / field3=msgId /
   field4=payload(bytes) / field5=needAck
5. payload → UTF-8 → JSON：message_type / live_msg_id / push_mills /
   checked_show_id / message_data；弹幕在 `message_data.live_chat_list[]`
   （uid/nickname/chat_message/sub_type/chat_sub_type/can_reply）

## 消息类型支持矩阵（2026-09-30 在播房间 450+ 条采样实测校准）

| message_type | 契约消息 | 备注 |
| --- | --- | --- |
| live_chat | DANMU | message_data.live_chat_list[]（chat_message/uid/nickname/sub_type/can_reply）——与调研形态一致，实测命中 |
| live_chat_notice | ENTER_ROOM / SOCIAL | notice_type: enter→ENTER_ROOM、favorite→SOCIAL(follow)、group_open（开团运营位）不 emit |
| live_chat_ext_v2 | LIKE / SOCIAL | sub_type: 121(thumb_up_chat)→LIKE、116(favor)→SOCIAL(follow)、120(buy_style)→SOCIAL(buy)；body.title/content |
| live_audience_num | ROOM_STATS | live_audience_num 观看数 |
| show_thumb_up_count | ROOM_STATS | total_count 点赞总数 |
| live_gift_rank | ⏳ 待采样 | 礼物榜形态（真实礼物事件待样本） |
| anchor_rank_change / anchor_acting_notice | 不 emit | 主播榜/讲解通知 |

## 房间参数

**直播间页链接**（必需）——App 分享短链（mobile.yangkeduo.com/...，带
_live_share_token 等参数）可在桌面浏览器打开，链接整体直达保留全部参数。

## 登录（已实测闭环）

- 弹幕仅登录会话推送（调研+实测双重实证）
- 登录闭环：无头未登录 → 自动弹可见窗口 → 用户手动登录 → 恢复无头
- **实测登录 cookie：`PDDAccessToken` / `pdd_user_id` / `pdd_user_uin`**
  （日志动态差异检测实证）——候选列表已据此确认
- 登录态 persistent profile 持久化，后续免登录

## 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `pdd.page.parse_failed` | 纯数字 show_id / 链接失效 | 使用直播间分享链接 |
| `pdd.session.silent` | 120s 无业务帧 | 确认直播中+登录态；风控时稍后重试 |
| 解码 0 条但 WS 有流量 | 帧结构与 2025 分析差异 | `--dump-all` 采样后校准 |

## 参考

- CSDN PDD wss hex Protobuf 解析全流程（2025，解码四层结构+JS/Python 代码）
- CSDN PDD wss protobuf 确认文章（2023，网页端 F12 可见 WS）
- BarrageGrab README 支持矩阵（拼多多 wss/浏览器/系统代理/直播伴侣四模式）
- 安全边界：只监听、不发送弹幕（调研明确 can_reply 字段存在但我们不发送）
