# M0 发送探针组（T2）——使用说明

生成：/autoplan 批准计划 T2（2026-10-06）| 纪律：R17/R19/R22/R23/F5/F8
**探针账号环境必须与实发一致（R17）**；所有探针弹幕带 `[M0]` 前缀（回环识别 F8）。

## 探针清单（9 平台）

| 平台 | 路线 | 工具 | 前置 | 备注 |
|------|------|------|------|------|
| bilibili | API | `bilibili_api_probe.py` | auth 预检 ✅ 已过（SESSDATA+bili_jct 有效） | 实发需直播中 |
| taobao | DOM | `dom_send_probe.py --platform taobao` | taobao_profile ✅ | 直播间 URL |
| 1688 | DOM | `dom_send_probe.py --platform 1688` | 1688_profile ✅ | 直播间 URL |
| xiaohongshu | DOM | `dom_send_probe.py --platform xiaohongshu` | xhs_profile ✅ | 直播间 URL |
| jd | DOM | `dom_send_probe.py --platform jd` | jd_profile ✅ | zhibo.jd.com/liveroom?liveId=… |
| wechat_channels | DOM | `dom_send_probe.py --platform wechat_channels` | 后台会话（助手发言入口） | 管理后台 URL |
| douyin | DOM | `dom_send_probe.py --platform douyin` | cookie 注入（douyin_cookies.json 53 条） | live.douyin.com/<room_id> |
| kuaishou | DOM | `dom_send_probe.py --platform kuaishou` | storage_state 注入 | live.kuaishou.com/u/<主播> |
| douyu | DOM(+R19) | `dom_send_probe.py --platform douyu` | acf_uid/acf_auth ✅（R19 命中） | douyu.com/<room_id> |
| huya | DOM | `dom_send_probe.py --platform huya` | **⚠️ R19 缺字段**——先跑登录窗口补齐 | huya.com/<room_id> |

## 运行方式（attended——弹可见窗口，人工旁观）

```bash
# 0. 离线审计（已跑，结果见探针卡片 R19 行）
python tools/send_probes/cookie_audit.py

# 1. B站 auth 预检（已过 ✅）
python tools/send_probes/bilibili_api_probe.py --check

# 2. 各平台 DOM 探针（对应直播间开播后逐台执行）
python tools/send_probes/dom_send_probe.py --platform taobao --room-url "<直播间URL>" --sends 3
python tools/send_probes/bilibili_api_probe.py --room-id <房间号> --sends 2
```

## 判定语义（F5/R36）

- **SUCCESS**：DOM=marker 回显于聊天流；API=HTTP 200 且 code==0
- **FAIL**：显式错误信号（禁言/验证码/登录提示/接口错误码）
- **UNKNOWN**：无回显无错误（虚拟列表/慢渲染可能）——不计熔断语义，探针如实记录
- **BLOCKED**：前置不满足（未开播/未发现输入框/goto 失败）——卡片记录 blocked_reason

## 卡片回填

每平台运行后生成 `cards/<platform>-<ts>.json`，把结论回填 `docs/testing/m0-send-probe-cards.md`
（成功 / blocked+降级路线 / NEEDS_LOGIN），回填完成后矩阵可行性终判。

## 降级路线（R19/3.1）

spike 失败平台标记 `blocked` 并公开降级路线：DOM 备选 / 协议边界申报——不进入永久搁置区。

## 社区资料比对结论（R23，2026-10-06 WebSearch）

- **斗鱼**：公开开源实现（dyproto/pydouyu/douyudm）全部只做**接收**；发送需网页 WS token
  （ltkid/stk/vk）或企业开放平台 Aid/Secret——DOM 路线是社区事实主流（Selenium 先例）
- **抖音**：发送比接收多一层 sign_url 级签名（X-Bogus/X-Gnarly/msToken 绑定浏览器指纹）；
  官方「弹幕小玩法」需企业资质（R24 否决记录成立）——DOM 路线优先（R22 判断验证）
- **快手**：官方弹幕玩法 API 需开放平台资质；无公开发送逆向——DOM 优先
- 来源：pypi.org/project/dyproto、github.com/Kexiii/pydouyu、npmjs.com/package/douyudm、
  eulerstream.com/docs/sign-server/custom-sign-servers、developer.open-douyin.com（弹幕玩法指南）、
  open.kuaishou.com（弹幕玩法接口）、w3xue.com（斗鱼 WS 协议）
