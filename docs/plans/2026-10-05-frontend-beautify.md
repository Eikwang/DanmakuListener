# 前端美化计划：布局优化 + 样式精修（真实浏览器证据驱动）

> 来源：/autoplan（2026-10-05，用户需求："前端显示非常杂乱，布局混乱，请使用真实浏览器测试并美化前端样式，优化布局"）
> 状态：**已实施（2026-10-05）**——D1 用户裁定**全新视觉重设计**（否决深色精修推荐）+ D2 批准；
> 新视觉锚定 AUTOlive design_tokens（Tailwind 色板：slate 暗阶 + blue-600 主色 + 宿主语义色）；
> $B 浏览器三轮迭代（before → after → 右栏补回/按钮主色终版）；554 单测全绿；
> AUTOlive 已同步（内容戳 cddc0a47）。
> 基线：main @ 99070f1（四项功能改版后 v=6）
> 证据：.gstack/browse-reports/2026-10-05-1131/screenshots/before-desktop.png（$B 真实浏览器，1280px，用户 serve 实况：1688 房间监听中）

## Implementation plan

### 浏览器实测发现的问题清单（before-desktop.png 逐项）

| # | 问题 | 位置 | 严重度 |
| --- | --- | --- | --- |
| P1 | 8 个类型过滤 chips 三行堆叠，把"弹幕"标题挤成竖排、"暂停滚动"按钮挤成竖排文字 | 弹幕区头部 | 高——最刺眼的杂乱源 |
| P2 | 平台徽章"1688"竖排两行、状态徽章"监听中"竖排 | 左栏房间行 | 高 |
| P3 | 右栏 240px 过窄："添加"按钮溢出边缘、屏蔽关键词输入框贴边、统计行无呼吸空间 | 右栏 | 高 |
| P4 | 互动区（右上）无消息时纯空白，无空态提示——与信息区（有消息）视觉失衡 | 右列上部 | 中 |
| P5 | 区块间无视觉边界：三区底色几乎相同（--bg-secondary），分隔仅靠 1px 边线，主次不清 | 全局 | 中 |
| P6 | 间距系统不一致：section padding 16px/12px 混用、消息行 padding 3px/6px 混用 | 全局 | 中 |
| P7 | 消息行无 hover 反馈、无时间信息，长内容换行后行高不齐 | 三区消息流 | 低 |

### 美化方案（保持深色控制台风格，v=7）

**A. 布局结构（style.css 为主）**
- A1 弹幕区头部重构：`标题（nowrap）| chips 紧凑单行区（flex:1 可换行但高度受控）| 暂停滚动按钮（nowrap）`——chips 降为 10px 字号/1px 5px padding/gap 3px，标题不再被挤压
- A2 三区卡片化：`.danmaku-section`/`.stream-section` 独立底色（--bg-card 系）+ 圆角 8px + 区标题带 3px 主题色条前缀，主次分明
- A3 右列宽度 340→380px；右栏（统计列）240→280px——解决 P3 溢出
- A4 互动/信息区高度比 45%/55%（flex-basis）；消息容器 padding 统一 10px 12px

**B. 组件修复**
- B1 `.platform-tag`/`.status-badge` 加 `white-space: nowrap; flex-shrink: 0`——徽章不再竖排（P2）
- B2 房间行结构：房号 `overflow: ellipsis`（长 feedId 不撑爆）、按钮组保持紧凑
- B3 关键词表单 `min-width: 0` + 按钮不收缩——修复溢出（P3）
- B4 chips 增加"全"切换（一键全开/全收）？——**砍掉**：非必要新功能，保持纯样式专项

**C. 空态与反馈**
- C1 互动区/信息区加空态提示（"暂无礼物/点赞/关注"、"暂无入场/房间信息"），首个消息到达时移除（app.js appendMessage 内已有 empty-state 移除逻辑，扩展到三容器）（P4）
- C2 消息行 hover 高亮 `background: rgba(255,255,255,0.03)`（P7）
- C3 消息行时间戳：可选轻量 `HH:MM` 右对齐淡色——**做**：消息密时区分批次，成本 2 行 JS

**D. 一致性（P5/P6）**
- D1 间距 token：section 内边距统一 12px、区块标题 margin 统一、消息行 padding 统一 5px 10px
- D2 字号层级：区块标题 13px/大写/字距、消息 13px、统计值 tabular-nums（已有）

## 改动面（3 文件 + 版本号）
- `web/static/style.css`：主体改动（A/B/C/D 全部）
- `web/static/index.html`：互动/信息区空态 div；app.js?v=7
- `web/static/app.js`：三容器空态移除逻辑（约 6 行）+ 消息时间戳（约 3 行）
- **零后端改动、零逻辑重构**（UI 专项边界）

## NOT in scope
- 主题切换/亮色模式
- chips 功能变更（B4 明确砍掉）
- 响应式深化（现有 1100px/900px 折叠规则保留）
- AUTOlive 主程序界面

## What already exists
- CSS 变量体系（:root 色板 19 个 token）——沿用扩展
- 深色主题底子（P5 只需区块底色分级，不换色系）
- appendMessage 三容器路由（上轮 v=6）——空态扩展点现成

## Review record

### Design 阶段（7 维度，浏览器证据评分 1-10）
| 维度 | 现状 | 方案后 | 依据 |
| --- | --- | --- | --- |
| 信息层级 | 3（chips 淹没标题、主次不分） | 8 | A1/A2 区块主次分明 |
| 布局结构 | 4（溢出、竖排、空白失衡） | 8 | A3/B2/B3 修复全部结构伤 |
| 一致性 | 4（间距混用、徽章样式各异） | 8 | D1 token 化 |
| 可读性 | 6（深色对比尚可） | 8 | C2/C3 行级改进 |
| 状态可见 | 6（空态只有弹幕区） | 9 | C1 三区空态 |
| 组件工艺 | 4（竖排徽章=明显缺陷） | 9 | B1/B2 |
| 视觉美观 | 4 | 8 | 整体卡片化+间距节奏 |

**已裁定**：C3 时间戳加入（ taste→推荐，消息密集时定位批次）；B4 砍掉（scope 纪律）。

### Eng 阶段
**范围挑战**：无扩大——3 个静态文件，零 Python 改动，554 单测基线不动（前端无单测覆盖渲染，以浏览器截图复验替代）。
**失败模式**：①chips 收窄后仍可能两行（1280px 宽度实测验证，可接受）②空态移除时机（首条消息即移除，重连不清空容器——无回归风险）③缓存（v=7 版本参数）。
**测试计划**：$B 浏览器 before/after 同机位截图对比（1280px）+ 控制台错误检查 + 554 单测回归 + AUTOlive copy_danmaku.py 同步。

### 共识表
| 议题 | Design | Eng | 结论 |
| --- | --- | --- | --- |
| 风格走向 | 保持深色精修 | 3 静态文件低风险 | 一致 |
| 时间戳 | 加入 | 2 行 JS 无风险 | 加入 |
| chips 功能 | 不动 | 不动 | 纯样式 |

## Decision Audit Trail

| # | 阶段 | 决策 | 分类 | 原则 | 理由 | 否决项 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | CEO | 纯样式专项：3 静态文件、零后端 | Mechanical | P5 显式 | 用户诉求=视觉杂乱，非功能 | 顺手重构渲染逻辑 |
| 2 | Design | 保持深色控制台风格精修 | Taste→gate | P3 务实 | 有 CSS token 体系，推倒重来风险大收益小 | 全新视觉方案 |
| 3 | Design | 消息时间戳加入 | Taste→推荐 | P1 完整 | 消息密集时可读性实质提升 | 砍掉保最小改动 |
| 4 | Design | chips "全选"开关砍掉 | Mechanical | P6 偏行动 | 非必要新功能，scope 纪律 | 加入 |
| 5 | Eng | 验证=浏览器截图对比（非单测） | Mechanical | P3 | 渲染层无单测基建 | 补 DOM 单测 |

<!-- autoplan-accepted:design -->
- 保持深色控制台风格，以"布局重构+组件修复+空态反馈+间距一致性"四层美化，不改色系不加新功能（时间戳除外）。
- 全部修复项以 before/after 同机位截图对比验收（1280px 桌面宽度）。
<!-- /autoplan-accepted:design -->

<!-- autoplan-accepted:eng -->
- 改动面锁定 web/static 三件（style.css/index.html/app.js），零 Python 改动；554 单测回归 + AUTOlive 拷贝同步（copy_danmaku.py）为完成定义。
- 前端缓存版本 v=6 → v=7。
<!-- /autoplan-accepted:eng -->
