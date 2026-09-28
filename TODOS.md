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
