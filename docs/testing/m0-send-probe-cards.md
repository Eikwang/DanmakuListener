# M0 发送探针卡片（T2）——回填矩阵

生成：/autoplan 批准计划 T2 | 探针工具：tools/send_probes/ | 判定语义见其 README

> 回填规则：每平台探针运行后，把卡片结论（cards/<platform>-<ts>.json）汇总到下表；
> 成功 → 矩阵可行性终判提升；blocked → 附降级路线；NEEDS_LOGIN → 补登录后重探。

## 探针矩阵（M0 终判）

| 平台 | 路线 | 状态 | 判定 | 卡片 | 备注 |
|------|------|------|------|------|------|
| bilibili | API | ✅ **实发 SUCCESS×2**（2026-10-07 实测） | 高（终判） | cards/bilibili-20261007-091159.json | HTTP 200/code=0；管线实发 sent ✓ 幂等 ✓ 去重 ✓；F8 回环数据链路就绪 |
| taobao | DOM | ⚠️ **受限可行**（2026-10-07 实测 5 发） | 中（终判） | 截图 persistence_data/taobao-send-unknown.png | 技术链路全通（E5 钩子/发现模式选择器 chatInputCenter*/BtnSend div/滑块 iframe 感知检测+单次自动滑动）；风控滑块 headless 实发频发（3/5）且自动滑动未通过——需可见窗口/降频/风控冷却后重试 |
| 1688 | DOM | ✅ **实发 SUCCESS**（2026-10-07 实测；前两条已入聊天区截图实证） | 高（终判） | cards/1688-enter-test.png | 关键发现：fill 的 DOM 值不进框架 state、发送 div 点击不可靠——唯一可靠配方=**click 聚焦+逐键输入(press_sequentially)+Enter**；回显延迟大→input 清空为第二判据；引擎钩子已按配方覆写 |
| xiaohongshu | DOM | ⏳ 待运行（profile 就绪） | — | — | 需直播间开播；监听侧帧结构同待校准 |
| jd | DOM | ⏳ 待运行（profile 就绪） | — | — | zhibo.jd.com 独立站 |
| wechat_channels | DOM | ⏳ 待运行（后台会话） | — | — | 助手发言身份（用户已实测可发送） |
| douyin | DOM | ✅ **实发 SUCCESS×3**（2026-10-07 实测，指定文案） | 中高（终判：可行但需有头窗口） | cards/douyin-20261007-100544.json | cookie 文件注入被拒（bd_ticket_guard 指纹绑定）→ profile 登录闭环（douyin_login 扫码一次）+**有头窗口**（headless 聊天面板不出现）；contenteditable+\[class\*=send\] 命中；管线 sender 已接（DouyinProfileSender） |
| kuaishou | DOM | ✅ **实发 SUCCESS×3**（2026-10-07 实测，指定文案） | 高（终判） | cards/kuaishou-20261007-095159.json | storage_state 注入 17 cookie；textarea+text=发送 命中；无风控信号（R22 判断验证：DOM 路线直达） |
| douyu | DOM(+R19) | ✅ **实发 SUCCESS×3**（2026-10-07 实测，指定文案） | 高（终判） | cards/douyu-20261007-094617.json | cookie 注入 24 条（acf_* 会话充分，R19 断言验证）；.ChatSend-input 已不可见（UI 变更）→通用 input[placeholder] 命中；.ChatSend-button 正常；无风控信号 |
| huya | DOM | ⚠️ R19 缺字段 | 前置未满足 | — | 先跑登录窗口补齐（login_gate 语义）再探针 |

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
