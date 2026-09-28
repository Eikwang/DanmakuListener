# Changelog

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
