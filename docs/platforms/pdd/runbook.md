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

## 消息类型支持矩阵

| 类型 | 状态 | 备注 |
| --- | --- | --- |
| DANMU | ⏳ 待实测 | live_chat_list[].chat_message；sub_type 区分待采样 |
| GIFT / LIKE / ENTER_ROOM | ⏳ 待采样 | message_type 枚举待真实样本 |

## 房间参数

**直播间页链接**（必需）——拼多多直播间网页 URL 形态待实测
（App 分享短链 dp.pinduoduo.com / Web 直播页），链接整体直达。

## 登录与风控

- 调研实证：拼多多弹幕需扫码登录 cookie；风控较严
- 未登录行为待实测——若 120s 静默三段式，考虑登录闭环（1688 同款
  NeedLoginVisible 模式，persistent profile 持久化登录态）

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
