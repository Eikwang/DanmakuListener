# Changelog

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
