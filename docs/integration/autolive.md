# AUTOlive 接入指南（docs/integration/）

> AUTOlive 是本系统唯一前端。本指南覆盖连接、鉴权、消费与故障处理的全部要点。
> 机读 Schema：[../contract/schema.json](../contract/schema.json)。

## 1. 连接与鉴权

- 传输：本机 WebSocket（默认 `ws://127.0.0.1:<port>/ws`，端口可配置）；
  可选 HTTP 回调（v1 未实现，预留）。
- **默认只绑定 127.0.0.1**——"本机"边界由 bind 地址保证，token 是第二道防线。
- 预共享 token：经环境变量 `DANMAKU_TOKEN` 或受限权限文件注入；连接时携带，
  服务端常量时间比较。生成步骤见部署清单（docs/ops/）。

## 2. 消息消费

1. 每条消息为契约 v1 线格式 JSON（见 schema.json）。
2. 按 `category` 分流：`business` → 数字人互动处理；`system` → 状态处理。
3. **忽略未知字段与未知 type 并计数**——契约 additive-only，忽略是正确行为而非容错。
4. 去重：按 `envelope.msg_id`（平台原生 ID）去重；无 msg_id 的平台在切换期允许重复
   （平台说明见 platforms/ 手册）。AUTOlive 重启后去重窗口从零开始（冷启动）。
5. 顺序：同房间按 `seq` 单调；发现 seq 跳跃即等待随后的 GAP 消息确认缺口。

## 3. 背压与慢消费

- 消费过慢时服务端有界环形缓冲兜底；溢出按类型分级丢弃（先丢 LIKE/ENTER_ROOM/DANMU）。
- 丢弃不静默：任一窗口丢弃 > 0 会收到该房间的 `GAP`（reason=backpressure）+
  `BACKPRESSURE` 窗口计数。
- 建议消费端独立 asyncio 任务 + 自身有界队列，避免阻塞 WS 读循环。

## 4. 心跳与失联

- 引擎每 10 秒发一条 `HEARTBEAT`；连续 3 个周期未收到 → 判定引擎失联，AUTOlive 告警呈现。
- 引擎自身对平台连接有独立静默检测（30s 超时触发重连）——两套心跳独立，勿混用。
- 失联恢复后会收到 `RECOVERED` 事件（含故障持续时长）。

## 5. 登录态处理（NEEDS_LOGIN 闭环）

1. 收到 `NEEDS_LOGIN`：payload.failure 含 reason_code/fix_hint/docs_anchor 三段式。
2. 若带 `interactive_login`（QR base64 或一次性 URL）：在 AUTOlive 界面呈现给操作人。
3. 操作人完成扫码/登录后，引擎自动检测登录态恢复并继续监听（自动恢复，无需重启）。
4. 视频号 session 有效期短，这是**常规路径**——AUTOlive 界面应为此设计常驻入口。

## 6. 兜底与引擎切换

- `ENGINE_STATUS` 消息携带当前活跃引擎标识（`protocol:x` / `proxy:x` / `fallback:x`）。
- 主路线失效（`ROUTE_FAILED`）期间若开启兜底，注入路线接管，消息继续但延迟放宽
  （验收 <3s）且活跃引擎标识变化——AUTOlive 界面应展示当前引擎。
- 兜底由配置人工开启（全局→平台→房间三级粒度），见运维手册。

## 7. 最小接入示例

```python
import asyncio, json, websockets  # websockets 由 AUTOlive 侧自备

async def main():
    async with websockets.connect("ws://127.0.0.1:8765/ws", extra_headers={"Authorization": "Bearer <token>"}) as ws:
        async for raw in ws:
            msg = json.loads(raw)
            if msg["category"] == "business":
                print(f'[{msg["platform"]}:{msg["room_id"]}] {msg["type"]}: {msg["payload"]}')
            elif msg["type"] == "GAP":
                print(f'数据缺口 {msg["payload"]["window_start"]}~{msg["payload"]["window_end"]} ({msg["payload"]["reason"]})')

asyncio.run(main())
```
