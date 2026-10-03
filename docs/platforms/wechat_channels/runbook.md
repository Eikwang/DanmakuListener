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
- data.appMsgList：msgType 20009/20013 礼物（base64 payload）、20006/20122
  点赞（20122 为新版，base64 payload 带 wording；昵称均在 fromUserContact）、
  20078 关注（base64 payload 带 wording）→ GIFT / LIKE / SOCIAL

## 协议边界（2026-10-03 双通道 dump 实证）

1. **点赞人帧偶发推送**：4 次点赞仅 1 次伴随昵称帧（20006）——点赞人
   昵称只在微信后台推帧时可得，推送时机由微信控制。用户裁定**严格帧
   驱动**：无帧时不合成匿名点赞，仅 likeCnt（总点赞量，每次点赞都实时
   准确）变化。诊断方法：serve 启动前 `set WXSP_RAW_DUMP=path`，系统端
   live/msg 原始响应落盘。
2. **观看人数为当前在线口径**：liveInfo 无累计观看字段（App 端"X 人
   观看"为累计口径，后台不提供）。onlineCnt 波动（如 0↔1）与观众进出
   吻合，属正常值。
3. liveInfo 多形态：data.liveInfo（驼峰键）与 data.live_info（小写键）
   并存于不同响应——解析字段级逐键回退。

## 网页常驻问题（2026-10-02 用户实测 + 技术方案）

**现象**：关闭监听浏览器窗口/AUTOlive 后无法继续监听。

**根因**：视频号后台登录态不支持静置恢复（cookie 由存活页面续命）——
浏览器窗口是登录态的唯一载体。

**技术方案（按推荐度）**：

1. **serve 进程解耦（推荐）**：danmaku serve 注册为 Windows 独立服务
   （NSSM/计划任务），AUTOlive 主程序仅作消费者——主程序重启/关闭不影响
   监听。视频号窗口由 serve 托管保持存活（最小化即可，勿关闭）。
2. **自动恢复（已实现）**：窗口被手动关闭 → 引擎检测 TargetClosed →
   5s 后自动重启窗口 → 登录态热（进程刚退出）直接恢复；冷（静置过）
   则重新弹出扫码。重建时发 ENGINE_STATUS 明确提示。
3. **操作规范（过渡）**：视频号监听期间最小化窗口勿关闭；AUTOlive 关闭
   前先在系统里移除视频号房间（优雅停止）。

**后续演进项（TODOS 登记）**：CDP attach 用户真实 Chrome（复用用户登录态，
无独立窗口）——复杂度高，暂缓。

## 参考

- wxlivespy（MIT，参考项目已不入库——协议结构知识来源）
- 合规：监听主播自己的后台（本人小号登录），只读、不发送
