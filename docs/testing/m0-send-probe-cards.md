# M0 发送探针卡片（T2）——回填矩阵

生成：/autoplan 批准计划 T2 | 探针工具：tools/send_probes/ | 判定语义见其 README

> 回填规则：每平台探针运行后，把卡片结论（cards/<platform>-<ts>.json）汇总到下表；
> 成功 → 矩阵可行性终判提升；blocked → 附降级路线；NEEDS_LOGIN → 补登录后重探。

## 探针矩阵（M0 终判）

| 平台 | 路线 | 状态 | 判定 | 卡片 | 备注 |
|------|------|------|------|------|------|
| bilibili | API | ✅ auth 预检通过（离线，2026-10-06） | 待实发 | — | SESSDATA+bili_jct 有效，nav_code=0；开播后 `--room-id` 实发 |
| taobao | DOM | ⏳ 待运行（profile 就绪） | — | — | 需直播间开播 |
| 1688 | DOM | ⏳ 待运行（profile 就绪） | — | — | 需直播间开播 |
| xiaohongshu | DOM | ⏳ 待运行（profile 就绪） | — | — | 需直播间开播；监听侧帧结构同待校准 |
| jd | DOM | ⏳ 待运行（profile 就绪） | — | — | zhibo.jd.com 独立站 |
| wechat_channels | DOM | ⏳ 待运行（后台会话） | — | — | 助手发言身份（用户已实测可发送） |
| douyin | DOM | ⏳ 待运行（cookie 注入） | — | — | R23 结论：发送=sign_url 级签名，DOM 优先（R22 验证） |
| kuaishou | DOM | ⏳ 待运行（storage_state 注入） | — | — | 同上 |
| douyu | DOM(+R19) | ✅ R19 字段命中（acf_uid/acf_auth） | 待实发 | — | 社区发送主流=DOM（R23） |
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
