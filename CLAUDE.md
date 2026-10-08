# DanmakuListener

十二平台直播弹幕监听 + AutoDanmu 弹幕发送（混合分层引擎：协议直连 + 受控页面）。

## Testing

- 运行命令：`python -m pytest tests/ -q`（pytest；测试目录 tests/unit/，全量 ~650 用例 / ~80s）
- 前端对账测试：`node --test "tests/js/*.test.mjs"`（Node ≥21，内置 runner 零依赖；6 用例）
- 修复 bug 时写回归测试；新增行为配行为测试；提交不得使既有测试失败

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec
