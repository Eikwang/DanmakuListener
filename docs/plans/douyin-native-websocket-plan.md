<!-- /autoplan restore point: "C:\\Users\\admin\\.gstack\\projects\\DanmakuListener\\master-autoplan-restore-20260928-205603.md" -->
# 抖音弹幕监听原生整合计划（Web WS + 本地签名路线）

> /autoplan 输入（2026-09-28）。用户方向修正（User Challenge，驳回上一轮桥接方向）：
> "我要实现的并不是桥接DouyinBarrageGrab……我要实现的是将抖音的弹幕监听功能整合到
> 系统中来，并不是桥接其它程序！你可以根据参考项目，选择合适的技术路线……如果
> ordinaryroad-barrage-fly的实现方式更适合当前系统，就使用它的实现方案！"

## Implementation plan

### 背景

- 六平台中四平台已原生实测通过（B站/斗鱼/快手/虎牙）；上一轮误做的 BarrageGrab
  桥接（非原生）已由用户驳回，本计划撤销。
- 上一轮将抖音实现为「桥接 DouyinBarrageGrab（外部程序）」——用户驳回：增加外部依赖
  与操作步骤，违背"独立分发、开箱即用"的产品约束。
- 系统约束：独立分发单进程（AUTOlive 唯一前端）、无外部程序依赖、合规只监听不发送。

### 路线决策（证据驱动）

**选定：路线 A —— barrage-fly SDK 同款「Web 端 WS 直连 + 本地签名」**（原生整合）。

证据（2026-09-28 端到端原型实测，runtime312 环境）：

| 环节 | 证据 |
|---|---|
| 签名（最高风险项） | barrage-fly SDK 内嵌修改版 `douyin-webmssdk.js`（MIT，hua0512 提取），Java 走 ScriptEngine 本地计算；Python 侧 **quickjs 0.02s 完成 eval+get_sign**（pip quickjs，无 node 依赖） |
| roomInit | 全游客 HTTP：GET live.douyin.com 拿 ttwid（实测获取 127B ttwid ✓）→ GET live.douyin.com/{rid} 正则拿 real_room/user_unique_id（实测 ✓） |
| WS 连接 | `wss://webcast5-ws-web-lq.douyin.com/webcast/im/push/v2/` + SDK 全参数 + signature —— 实测 **WS CONNECTED** ✓ |
| 帧协议 | PushFrame protobuf → headers compress_type=gzip → Response{messagesList} → needAck 回 ACK（payload=internalExt）—— 实测 ✓ |
| 心跳 | 固定字节 `{58,2,104,98}`（PushFrame{payloadType:"hb"}），10s 周期（SDK 默认 initial 5s）—— 实测 hb ack ✓ |
| 业务消息 | 实测 35s 收 22 条：LikeMessage×12、RoomStatsMessage×7、RoomRankMessage、ResidentGuestMessage ✓（房间此刻无文字弹幕；ChatMessage 同通道） |

**放弃：桥接 BarrageGrab**（用户驳回；douyin_grab.py + 测试 + registry/bridge 接线一并移除，
git 历史保留）。**放弃：自研 mitmproxy 代理路线**（engines/proxy_engine.py 等）——需要
证书安装 + 直播伴侣运行，环境前置与桥接同病；保留原位、不再注册、不做归档移动。

### 关键资产（已就位）

- `danmaku_listener/engines/protocol/douyin_assets/douyin-webmssdk.js`（485KB，签名 JS）
- `danmaku_listener/engines/protocol/douyin_assets/douyin.proto`（package dyproto，已加
  避免全局 pb 名冲突）+ `douyin_pb2.py`（grpc_tools 生成）
- 新增依赖：`quickjs`（pyproject dependencies 补声明）

### 实施任务

0. **T0 冒烟验证（先行门禁，CEO 2.1 + Eng F1）**：**第一步把 quickjs 签名原型脚本入库**（tools/dy_sign_smoke.py：webmssdk eval + get_sign + WS 帧解析最小路径；当前原型仅在会话环境未入库），然后在真实**活跃弹幕**房间（Playwright 找高热房间）抓到 ChatMessage≥3 条——DANMU 链路实测补全后才开工。
1. **T1 资产与依赖**：pyproject 声明 **quickjs**、**protobuf>=7.35.1,<8**（pb2 gencode 7.35.1 硬要求——Eng 5e）、**websockets>=14**（additional_headers 参数名，Eng 5c）；douyin_assets 纳入 package_data；**provenance 补 proto 来源**（douyin.proto 提取自 HaoDong108/DouyinBarrageGrab message.proto——Eng F5）；
   **签名自检**（启动时固定样本串 get_sign，失败报「签名资产过期」而非笼统网络错误）；
   **资产 provenance 记录**（douyin-webmssdk.js 来源：barrage-fly SDK 1.5.8 内嵌
   MIT 提取版 by hua0512；刷新流程=重新提取上游 release）。
2. **T2 roomInit**：`engines/protocol/douyin.py` 内 `DouyinRoomInit`（requests.Session：
   ttwid → 页面正则 real_room/user_unique_id/status；msToken 随机 116 字符）。
   **ttwid 获取失败（网络/风控）同样归入三段式**；status==2 为直播中；非 2 或解析
   失败 → 三段式错误（reason_code/fix_hint/docs_anchor 非空）。
3. **T3 引擎**：`engines/protocol/douyin.py` 的 `DouyinWebProtocolEngine`（复用协议
   引擎骨架；**引擎粒度为每平台一实例、每房间独立任务**——与桥接的"单 WS 共享"相反，
   每房间独立 roomInit/签名/WS 连接）：
   - WS 连接（SDK WEB_SOCKET_URIS 三域名：webcast5-ws-web-lq/-lf/-hl.douyin.com，轮换）+ SDK 全参数拼装 + quickjs 签名
   - 心跳 10s（首帧 5s 延迟，SDK 默认）；PushFrame 解帧 → gzip → Response → needAck ACK
   - cmd 分发 → 契约映射（显式清单，与 T5 单测逐条对齐）：
     - 业务六类：ChatMessage→DANMU（user.nick_name/content/id）、GiftMessage→GIFT
       （**count 取 GiftMessage.totalCount 字段原样透传——Eng F4 修正字段名**；
       groupCount/repeatCount/comboCount 均不参与——连击合并已 defer）、
       MemberMessage→ENTER_ROOM（仅进房 action；离房等变体按未映射丢弃+debug）、LikeMessage→LIKE（count/total）、
       SocialMessage→SOCIAL（action=1 关注/3 分享）、RoomStatsMessage→ROOM_STATS（**displayType 多统计类型过滤策略：仅透传 total 类**，
       与 T5 对齐——Eng H3）
     - 系统类：ControlMessage→ROOM_STATUS（**proto 字段为 int32 status，status==3 下播**；
       其它 status 值按未映射丢弃+debug——Eng F3）/ROUTE_FAILED（签名失败、WS 拒绝）；
       心跳帧（hb/ack）仅保活不外发
     - **粉丝团为 Web WS 路线已知能力回退（Eng F2 修正理由）**：proto 存在 FansclubMessage 但字段过薄（type 枚举语义未实测），无法可靠映射——本计划不实现，记 TODOS（显式回退，非静默）
     - 未映射 cmd（RoomRankMessage/ResidentGuestMessage 等）：丢弃 + debug 日志，
       不产生 GAP、不消耗 seq
   - **quickjs 线程模型（Eng H1，三句话写死）**：Context 为引擎级单例；仅在事件循环
     线程同步调用（quickjs 绑定线程绑定语义，跨线程即错）；**任何 run_in_executor/
     to_thread 包裹 get_sign 均为违规**——eval 预热 50-200ms 一次性成本在 loop 线程做
     并计时打日志
   - **重连单层归属（Eng H2）**：照抄 huya——引擎内 while 单层 + 指数退避封顶；
     ReconnectManager 不接（双层叠加会重连风暴）
   - **多房间启动错峰**（CEO 2.4）：每房间 start 加随机 1-5s 抖动
   - 断线重连：roomInit 重新签名（host 列表轮换 + 慢速重试，契约 O）
   - **多房间启动错峰**（CEO 2.4）：每房间 start 加随机 1-5s 抖动，避免并发连发
     游客抓取触发 IP 级风控
4. **T4 接线与清理**：registry douyin → DouyinWebProtocolEngine；bridge 移除 douyin
   特判（无 501、无 BarrageGrab 提示）；**删除** douyin_grab.py + test_douyin_grab.py +
   registry/bridge 的 grab 接线——**时序依赖（CEO 4.3）：待 T0 冒烟 + §4C 真实房间
   DANMU/GIFT/ENTER_ROOM 验证通过后执行删除**（删除前旧桥接是唯一可用路径，git 可回滚）；
   DouyinProxyEngine（**代理路线**遗留文件）保留但不再注册。
5. **T5 测试**：`tests/unit/test_douyin_protocol.py`（对齐四平台命名先例）：映射单测
   （业务六类+系统类，dy_pb2 真实构造，清单与 T3 逐条对齐）+ roomInit 正则单测
   （页面样例 fixture）+ 引擎生命周期 + 未知 cmd 丢弃策略单测 + **缺口清单**
   （Eng §3）：ACK 序列（needAck→断言 ack 帧同帧 logId+internalExt）、gzip 坏包
   （不 crash 不 emit 计数）、签名自检（固定样本确定性输出）、quickjs 线程模型锁定、
   ControlMessage status==3 vs 其它、WS 403→ROUTE_FAILED 三段式、启动错峰抖动
   （patch 随机源）、未知字段前向兼容。
6. **T6 文档与登记**：manual-test-procedure §4C 改为 Web WS 路线（无证书/无外部程序/无
   直播伴侣依赖；**要求在真实活跃房间验证 DANMU/GIFT/ENTER_ROOM 三类后再关闭计划**）；
   compliance-review §4 重写（无根 CA、无 hook——纯 Web WS 游客监听）；
   registry warnings 更新；**契约文档标注 GIFT.count 语义=累计值（连击不合并，
   防下游按增量误用——CEO 3.2）**；**TODOS.md 登记**（粉丝团监听回退、礼物连击合并、
   ChatMessage 表情细分、wsapi Wup 通路、**抖音登录态备选路线**——复用快手登录窗口
   模式，触发条件：三段式 reason_code 命中风控特征时提示用户【CEO 2.3】、
   **webmssdk 上游 release 跟踪**【CEO 2.2】、**抖音开放平台官方 API 调研结论登记**
   ——已评估：逆向 WS 为当前可行路线，官方 API 是否覆盖游客监听/企业资质要求
   待调研记录【CEO 4.1】）。

### NOT in scope

- 抖音发送弹幕/礼物（合规硬约束：只监听）
- 粉丝团监听（Web WS 路线 proto 缺 FanClubMessage——已知能力回退，记 TODOS）
- 礼物连击合并（groupCount 聚合窗口——defer，GIFT 仅透传计数）
- ChatMessage 表情/emoji 消息细分（defer）
- wsapi/mitmproxy 代理路线（保留原位、不再注册、不做归档移动）
- 视频号（下一平台，另行计划）

### What already exists

- 契约 v1（8 类业务消息 + 8 类 SYSTEM_STATUS）+ BaseEngine 骨架（seq/GAP/重连/慢速重试）
  ——B站/斗鱼/快手/虎牙四平台同构复用
- douyin_assets 资产 + quickjs 签名验证脚本（本计划证据链）
- 旧 ProxyEngine/DouyinAdapter（代理路线遗留，不接线不删除）

## DX Review（Phase 2.5，SELECTIVE 深度，auto-decide）

**Persona（0A）**：AUTOlive 集成开发者（WS 8765 契约消费方）+ 自部署运营者（serve/exe
启动 + web 控制台加房间）。Tolerance≈30 分钟；Expects：README 快速开始、契约
examples、加房间即出流。

**Empathy（0B）**：集成者读 docs/integration/autolive.md → 起 serve → WS 连 8765 →
按 category 分流——路径已文档化（~15 分钟）；运营者装 wheel → serve --web → 加房间
——抖音从"装证书+跑外部程序"变为"加房间即用"（本计划直接消除最大摩擦点）。

**Benchmark（0C）**：BarrageGrab（装证书+管理员启动+配置过滤 ≈15 分钟人工）→ 本计划
0 分钟外部前置；barrage-fly（Java 部署+签名服务 ≈30 分钟）→ pip install 即内嵌。
TTHW（AUTOlive 接入）：观测 ~15 分钟，目标保持 <15 分钟（接入契约不变更）。

**8 维度评分（现状 → 本计划后）**：1 Usable 8→9；2 Credible 8→8；3 Findable 7→8；
4 Useful 8→8；5 Valuable 8→9；6 Accessible 8→8；7 Desirable 8→8。
**DX Implementation Checklist（并入 T6）**：README 集成段补抖音一行；
docs/integration/autolive.md 补抖音 payload 样例。
**结论**：DX scope 由计划正文术语命中触发（SDK/pip/debug/endpoint），经核验交付物
为平台引擎内部实现、集成面无变更——无 dev-facing 阻塞项，checklist 并入 T6。

## Review record

<!-- autoplan-accepted:ceo -->
- 路线 A（Web WS + quickjs 本地签名）为抖音监听唯一主路线；实测证据：quickjs get_sign 0.02s、ttwid 游客获取、webcast5-ws-web-lq WS CONNECTED、PushFrame/gzip/Response/ACK 解帧、心跳 0x3a026862 ack、35s 收 22 条业务消息（Like×12/Stats×7/Rank/Guest）。
- 引擎行为：DouyinWebProtocolEngine 复用 BaseEngine 骨架；WS 参数对齐 SDK 全集（cursor/internal_ext/host/aid/endpoint/identity 等）；三域名 webcast5-ws-web-lq/-lf/-hl 轮换；心跳 10s 周期首帧 5s；needAck 必回 ACK（payload=internalExt, logId 同帧）；断线重连重跑 roomInit 重签名，host 轮换 + 慢速重试（契约 O）。
- roomInit：requests.Session 游客流程——GET live.douyin.com 取 ttwid（**ttwid 获取失败同样三段式**）；msToken 随机 116 字符；页面正则 real_room/user_unique_id/status；status==2 为直播中，非 2 或解析失败 → 三段式 FailureInfo（reason_code/fix_hint/docs_anchor 非空）。
- 契约映射（显式清单，与 T5 单测逐条对齐）：业务六类 ChatMessage→DANMU、GiftMessage→GIFT（**count 取 gift.total 原样透传**，group_count 不参与合并）、MemberMessage→ENTER_ROOM（仅进房 action；离房等变体按未映射丢弃+debug）、LikeMessage→LIKE、SocialMessage→SOCIAL(action=1关注/3分享)、RoomStatsMessage→ROOM_STATS；系统类 ControlMessage→ROOM_STATUS（仅 live=false 下播；live=true/其它变体按未映射丢弃+debug）/ROUTE_FAILED（签名失败/WS拒绝）；未映射 cmd（RoomRankMessage/ResidentGuestMessage 等）丢弃+debug 日志不耗 seq；msg_id 用平台 msgId（去重键）；粉丝团监听为显式回退记 TODOS。
- 清理：删除 danmaku_listener/engines/douyin_grab.py + tests/unit/test_douyin_grab.py；registry douyin 指向 DouyinWebProtocolEngine；bridge 无 douyin 特判（无 501/无 BarrageGrab 提示）；DouyinProxyEngine（代理路线遗留文件）保留但不再注册。
- 验证：pyproject 声明 quickjs；douyin_assets 入 package_data；645+ 测试全绿；新增映射单测用 dy_pb2 真实构造（业务六类+系统类）；roomInit 正则单测用页面样例 fixture；未知 cmd 丢弃策略单测；签名失败/WS 拒绝 → ROUTE_FAILED 三段式。
- 文档：manual-test-procedure §4C 与 compliance-review §4 重写为纯 Web WS 路线（无证书、无外部程序、无 hook、只监听不发送）；§4C 要求在真实活跃房间验证 DANMU/GIFT/ENTER_ROOM 三类后再关闭计划；TODOS.md 登记粉丝团回退/连击合并/表情细分/wsapi Wup 通路。
<!-- /autoplan-accepted:ceo -->

<!-- autoplan-accepted:dx -->
- DX persona：AUTOlive 集成开发者（WS 8765 契约消费方）+ 自部署运营者；接入面无变更（本计划为平台引擎内部实现）。
- DX 验收：T6 并入 checklist——README 集成段补抖音一行、docs/integration/autolive.md 补抖音 payload 样例；TTHW 保持 <15 分钟（接入契约不变更）。
- DX 评分基线：8 维度现状 8/8/7/8/8/8/8 → 本计划后 9/8/8/8/9/8/8（无 dev-facing 阻塞项）。
<!-- /autoplan-accepted:dx -->

<!-- autoplan-accepted:eng -->
- Eng H1（critical）：quickjs 线程模型三句写死——Context 引擎级单例、仅 loop 线程同步调用、get_sign 禁止 executor/to_thread 包裹；eval 预热在 loop 线程做并计时。
- Eng H2（high）：重连单层归属——照抄 huya 引擎内 while 单层+指数退避封顶，ReconnectManager 不接。
- Eng F1（high）：T0 第一步先入库 quickjs 原型脚本（tools/dy_sign_smoke.py）再冒烟；T1 的 pyproject 声明先于 T0。
- Eng 5e（high）：pyproject 三 pin——quickjs、protobuf>=7.35.1,<8（pb2 gencode 7.35.1 硬要求）、websockets>=14（additional_headers）；登记 grpcio-tools 生成工具版本。
- Eng F3：ControlMessage 映射字段修正——proto 为 int32 status，status==3 下播→ROOM_STATUS，其它丢弃+debug。
- Eng F4：GIFT count 取 GiftMessage.totalCount 字段（非 gift.total）；groupCount/repeatCount/comboCount 不参与。
- Eng F2：粉丝团回退理由修正——proto 存在 FansclubMessage 但字段过薄（type 语义未实测）无法可靠映射；回退决策不变。
- Eng F5：provenance 补 proto 来源（HaoDong108/DouyinBarrageGrab message.proto）。
- Eng H3（medium）：RoomStatsMessage displayType 过滤策略——仅透传 total 类，T5 对齐。
- Eng 5c（low）：websockets 实装 17.1，>=14 下限确认。
- Eng 5d（low）：msToken 随机 116 字符合规（协议模拟非身份伪造）；compliance §4 写明。
- Eng T5 缺口清单：test_douyin_protocol.py 含 ACK/gzip 坏包/签名自检/线程锁定/status 枚举/403 三段式/错峰抖动/前向兼容单测。
- Eng T6：粉丝团 TODOS 措辞按 F2 修正；manual-test §4C 与 compliance §4 按 5d 措辞重写。
<!-- /autoplan-accepted:eng -->
## 义务块

（管线各阶段写入）
