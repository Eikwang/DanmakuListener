# 小红书直播弹幕监听 Runbook

## 技术路线

受控 Playwright 页面（`www.xiaohongshu.com/livestream/{room_id}`）+ 页内
WebSocket `framereceived` 帧拦截。观众侧无需登录（设备 cookie a1 访问自动
种下；persistent profile `cookie/xhs_profile` 保存）。引擎：`page:xiaohongshu`。

帧结构：JSON 帧 `t==4` → `b.d.b[]` → 每项 `.d` base64 → JSON →
`customData`（JSON 字符串）二次 parse → 业务对象。

## 消息类型支持矩阵（2026-09-30 在播房间 696 条采样实测校准）

| customData.type | 契约消息 | 备注 |
| --- | --- | --- |
| text | DANMU | desc=内容、profile.nickname/user_id |
| audience_join / audience_join_v2 | ENTER_ROOM | 实测 audience_join_v2 为主 |
| praise | LIKE | praise_info.count=本次点赞事件聚合数；profile 无 nickname → **会话内 user_id→昵称学习表反查**（refresh 在线观众名单/text/进场/关注/礼物帧学习，2026-10-03 用户实测昵称显示生效；未命中回退"有人"）（调研推断的 "like" type 实测不存在） |
| gift_dock_and_effect | GIFT | send_user_info.nick_name（下划线命名）/base_gift_info.name/gift_action_info.count |
| follow_emcee | SOCIAL | action=follow |
| share | SOCIAL | action=share |
| gift_comment / gift_settle | 不 emit | 同一次送礼的重复视图（时序实证）——跳过防重复计数 |
| refresh / letter_refresh | 不 emit | 链路活跃信号（静默检测依据）；**refresh 的 room_data.viewers[] 为昵称学习主要来源** |
| light | 不 emit | 进场来源路径（slide/follow_feed），语义待定 |
| live_banner_resource / goods_rank_entrance_im | 不 emit | 运营位/商品榜 |

## 房间参数

直播间页链接（App 分享 → 复制链接）中的数字 id，或纯数字 room_id。

## 待实测校准项

- ~~like 的计数字段名~~（已校准：praise/praise_info.count）
- ~~礼物详细字段~~（已校准：gift_dock_and_effect 全嵌套结构）
- 未登录状态下 WS 是否推弹幕（本次实测未登录可收——若后续风控：登录闭环同 1688 模式）
- 下播时页面行为（当前用 90s 业务帧静默判定）

## 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `xiaohongshu.session.silent` | 90s 无业务帧 | 确认直播中；风控时稍后重试 |
| 页面加载但无消息 | 未开播/链接失效 | 核对直播间页可打开且显示直播画面 |

## 参考

- qdlx2000/xhs-recorder（Playwright 拦截开源实现；其 framereceived 传参 bug 已在本引擎修正）
- CSDN 中控台 longlink 帧结构文章（2024-12）
- BarrageGrab README 支持矩阵（小红书 wss+直播伴侣模式）
- 安全边界：只监听、不发送弹幕（发评论接口不做）
