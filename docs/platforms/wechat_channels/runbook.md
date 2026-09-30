# 视频号直播弹幕监听 Runbook

## 技术路线（2026-09-30 实测定型）

受控**可见**浏览器（常驻不关）打开官方管理后台
（channels.weixin.qq.com/platform/live/liveBuild），网络层拦截
`mmfinderassistant-bin/live/msg` 弹幕轮询响应（wxlivespy 同构解析）。
引擎：`controlled:wechat_channels`，profile `cookie/wxsp_profile`。

**关键实测结论**：
1. **登录态不支持静置恢复**——关闭浏览器后 cookie 快速失效（两次实测
   数分钟内跳 login.html）。登录、监听必须在同一存活 context 完成
   （wxlivespy 同为常驻浏览器）。
2. **页面保持打开即可监听**——liveBuild 落地页在账号有进行中直播时
   自身就轮询 live/msg；"直播→直播管理→进入直播间"导航为增强路径
   （引擎自动执行，失败不阻断）。
3. 侧栏菜单为纯图标（hover 才显名称）——按几何位置点击第 4 项。

## 登录闭环

无登录态 → 可见窗口就地等微信扫码（300s）→ 登录态由存活页面续命。
storage_state 快照模式不可用（实测 34 分钟即失效）。

## 消息解析（wxlivespy 同构校准）

- data.liveInfo：liveStatus/onlineCnt/likeCnt → LIVE_STATUS_CHANGE / ROOM_STATS
- data.msgList：type=1 弹幕、type=10005 进房 → DANMU / ENTER_ROOM
- data.appMsgList：msgType 20009/20013 礼物（base64 payload）、20006 点赞、
  20031 粉丝等级 → GIFT / LIKE / SOCIAL

## 参考

- wxlivespy（MIT，参考项目已不入库——协议结构知识来源）
- 合规：监听主播自己的后台（本人小号登录），只读、不发送
