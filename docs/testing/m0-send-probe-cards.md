# M0 发送探针卡片（T2）——回填矩阵

生成：/autoplan 批准计划 T2 | 探针工具：tools/send_probes/ | 判定语义见其 README

> 回填规则：每平台探针运行后，把卡片结论（cards/<platform>-<ts>.json）汇总到下表；
> 成功 → 矩阵可行性终判提升；blocked → 附降级路线；NEEDS_LOGIN → 补登录后重探。

## 探针矩阵（M0 终判）

| 平台 | 路线 | 状态 | 判定 | 卡片 | 备注 |
|------|------|------|------|------|------|
| bilibili | API | ✅ **实发 SUCCESS×2**（2026-10-07 实测） | 高（终判） | cards/bilibili-20261007-091159.json | HTTP 200/code=0；管线实发 sent ✓ 幂等 ✓ 去重 ✓；F8 回环数据链路就绪 |
| taobao | DOM | ⚠️ 受限可行（2026-10-07 实测 5 发）；**mtop page-eval 管线级 ✅ SENT（T2 实测 2026-10-07）+ T1 探针 SUCCESS×2** | 高（终判：**mtop page-eval 为主路线，DOM 降备选**） | cards/taobao-mtop-{capture,replay,pageeval}-20261007-*.json + cards/taobao-mtop-t2-pipeline-20261007.json | **T1 三连判定**：①capture 抓到发送端点 `mtop.taobao.iliad.comment.publish` v1.0（appKey 34675810，data={topic,content} 极简，GET jsonp）②纯 HTTP 重放 0/3 FAIL——`FAIL_SYS_USER_VALIDATE; RGV587_ERROR`（query 的 bx-ua/bx_et 行为签名须页面 JS 现生成，签名 sign 重建正确仍被拒）③**页面上下文调用 window.lib.mtop.request（type:'GET'）2/2 SUCCESS**——页面 JS 现生成 bx-ua 风控全过。**T2 交付**：TaobaoMtopSender（senders/taobao_mtop.py，E5 借引擎 _profile_lock+瞬态页 evaluate+ret 五路径映射）管线级实发 status=sent 实证；单测 9/9+全量 607 回归绿；ENG-2/15 由页面 mtop 库天然解决；wiring 已替换（DOM 钩子 deprecated 保留作 T4 参照）；ret 已知码：SUCCESS/RGV587（风控）/UNEXCEPT_REQUEST（type 参数须 HTTP 方法） |
| 1688 | DOM | ✅ **实发 SUCCESS**（2026-10-07 实测；前两条已入聊天区截图实证） | 高（终判） | cards/1688-enter-test.png | 关键发现：fill 的 DOM 值不进框架 state、发送 div 点击不可靠——唯一可靠配方=**click 聚焦+逐键输入(press_sequentially)+Enter**；回显延迟大→input 清空为第二判据；引擎钩子已按配方覆写 |
| xiaohongshu | DOM | ✅ **实发 SUCCESS×3**（2026-10-07 实测，指定文案） | 高（终判） | cards/xiaohongshu-20261007-102810.json | contenteditable 输入框+Enter 提交（无发送按钮元素）；fill 直接可用（框架吃 DOM 值）；无风控信号 |
| jd | DOM | ✅ **实发 SUCCESS×3**（2026-10-07 实测，指定文案） | 高（终判） | cards/jd-20261007-103520.json | input[placeholder]+text=发送 命中；fill 直接可用；无风控信号 |
| wechat_channels | DOM | ✅ **实发 SUCCESS×3**（2026-10-07 实测，指定文案，截图实证） | 高（终判，附有头约束） | 截图 persistence_data/wxsp-send-unknown.png | 管线 E5 钩子全链：后台扫码登录（wxsp_profile）→几何导航进直播间→助手发言输入框（shadow DOM 内，get_by_placeholder 穿透定位）→逐键+Enter→**get_by_text 穿透回显判定**；两处盲区实证修复：①输入控件不在主 frame DOM ②回显不在 page.content()；修正后唯一文案验证 status=sent（11:32 实测） |
| douyin | DOM | ✅ **实发 SUCCESS×3**（2026-10-07 实测，指定文案）；**T3 常驻会话 headless=new 实发 sent×2（2026-10-07）** | 高（终判：**常驻会话 headless=new 形态——无桌面运行，部署约束解除**） | cards/douyin-20261007-100544.json + cards/douyin-ceo-f5-probe-20261007-170035.json + cards/douyin-t3-resident-20261007.json | **T1 判定修订（CEO-F5 探针）**：bd_ticket_guard 检测的是旧 headless 特征——`--headless=new` 完整 Chrome 指纹下面板渲染✓+实发✓（f5-diag 截图：聊天流'[M0] f5-diag'(我)）——"必须有头"前提推翻，常驻会话无桌面可用；**判定手段升级**：聊天流移入 shadow DOM（page.content() 失效）→get_by_text 穿透（视频号同款修复）；登录失效信号="需先登录"文本（比输入框缺失更准）。**T3 交付**：ResidentSendSession（ENG-1 同锁空闲关闭/30s 操作超时重置/CEO-F8 健康自愈/ENG-6 撞锁/DX-D7 清理自愈/ENG-12 日志/ENG-4 退出钩子）+DouyinProfileSender 重构（旧瞬态 deprecated 保留）+douyin_login CLI+配置三件套；实发 sent×2（6.2s/6.8s）；单测 8/8+全量 615 绿；浸泡验收 2h 被用户手动停止（DX-D2 判定未完成——douyin_soak.py 可补跑）；CEO-F7 冷启动实测 6.2s<15s 阈值 ✓ |
| kuaishou | DOM | ✅ **实发 SUCCESS×3**（M0）+ **T6 管线 sent×2**（XFZ11200，2026-10-07） | 高（终判） | cards/kuaishou-20261007-095159.json + cards/t6-3platform-20261007.json | storage_state 注入；textarea+text=发送 命中；**T6 形态修订：旧 headless 被风控（请求过快/错误代码22）→ headless=new 对齐抖音形态后打通**；管线 KuaishouStateSender（瞬态注入基类） |
| douyu | DOM(+R19) | ✅ **实发 SUCCESS×3**（M0）；T6 管线实发待真开播房间（71415 挂播/12249 关闭，选择器修复后代码就绪） | 高（终判，实发复验待房间） | cards/douyu-20261007-094617.json + cards/t6-3platform-20261007.json | cookie 注入（acf_* R19）；**T6 选择器修复**：泛 input[placeholder] first 误选顶部搜索框（截图实锤）——placeholder*=说/未拥有 精征前置；发送动作已可达（ChatSend-button 点击成功） |
| huya | DOM | ✅ **实发 SUCCESS×3**（M0）+ **T6 管线 sent×2**（518518，2026-10-07，6.8s/6.1s） | 高（终判，附冷却约束） | cards/huya-20261007-103941.json + cards/t6-3platform-20261007.json | **T6 接线完成**：HuyaResidentSender（ResidentSendSession 第二实例，headed minimized）+ 渲染等待修复（goto 后 SPA 输入框延迟挂载）；35s 冷却由 guard per-platform 覆写内置默认兜底（guard.check 实测 31s 拒/36s 过） |

## R19 cookie 字段审计结论（离线，2026-10-06）

- bilibili: SESSDATA+bili_jct 双全（18 cookies）——API 发送鉴权就绪
- douyu: acf_uid+acf_auth 命中（24 cookies）——网页侧初步充分；ltkid/stk/vk 需活会话核实
- huya: 43 cookies 无候选登录字段——**登录窗口补齐后再探针**
- douyin: 53 cookies（WS 登录态，OK(info)）；DOM 发送用浏览器会话
- kuaishou: storage_state 14 cookies（OK(info)）
- 受控页面 profile ×6 全部就绪（taobao/1688/xhs/jd/pdd/huya_login）

## 探针纪律执行记录

- [x] 探针账号环境=实发环境（R17）：profile/cookie 全部复用 cookie/ 既有存档
- [x] 连续 N 次发送+间隔 10s+抖动+风控信号观察（R17）：dom_send_probe 内建
- [x] 判定语义 F5：SUCCESS（回显）/ FAIL（显式错误）/ UNKNOWN（不计熔断）/ BLOCKED
- [x] 内容标记 [M0]（回环识别 F8）
- [x] R23 社区资料比对：结论见 tools/send_probes/README.md（斗鱼/抖音/快手发送均无成熟公开逆向——DOM 优先）

## 根因卡：淘宝集成环境发送挂起（2026-10-08，T1 取证）

**判定：none（挂起）——不是 sent，也不是显式 failed。** 无任何证据表明弹幕实际发出。

### 证据时间线（persistence_data/send_audit.jsonl）

| 行 | ts(≈) | request_id | 事件 |
|---|---|---|---|
| 54 | 09:17:53 | ui-1791422273810-a816ke | intent（"早上好呀主播"，房 2402661083849123）——**无 result 行** |
| 55 | 09:19:55 | ui-1791422395668-pn55d9 | intent+result 同秒：**DUPLICATE**（行 54 record_attempt 占 300s 去重窗的影子） |
| 56 | 09:21:28 | ui-1791422488366-mnggx2 | 重启后 intent——**此后文件零写入**（mtime 09:21） |

关键推论：行 54 的 intent 后 122 秒（> sender 全部有界阶段预算 85s）仍无 result → 挂点必在**无超时的 await**；锁 busy 路径（3s 超时会留 result）排除；监听引擎无常开浏览器（taobao.py:451-452 finally close 实证），profile 冲突会快速 raise（→500，前端"服务错误"而非 60s 中止）→ 降权。

### 挂点嫌疑排序

1. **[P1 头号] page.evaluate(EVAL_SEND_JS) 无超时包裹**（senders/taobao_mtop.py:113）——页面 JS promise 未决（页面冻结/风控打断/mtop jsonp 超时机制失效）→ await 永久悬挂。
2. [P2] playwright 启动/launch 阶段挂起（与"重试看到 60s 超时而非 500"部分矛盾，未完全排除；首次尝试可能是 500 形态）。

### 环境差异假设（集成 vs T2 探针）

T2 管线级 sent（10-07）为独立探针进程；本次在 web 服务进程（12 平台监听并发）。且**房间不同**（本次 2402661083849123 vs 探针 1917110531243955/4091720237373013）——两次挂起都是确定性复现（同形状无 result），指向稳定条件而非偶发竞态。分辨动作：换探针房间对照（T6 清单项）+ T5 阶段日志锁定挂点。

### 结构性缺陷（根因三件套，见计划 §已知问题）

① 四阶段预算 85s > 前端 60s 中止（app.js:801）；② record_attempt 发起即占窗 → DUPLICATE 影子；③ sender 无异常围栏 → 异常形态为 500 且丢审计 result 行。T1 结论：**三件套全部实证成立**；修复=T2（围栏+预算 ≤55s，全部 await 包 wait_for，消灭无超时挂点类）+T4（对账轮询）。

### 根因定稿（2026-10-08 10:42 网络观测实证）

**挂起机制 = x5sec 风控触发 noCaptcha 验证，headless 瞬态页无人可解，promise 永挂。**

分阶段计时探针（独立干净进程，无监听/服务并发）：`launch=0.1s ✓ | goto=0.2s ✓ | topic_anchor=1.0s ✓（房间在播）| mtop_lib=0.1s ✓ | eval_mtop=20s TIMEOUT`。

网络层证据：mtop publish 响应 URL=`/h5/mtop.taobao.iliad.comment.publish/1.0/_____tmd_____/report?x5secdata=xgba…`（x5sec 风控挑战）+ `cf.aliyun.com/nocaptcha/initialize.jsonp`（验证组件初始化）——**请求发出且服务端有响应，但响应是风控验证流程而非发布结果**；mtop 库等待验证完成 → promise 未决 → evaluate 无超时 → 永挂。

- 「集成进程并发」假设否决（独立进程同挂）；「房间/topic 问题」否决（秒级锚定成功）。
- 与学习 [douyin-send-resident-session] 同构：瞬态窗口触发行为风控——10-07 探针连发是今日触发的可能导火索。
- 修复映射：T2 超时包裹（挂起→结构化 UNKNOWN）+ x5sec/nocaptcha 信号检测（回执 fix_hint=「风控验证待人工，勿盲目重试」）；**验证通过的形态（有头/常驻会话）=PLAN B**，如验收阶段复现则按缺陷卡流程裁定。
- 附带发现：runbook 周检命令 `--replay` 缺 `--page-eval`（纯 HTTP 形态=T1 实证必败 RGV587）——T5 修正。
- 本次 T1 探针零弹幕落地（全部在风控层被拦，无真实发送成功）。
