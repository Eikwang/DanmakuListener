# 京东直播弹幕监听 Runbook

## 技术路线

受控 Playwright 页面 + 页内 WebSocket `framereceived` 帧拦截。京东直播间
弹幕走**咚咚 IM 群聊体系**（直播间=群，明文 JSON）；wss 直连需 liveauth
token（App 端 sign 走 JNI 需 frida）——受控页面让页面自己完成鉴权订阅，
引擎免签名只解析（引擎：`page:jd`，persistent profile `cookie/jd_profile`）。

## 房间参数

**直播间页链接**（必需）——京东直播间页 URL 形态多样（live.jd.com/
App 分享短链/带 popId 等），链接整体直达（保留全部风控参数），
room 标识取 popId/liveid/id 参数或链接截断。纯数字 ID 无从打开页面，
会报 `jd.page.parse_failed` 并提示改用链接。

## 帧结构（2020 调研数据点，网页端待实测校准）

- 订阅帧：type=join_live_broadcast（aid=dongdong, appid=jd.mall,
  groupid=房间号, nickName）
- 弹幕：type=chat_group_message，body 含 nickName/content
- 引擎宽容解析：顶层 + body + msgs[] 收集，业务特征（type 枚举或
  nickName+content 组合）过滤；`tools/jd_smoke.py --dump-all` 采样校准

## 消息类型支持矩阵

| 类型 | 状态 | 备注 |
| --- | --- | --- |
| DANMU | ⏳ 待实测 | chat_group_message（字段多候选兼容） |
| ENTER_ROOM | ⏳ 待实测 | join_live_broadcast |
| GIFT / LIKE | ⏳ 待采样 | 京东直播礼物/点赞帧结构未知 |

## wss 直连专项探测记录（2026-09-30，押后裁定后启动）

| 探测 | 结果 |
| --- | --- |
| liveauth 直调（api.m.jd.com/client.action） | 接口可达；无 appid 报参数缺失；带 appid=jdzb 报 `no access`；带 client/uuid 报 `signature verification failed`——**签名校验强制** |
| H5 直播页 6 种历史 URL 形态（wq/pro.m/live.jd.com/live 等） | 全部 403/不存在/空壳 |
| PC 商详页直播窗（item.jd.com，用户房间商品实测） | 强制登录墙（passport.jd.com 重定向） |

**结论**：任何路线都需要（登录京东账号 cookie + 签名算法）或 bypass。
需代码级开源实现支撑（liveauth 参数构造/sign 算法）——专项调研进行中。

## 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `jd.page.parse_failed` | 用了纯数字 ID / 链接失效 | 使用直播间分享链接 |
| `jd.session.silent` | 120s 无业务帧 | 确认直播中；风控时稍后重试 |
| 页面加载但零消息 | 帧结构与 2020 数据点差异大 | `--dump-all` 采样后校准 |

## 参考

- CSDN 京东直播 App 全链路文章（2020-12，liveauth/frida JNI/wss 订阅帧）
- CSDN 网页端分析（2025-01，wss://live-ws4.jd.com token 鉴权，细节付费墙）
- BarrageGrab README 支持矩阵（京东 wss+直播伴侣模式）
- 安全边界：只监听、不发送弹幕
