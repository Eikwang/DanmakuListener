# Changelog

## v0.5.0 (2026-10-06)

十二平台登录闭环全覆盖（/autoplan 双阶段审查 + 实机 probe 校准）+ 实测缺陷修复三连。

### 新增
- 登录闭环全覆盖：十二平台登录策略矩阵落全（7 平台已有闭环 + 淘宝/京东/小红书新增引擎层闭环 + 斗鱼/虎牙新增 cookie 文件形态检测闭环 + 美团豁免）——首次添加自动检测登录态并弹登录窗口，登录后自动开始监听
- 登录共享基建：engines/login_gate.py（判定/掩码/预算/cookie 文件形态闭环）；BaseEngine._emit_system_status（ENGINE_STATUS 快捷通道）
- 登录生命周期事件词表：login.first_login / relogin_triggered / timeout_budget_exhausted / degraded_detected（前端/健康面板数据源）
- 登录窗口预算语义：每房间 2 次超时预算（首登/重登共用、内存态、重启清零、锁存键=room_id、每会话一次提示）；stop 立即关窗；关窗异常按用户关窗分支（不冒泡 topic_failed）
- 淘宝会话失效重登框架：spike 驱动定型（enter 存活型证据窗口 / 全停推型重建计数，RELOGIN_MODE 由 T0 spike 实测激活）；触发时证据快照随日志带出
- 实机 cookie 校准工具：tools/douyu_cookie_probe.py / xhs_cookie_probe.py / login_spike_taobao.py（登录前后差异集实证，杜绝调研猜测名）

### 实测校准（cookie 判定名全部实机 probe 实证）
- 斗鱼：dedeuserid 不存在——真实登录态 acf_uid/acf_auth 家族
- 小红书：游客即自带 web_session（匿名会话）——登录判定改 id_token（登录后新增 JWT）
- 虎牙：候选 yyuid/hiido_ui/u_db_uid 实测命中；淘宝/1688 unb（阿里系同源）保持

### 修复（用户实测三连）
- 抖音 quickjs 运行环境缺装（依赖已入 requirements，属环境项）；bilibili 停止时内层 WARNING 噪音（_is_stopping 短路补齐）
- 京东/小红书登录窗闪退：_cookies() 少 await（coroutine TypeError → 误判关窗）——controlled_base/taobao 两处
- 斗鱼/虎牙登录门槛 AttributeError（BaseEngine 无 _emit_system_status）
- 斗鱼登录页 302 误导（douyu.com/login → 直播间页）：登录入口改 passport.douyu.com；登录后关窗丢登录态（关窗异常分支补 last_cookies 存档）
- 虎牙未开播房间误报"房间不存在"：TT_ROOM_DATA 开播状态判定，未开播明确提示等开播
- 小红书在线人数补映射（refresh 帧 viewers 名单 → ROOM_STATS，同值去重）；关注匹配加宽 follow 变体 + 未识别类型首见日志
- huya lifecycle 单测真实弹登录窗致 pytest 挂起（stub 门槛）；测试基线 557→566

### 变更
- registry.PLATFORM_WARNINGS 十二平台登录声明全量补齐（taobao/1688/douyu 新增 + 四平台登录增强声明）
- 测试文档登录盘点表：判定依据 + 实测日期（声明过时可追溯）
## v0.4.0 (2026-10-05)

十二平台全量交付（全部实测验收）+ 前端控制台成熟版（多平台运营监控台形态）。

### 新增
- 平台扩展：六平台 → 十二平台（淘宝/1688/小红书/拼多多/京东/美团），全部协议直连或受控页面，实测验收至各自协议边界
- 前端控制台 v6-v10：多平台同步监听、选项式添加（平台下拉 + 直播间链接自动识别，dpurl.cn 短链 302 归一）、房间持久化（persistence_data/rooms.json，重启恢复按需启停）、三区消息显示（弹幕/互动/信息，"[平台]内容"格式）、全新视觉（Tailwind slate 体系对齐 AUTOlive design_tokens）、单房间启停 API（start/stop）、在线口径统一 + 同值去重、空载荷渲染兜底
- 引擎归一接口：BaseEngine.normalize_room_id（链接/短链 → 安全 room_id 入库）
- 停止语义：BaseEngine._is_stopping——停止中的连接关闭不发 GAP/不标 ERROR（11 引擎统一）
- 拼多多会话降级检测：登录会话被服务端作废（cookie 在而服务端按游客推送）自动弹窗重登
- 快手统计解析增强：displayWatchingCount 脏格式宽松解析（万/亿/千分位/脏后缀）

### 协议边界（dump 实证，详见 docs/testing/full_platform_test_plan.md）
- 斗鱼点赞/关注无房间级 STT 推送；美团进场走 Pike WS（H5guard 签名保护）不进轮询接口
- 京东点赞为聚合帧无昵称；B站 LIKE_INFO_V3_UPDATE/NOTICE_MSG（全站广播）跳过
- 快手无独立入场/关注推送（SC_FEED_PUSH 四类）

### 修复
- B站 V2 protobuf 消息补齐（SEND_GIFT_V2/INTERACT_WORD_V2/ENTRY_EFFECT/LIKE_INFO_V3_CLICK）与"登录态失效"误报
- 斗鱼 oun 在线人数映射；虎牙贵宾进场横幅（Tars 递归解码）
- 抖音 SDK 参数对齐页面 WS（消息集合恢复完整）+ 登录闭环（礼物只推登录观众）+ CookieConflictError
- 淘宝/1688 观看数口径校准；1688 入场横幅 DOM 探测；小红书点赞昵称反查（会话内学习表）
- 美团 dpurl.cn 短链添加 + 链接型 room_id 打散 REST 路径（前端 encodeURIComponent 防御）
- 淘宝 random 未导入存量炸弹；pyflakes 存量清理

### 变更
- 抖音引擎最终形态为原生 Web WS 直连（BarrageGrab 桥接/代理路线撤销，douyin_grab.py 删除）
- AUTOlive 拷贝分发（Scripts/copy_danmaku.py，COPY_MANIFEST 版本戳）随每次推送同步

## v0.3.0 (2026-09-28)

六平台协议直连引擎 + 统一消息契约 v1 + Web 测试控制台 + 独立分发。

### 新增
- 六平台无感监听引擎：B站/斗鱼/虎牙/快手协议直连、抖音代理/伴侣直听（ADR-001 独立进程）、微信视频号受控后台
- 统一消息契约 v1（九类消息 = 8 业务 + SYSTEM_STATUS；pydantic 单源 + JSON Schema 导出 + CI 漂移检查）
- SYSTEM_STATUS 管道：心跳（loop lag 采样）/GAP（下播裁剪+崩溃恢复补发）/NEEDS_LOGIN（interactive_login 闭环）/背压分级/路线失效/恢复
- Web 测试控制台（契约渲染 + 8 种告警条 + 统计面板 + 设置面板 /api/config）
- fixture 回放基建（录制/回放/离线演示，TTHW <10ms）
- 部署预检脚本（六平台统一框架）
- 引擎注册表（registry）与分发打包（wheel + extras 分层）

### 破坏性变更
- SUPPORTED_PLATFORMS 移除 taobao/weixin（无引擎实现）
- 旧 DanmakuMessage 消费路径改为契约 v1（兼容适配器见 contract.legacy）

### 修复
- 主包急切导入链（PEP 562 惰性导入）
- protobuf gencode/runtime 版本对齐
