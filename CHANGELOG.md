# Changelog

## v0.7.0 (2026-10-10)

弹幕发送多平台验收收官（10/12 平台全通；拼多多/美团 WEB 端未开放发送入口 N/A）+ 无感后台化架构批。核心资产：F1 登录态快照/恢复（login_state_store 共享层）、F2 发送/监听 profile 互斥、F3 WS 帧服务端回环判定、F4 自发声回环——贯穿小红书/虎牙/京东三平台修复。

### 修复
- **登录态持久化根因（三平台同源）**："会话级 cookie"旧结论全部被磁盘 Cookies 库取证推翻（小红书 id_token/虎牙 yyuid/京东 thor 均持久型）；历史登录全丢真因=进程硬杀丢未提交窗口+登录从未落盘。登录检测点立即快照 storage_state 原子落盘 + 启动时丢登录自动注入（login_state_store 共享层，controlled_base 与 resident_session 两级委托）
- **小红书发送（方案 B）**：瞬态后台会话替代常驻前台页（同 profile 双 persistent context 必然 TargetClosedError 实证——监听/发送互杀根除）；cookie 判登录（游客态输入框可见性判定失真）；WS 帧服务端回环唯一 SENT 真源（DOM 乐观渲染假阳性三例实证）；F4 自发声回环（发送侧注入+监听侧 10s 去重——监听收不到自己弹幕的根因=让位窗口吞噬广播）
- **虎牙发送**：STEALTH_JS 7 信号伪装经 init_scripts 实接（10-09"headless 被吞"回退缺此变量——翻案）；输入面回归 #pub_msg_input（用户 devtools 路径实为包裹层 div 教训固化：逐匹配扫描+可见且可编辑过滤）；UDB 遮罩可见性判定（count 假阳性修复）
- **京东发送**：登录判定根因=cookie 名全错（pt_key/pt_pin 老体系从未出现，真实登录为 thor/pin 持久型——用户扫码登录 Cookies 库取证）；方案 B 完整移植（游客发送区无输入框 DOM 取证"请先登录再发弹幕互动"）；发送按钮为 div 非 button（CSS-module 哈希类名稳定前缀匹配）
- **公共登录等待助手**：_wait_login_interactive 上收基类（2s 轮询+登录即快照+关窗即止——死 context 空转 240s 修复）；关窗竞态 profile 复检兜底（登录 cookie 随干净关闭落盘，不要求重扫）

### 变更
- **发送冷却默认 30s → 3s（用户裁定，防刷屏）**；虎牙保持 35s 内置覆写（平台实测约束：10-14s 失败、35s 全过）——INI send_min_interval_overrides 可按平台覆写
- 无感模式参数化：headless=new 后台发送（登录续期唯一弹窗场景），_launch 加 extra_args 扩展位
- 版本对齐：VERSION/pyproject/__init__ 三处同步 0.7.0（pyproject/__init__ 此前滞留 0.4.0）

### 验收
- 小红书/虎牙/京东 10-10 当日修复当日通过（用户实测：发送+监听+无感全通）；此前已通过：淘宝/1688/抖音/斗鱼/B站/快手；拼多多/美团 WEB 端无发送入口 N/A
- 测试基线 647→678（+31：F1 快照恢复/F4 回环/F2 互斥/京东 WS 回环/虎牙接线/公共件）


## v0.6.2 (2026-10-08)

多平台发送实测验收战役修复批（验收战役计划经 CEO/工程双阶段评审批准，8 项裁定 + 评审军团 20 项发现全闭环）——淘宝验收失败根因修复 + 发送链路「无超时挂点」类缺陷清零 + webui 行内发送结果闭环。

### 修复
- **淘宝发送静默挂起（P0，验收首日实证）**：根因=x5sec 风控触发 noCaptcha 验证，headless 瞬态页无人可解，mtop.request promise 永挂 + evaluate 裸 await 即永久悬挂。现在全部 await 显式超时（发送 evaluate 15s/lib 探针 2s/管线兜底 70s），x5sec 网络信号检测回执「风控验证待人工，勿盲目重试」——失败从 120s 永挂变为 ~17s 结构化回执
- **发送异常穿透 500（CEO-3）**：管线唯一分发点异常围栏——sender 异常/挂起转结构化回执+审计 result 行，杜绝 HTTP 500 与静默丢回执；未捕获异常计熔断（FAILED），unknown 语义保留给 sender 自分类
- **前端中止后结果不可见（CEO-5）**：60s 中止后 2s 宽限自动对账 `/api/send-results` 回显真实结果（sent/dry_run/failed/未知四态），查不到回落「结果待对账」；对账 GET 自带 5s 超时
- **UNKNOWN 渲染语义（？第四态）**：「结果未知（可能已送达）」琥珀色独立呈现，不再诱导盲重制造平台侧真重复（DUPLICATE 影子源消解）
- **幂等重放保真**：重放回执透传原 detail/fix_hint，对账 triage 上下文不被覆盖降级

### 变更
- 淘宝 sender 阶段预算收敛（goto 20+topic 12+lib 8+eval 15=55s，前端 60s 内闭环；tripwire 单测锁定）；JS mtop timeout 12s 联动
- x5sec 观测窗提前到页面加载期（goto/topic/lib 失败分支统一风控语义，不再误诊「页面改版」）；检测门主机白名单收敛（防页面伪造信号）
- 发送阶段日志（launch/goto/topic/lib/eval 五阶段+耗时）；管线日志 detail 截断 60→200
- runbook：失败表补 6 行（E5 隔离/管线兜底/页面未决/x5sec/DUPLICATE 对账指引等）、周检命令修正（--page-eval 形态）、验收前置检查（ADR-002 合规+重登窗口避让）、QA 清单第 9 项（中止对账）
- 测试基线 634→647（pytest）+ 新增 node:test 前端对账 6 用例（零依赖，源码提取防漂移）

## v0.6.1 (2026-10-08)

webui 房间行内弹幕发送（/autoplan 降级管线四阶段评审批准，13 项裁定）——房间行两行布局 + 行内发送表单，消费既有 `POST /api/send-danmu`，零后端改动。版本号经用户裁定取 PATCH。

### 修复
- **app.js:480 多余 `});` 语法错误（P0）**：`91d45c5` 引入，main 前端 JS 整体失效（房间列表/弹幕流/统计全不渲染）；修复 + node --check 冒烟单测防回归

### 新增
- **房间行内发送表单（T2/T3）**：每房间行第二行=输入框（maxlength 读自 /api/config send_max_length）+发送按钮+行内结果反馈行；按钮禁用三态（非 running/空输入/发送中）；Enter 提交+焦点回位+Escape 清空；IME 组合输入 Enter 不误触发（isComposing 守卫）
- **发送交互全分支反馈（D-C）**：✓ 已发送 HH:MM（含弹幕流回环）/ ○ dry-run 已记录 / ✗ 拒绝码中文映射（15 码+原码兜底，fix_hint+docs_anchor 入 title）/ 超时/网络/服务错误三失败分支；request_id 随机后缀防同毫秒幂等键相撞；AbortController 60s
- **getSendToken() 抽取**：token 流公共化（localStorage send_token+prompt），401 清 token 语义单点化；prompt 取消→行内提示不发请求
- **列表重绘回执降级**：在途发送遇列表重绘时回执降级写入发送状态行（对抗评审 F1），不静默丢失
- **结果三态色**：11px 小字用 400 阶亮色变体（#4ade80/#38bdf8/#f87171，对抗评审 F2 对比度 ≥4.5:1），与 status-badge 用色同源

### 变更
- 右栏"弹幕发送"测试表单删除（D-H 裁定：与房间行功能冗余；AUTH 反馈经运行中房间行可达），状态行保留；`?v=11` 缓存破坏
- style.css：.room-item 两行布局（.room-main-row/.room-send-row），focus-visible 焦点环，结果行 aria-live
- send-runbook.md：新增房间行内发送手动 QA 清单（8 项）
- 测试基线 631→634（前端资产回归 3 项）

## v0.6.0 (2026-10-07)

弹幕发送修复计划（/autoplan 全管线 82 项裁定）——淘宝 mtop 新路线 + 抖音常驻会话 + 三平台接线，10 平台 sender 全接线交付。

### 新增
- **淘宝 mtop page-eval sender（T2）**：页面 mtop 库调用（`mtop.taobao.iliad.comment.publish`）——页面 JS 现生成 bx-ua，纯 HTTP 重放被 RGV587 拒（T1 抓包探针三模式实证：capture/replay 重新签名/page-eval）；ret 五路径映射（SUCCESS/RGV587 风控/未登录/参数/未知码透传——禁止一律落 NEEDS_LOGIN 误导排障）；实发 sent 管线级实证；DOM 钩子 deprecated 保留
- **抖音常驻发送会话（T3/ResidentSendSession）**：headless=new 无桌面形态（CEO-F5 探针推翻"必须有头"——bd_ticket_guard 检测的是旧 headless 特征）；per-room page/同锁空闲关闭+锁内二次校验（ENG-1）/30s 操作超时会话重置/健康检查自动拉起（CEO-F8）/SingletonLock 撞锁独立错误（ENG-6）/close 超时 psutil 清理自愈（DX-D7）/生命周期日志（ENG-12）/aclose 退出钩子（ENG-4）；实发 sent×2（6.2s/6.8s）；CEO-F7 冷启动 <15s 阈值
- **快手/斗鱼/虎牙三平台接线（T6/X1）**：DomTransientSender 瞬态注入公共基类（凭证只读导入/候选选择器/逐键配方/get_by_text 穿透回显）+ KuaishouStateSender（storage_state）+ DouyuCookieSender（acf_* cookie）+ HuyaResidentSender（ResidentSendSession 第二实例，headed minimized）；快手 sent×2 + 虎牙 sent×2 实发实证
- **guard per-platform 限速覆写**：内置默认 `{"huya": 35}`（10-14s 实测失败、35s 补发全过）+ INI JSON 按键合并（DX-D3，损坏 JSON 兜底）——guard.check 实测虎牙 31s 拒/36s 过
- **DX-D1 凭证 CLI**：`python -m danmaku_listener.engines.kuaishou_login`（__main__ 补齐）+ `send_login douyu/huya`（新增）——三平台从零配置闭环
- **配置三件套**（[send] 节）：send_session_idle_timeout_seconds（1800）/ send_window_mode（默认 headless_new）/ send_min_interval_overrides
- 探针工具三件：taobao_mtop_capture.py（capture/replay/page-eval 三模式+离线自检）/ douyin_f5_probe.py（CEO-F5 双探针）/ douyin_soak.py（浸泡验收）

### 修复（实测四连）
- playwright timeout 单位 bug：秒传成毫秒→goto 30ms 超时→异常冒泡致子进程泄漏→loop 关不净→python 退出挂起（修+挂页失败清理）
- 回显判定升级 get_by_text 穿透 shadow DOM：聊天流 2026-10-07 起陆续 shadow 化，page.content() 搜索失效（视频号/抖音同款盲区）
- storage_state 导出覆盖事故防护：_inject_credentials 误用 context.storage_state(path=)（导出语义）致 kuaishou_storage_state.json 被空 context 覆盖（cookies 17→9）——改只读导入+add_cookies+防护单测
- 斗鱼选择器：泛 input[placeholder] first 误选顶部搜索框（截图实锤）——placeholder 精确特征前置
- 虎牙渲染等待：goto 后 SPA 输入框延迟挂载（1s 即查假阴性）——10×2s 等待循环

### 实测校准（判定手段全部截图/回环实证）
- 淘宝：RGV587 风控语义（纯 HTTP 重放 0/3 拒——页面 JS 现生成 bx-ua 2/2 过）
- 抖音：headless=new 实发成功（f5-diag 截图聊天流'(我)'标记）；登录失效信号=页面"需先登录"文本
- 快手：旧 headless 被风控（"请求过快"/"错误代码22"）→ headless=new 对齐抖音形态后打通
- 虎牙：#pub_msg_input 延迟挂载；35s 冷却 guard.check 实测 31s 拒/36s 过
- 探针矩阵五行终判更新（docs/testing/m0-send-probe-cards.md）

### 变更
- wiring：淘宝移出 E5 DOM 循环改注册 TaobaoMtopSender；三平台注册——10 平台 sender 全接线
- send-runbook.md 全量更新：凭证 CLI 表/配置三键/每周运维节奏（mtop 重放+成功率周报+政策监控）/选择器失效自查/cookie 语义
- TODOS 落盘：X2 1688 mtop 同构化 defer + CEO-F11 官方开放平台商业评估
- 测试基线 607→631（新增 resident_session 8 + t6_senders 16 中净增）
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
