# TODOS

## P2: 客户访谈扩样（2-3 家）
- **What**: 阶段 0 契约校验目前 N=1（单客户）。补 2-3 家电商客户访谈验证契约与产品形态代表性。
- **Why**: CEO 评审 F5——单客户深度绑定有代表性风险。
- **Effort**: human S / CC S | **Depends on**: 阶段 0 契约 v1 初稿
- 来源: /autoplan CEO review F5（2026-09-27，defer 决策）

## P3: 指标导出端点（Prometheus 格式）
- **What**: 每平台消息量/延迟/断线次数的指标端点。
- **Why**: AUTOlive 监控栈定型后按其格式接入；SYSTEM_STATUS 已覆盖最小观测。
- **Effort**: human M / CC M | **Depends on**: AUTOlive 监控栈定型
- 来源: /autoplan CEO review Scope Decision #4（2026-09-27，defer 决策）

## P2: 契约 Schema CI diff 检查（Eng T-2）
- **What**: CI 增加 Schema diff 检查——禁删字段、禁改类型、新字段必须 optional，漂移即红灯。
- **Why**: 契约 v1 承诺 additive-only，无机制防后续 PR 违约。
- **Effort**: human S / CC S | **Depends on**: 阶段 0 契约 Schema 定稿
- 来源: /autoplan Eng review T-2（2026-09-27，defer 决策）

## P3: 虎牙礼物名称表（getPropsList 通路）
- **What**: 虎牙礼物 ID→名称映射。代码路径已就绪（huya_codec.build_gift_list_req /
  decode_gift_list，引擎自动加载）；2026-09 实测 cdnws.api.huya.com 入口对所有
  WupReq 不应答（弹幕推送专用入口）——需改连 wsapi.huya.com（浏览器入口，URL
  带 baseinfo 握手参数，含 base64 Tars 设备信息）后调 PropsUIServer/getPropsList。
  完成前礼物名退化为类型编号。
- **Why**: 前端展示礼物名（当前 GIFT.gift_name="4" 可读性差）。
- **Effort**: human S / CC M（baseinfo 结构逆向 + 实测）| **Depends on**: 无
- 来源: 虎牙实测（2026-09-28）——SDK 2024 的 cdnws+getPropsList 路线已失效

## P3: 抖音登录态备选路线（风控升级预案）
- **What**: 若抖音游客路线被风控拦截（ttwid 拒/WS 403 持续命中，reason_code=
  douyin.room_init.ttwid_failed 等），复用快手登录窗口模式（受控浏览器扫码 →
  storage_state → 引擎带登录 cookie）。
- **Why**: 抖音是风控重点平台；快手已发生同类升级（先例）。触发条件写明：三段式
  reason_code 命中风控特征时向用户提示。
- **Effort**: human S / CC M | **Depends on**: 无（模式已验证）
- 来源: /autoplan CEO 评审 2.3（2026-09-28）

## P3: 抖音开放平台官方 API 调研
- **What**: 调研抖音开放平台直播评论 API：是否覆盖游客监听场景、是否需企业资质、
  限流与费用。若可行则作为长期最稳替代路线评估。
- **Why**: 逆向 WS 本质是 treadmill；官方 API 为合规最优解（若可得）。
- **Effort**: human S / CC S | **Depends on**: 无
- 来源: /autoplan CEO 评审 4.1（2026-09-28）

## P3: webmssdk 上游 release 跟踪（抖音签名资产预警）
- **What**: 定期检查 barrage-fly SDK / hua0512 上游仓库 release——webmssdk.js 更新
  即预警（抖音签名轮换先兆）；刷新流程见引擎 docstring provenance。
- **Why**: 签名资产是抖音引擎单点（失效=全部抖音房间下线，自检可感知但无自愈）。
- **Effort**: human S / CC S | **Depends on**: 无
- 来源: /autoplan CEO 评审 2.2（2026-09-28）

## P3: 抖音增强项（粉丝团/连击合并/表情细分）
- **What**: ① 粉丝团监听（proto 有 FansclubMessage 但字段语义未实测，无法可靠映射）
  ② 礼物连击合并（GIFT.count 当前为 totalCount 累计值透传——**下游勿按增量消费**）
  ③ ChatMessage 表情/emoji 消息细分。
- **Why**: 增强项，不阻塞核心监听；契约 GIFT.count 语义已在计划标注（累计值）。
- **Effort**: human M / CC M | **Depends on**: 实测字段语义样本
- 来源: /autoplan CEO/Eng 评审（2026-09-28）

## 平台专项押后（2026-09-30 用户裁定）

1. **京东直播 wss 直连逆向专项**（P2, XL）— 2026-09-30 实测：京东直播间网页通道服务端封死（桌面/移动 UA 完整模拟均渲染"暂不支持电脑观看"拦截页；live.jd.com 独立站已 302 主站）。唯一路线=wss 直连，需逆向 liveauth token（App 端 sign 走 JNI 需 frida+真机，网页端 token 来源被封；2020 App 端全链路文章+2025 网页端文章付费墙内）。引擎骨架保留（engines/protocol/jd.py+测试，未注册）——网页通道放开或专项启动时继续。房间号特征：App 分享链接 #/{房间号}/live（实测 48473355）。
