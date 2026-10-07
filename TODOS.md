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

1. ~~**京东直播 wss 直连逆向专项**（P2, XL）~~ **✅ 已关闭，无需实施（2026-10-03）**
   — 当初启动理由：京东直播间网页通道服务端封死，wss 直连是"唯一路线"。
   后用户发现 `zhibo.jd.com/liveroom?liveId=` 独立站突破封死，受控页面方案
   验收通过（入场/弹幕，2026-10-03）——**专项初衷已被替代，逆向无必要**。
   历史探测记录存 docs/platforms/jd/runbook.md；若未来受控页面被封，
   可从该记录重启评估（引擎已注册 `page:jd`，无遗留骨架问题）。

2. ~~**美团进场监听（Pike WS 逆向）**（P3, XL）~~ **按协议边界关闭（2026-10-05 用户裁定）**
   — 四轮采样实证：轮询接口（livestudiobaseinfo.bin，快照恒 10 条增量）
   无进场形态（1630+ 条全 msgType=2 聊天）；页面进场横幅走独立 Pike IM
   长连接（wss://pike-room-webhl.meituan.com/pike/?bizId=dzu_live_pike，
   engine.io v3），登录帧含 H5guard signature 风控签名，且探测期间已触发
   3D 点选验证码。用户在"受控页面拦帧（拼多多模式，常驻浏览器+过验证）"
   与"协议边界申报"之间裁定后者。重启评估条件：未来发现免签名进场 HTTP
   通道，或客户对美团进场有强需求且接受受控页面成本——CDP 级抓帧技术
   路径已验证可行（playwright page.on("websocket") framereceived，帧格式
   42["pike",{d:"<json>"}]）。

## P3: 登录健康度面板（前端 UI）
- **What**: 前端显示各平台登录态/预算/过期状态（数据源=ENGINE_STATUS 登录生命周期词表 4 事件）。
- **Why**: 0G 决议 #4（CEO review 2026-10-06 defer）——词表已为面板铺路。
- **Effort**: human M / CC S | **Depends on**: 登录词表落地（切片 1/2）

## P3: 登录超时重试按钮（前端）
- **What**: login_required/降级房间的手动重试入口。
- **Why**: 0G 决议 #4 defer；目前逃生路径=停止后重新添加。
- **Effort**: human S / CC S | **Depends on**: 无

## P3: cookie 目录 README
- **What**: cookie/ 下各 profile/storage_state 文件用途说明。
- **Why**: 0G 决议 #4 defer；新部署排查成本高。
- **Effort**: human S / CC S | **Depends on**: 无

## P3: 前端内嵌二维码替代 OS 弹窗
- **What**: 扫码登录二选一呈现（AUTOlive 扫码面板/浏览器窗口）。
- **Why**: CEO F10 战略备忘（2026-10-06）；与视频号 NEEDS_LOGIN 面板形态同址。
- **Effort**: human M / CC M | **Depends on**: 登录健康度面板

## P3: 淘宝开放平台/官方弹幕通道评估
- **What**: 评估官方通道替代受控页面抓取（长线抗风控）。
- **Why**: CEO F10 战略备忘——淘宝反爬升级最快，长期维护成本最高模块的正解。
- **Effort**: human L / CC M（调研为主） | **Depends on**: 无


## P3: 1688 mtop API 同构化（X2 defer，2026-10-07）
- **What**: T2 的 MtopClient.post+页面 mtop 库调用能力落地后，1688（同协议异域名，mtop.py 直接支持）复制淘宝 mtop page-eval 路线——探针一次抓 1688 发送端点（iliad 同族）。
- **Why**: 1688 DOM 路线已达标（M0 SUCCESS，无风控信号），无痛点驱动；但 mtop 化可消除 DOM 选择器维护面（长期债）。
- **Pros**: 与淘宝 sender 同构（低成本复制）；消除选择器维护。
- **Cons**: 无实测痛点支撑；探针+sender 复制 ~1h CC。
- **Context**: 淘宝 T2 判定（cards/taobao-mtop-pageeval）——页面 mtop 库调用是唯一可行 API 形态；1688 引擎同用 MtopClient。1688 DOM sender（EngineHookSender）继续工作，本条目为优化非修复。
- **Effort**: human S / CC S | **Depends on**: 无（T2 已交付前置）
- 来源: /autoplan 修复计划 0G 裁定 X2（2026-10-07，defer 决策）

## P3: 官方开放平台互动 API 商业评估（CEO-F11，2026-10-07）
- **What**: 30 分钟商业评估——B站/抖音等官方开放平台互动 API 的资质门槛实际高度、公司主体是否可申请、成本收益；结果决定是否立项"长线最合规路线"。
- **Why**: R24 当时因"企业资质门槛"一票否决是工程层正确；若 AUTOlive 数字人商业化，资质是一次性成本，换双平台合规稳定发送+免除 DOM/mtop 军备的永久维护税——可能是 10x 路径（CEO 声部 F11：用既往裁定代替分析是盲区）。
- **Pros**: 合规稳定、免军备维护、解除账号连坐尾部风险。
- **Cons**: 资质成本未知（评估前）；覆盖面可能不满足 12 平台统一底座。
- **Context**: R24 否决记录（前置计划）+ ADR-002 替代方案节；2026-10-07 检索确认官方 taobao.live.comments.publish 等存在但需资质。评估产出=立项/不立项决议（记录于 ADR 或新 ADR）。
- **Effort**: human S（30min 评估）/ CC XS | **Depends on**: 无
- 来源: /autoplan CEO 声部 F11（2026-10-07，defer 决策）

## P3: 发送成功弹幕在弹幕区高亮（webui）
- **What**: 房间行发送成功的弹幕在弹幕流中高亮数秒；需跨平台内容归一化匹配（平台侧可能改写内容）。
- **Why**: CEO 评审扩展候选#3（2026-10-07 defer）——行内结果反馈已覆盖核心确认需求，弹幕区匹配脆弱且非必要。
- **Effort**: human S / CC M | **Depends on**: 本计划 T3 落地
- 来源: /autoplan CEO review 扩展裁定（2026-10-07，defer 决策）

## P3: DESIGN.md 提取（前端设计系统文档化）
- **What**: 从 style.css v7 锚点（slate 暗阶/blue-600 主色/8px 网格/字号层级/AUTOlive design_tokens 对齐）提取 DESIGN.md。
- **Why**: 设计评审 P5（2026-10-07）——事实设计系统存在且用户裁定过，但无文档承载；新前端工作时锚点靠读源码。
- **Pros**: 令牌词汇统一；新组件对齐有据；/design-consultation 后续工作有底。
- **Cons**: 文档维护成本（令牌变更需同步）。
- **Effort**: human S / CC S | **Depends on**: 无
- 来源: /autoplan 设计评审 P5（2026-10-07，defer 决策）
