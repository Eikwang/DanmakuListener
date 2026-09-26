# 许可证审计（阶段 1 前置，Eng 评审 F10）

审计原则：只借鉴协议行为特征与消息结构，不复制代码；GPL/AGPL 类强传染许可证一票否决。

| 参考项目 | 许可证 | 核查方式 | 结论 |
|---|---|---|---|
| DouyinBarrageGrab | MIT（本地 LICENSE 文件，Copyright 2022 一只小白猿） | 本地核查 2026-09-27 | ✅ 可参考 |
| ordinaryroad-barrage-fly | Apache-2.0（本地 LICENSE 文件） | 本地核查 2026-09-27 | ✅ 可参考；保留 NOTICE 义务（如分发） |
| wxlivespy | MIT（Electron React Boilerplate 衍生） | 本地核查 2026-09-27 | ✅ 可参考 |
| blivedm（B站 Python 参考） | MIT（GitHub xfgryujk/blivedm，**线上待复核**） | 线上知识，未本地核查 | ⚠️ 阶段 1 开工前复核 |
| ordinaryroad-live-chat-client | 与 barrage-fly 同团队，预期 Apache-2.0，**待线上确认** | 未核查 | ⚠️ 获取源码时一并确认（见依赖清单） |

## 行为准则

1. 协议实现以**线上抓包对照**为准，参考项目仅用于理解握手流程与消息结构。
2. 不复制任何参考项目的源码文件、注释块或独有表达式。
3. 若发现某依赖为 GPL 类，立即停止对照并升级到项目所有者裁定。
4. 本审计在每次新增参考项目时更新。
