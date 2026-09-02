"""DanmakuAddon — mitmproxy 插件

拦截 WebSocket/HTTP 响应，执行域名白名单/进程过滤/页面Hook/JS Hook。
所有钩子方法由 mitmproxy 事件驱动调用。
"""

import re
from typing import Any, Callable, Coroutine, Dict, List
from urllib.parse import urlparse, parse_qs

from loguru import logger

from danmaku_listener.bus.dedup_filter import DedupFilter
from danmaku_listener.engines.protobuf_decoder import ProtobufDecoder, DecodedMessage
from danmaku_listener.engines.ssl_whitelist import SSLWhitelistChecker
from danmaku_listener.engines.process_filter import ProcessFilter


class DanmakuAddon:
    """mitmproxy 弹幕拦截插件

    钩子方法对应 mitmproxy 事件：
    - http_connect: HTTP CONNECT 请求（SSL 解密决策前置日志）
    - tls_clienthello: TLS ClientHello（SSL 解密/直传决策）
    - response: HTTP 响应（CSP 删除 + JS Hook）
    - websocket_start: WebSocket 连接建立（识别弹幕流）
    - websocket_message: WebSocket 消息（Protobuf 解码 + 消息分发）
    - websocket_end: WebSocket 连接关闭（触发重连）
    """

    # 弹幕 WebSocket 域名匹配模式
    _WEBCAST_WS_PATTERN = re.compile(
        r"webcast\d+-ws-web-\w+\.(douyin|amemv)\.com"
    )

    # 已知的弹幕消息 method 集合
    _KNOWN_DANMAKU_METHODS = {
        "WebcastChatMessage", "WebcastGiftMessage",
        "WebcastLikeMessage", "WebcastMemberMessage",
        "WebcastSocialMessage", "WebcastControlMessage",
        "WebcastRoomUserSeqMessage", "WebcastFansclubMessage",
    }

    def __init__(
        self,
        message_callback: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]],
        settings: Any,
    ):
        """初始化弹幕拦截插件

        Args:
            message_callback: 异步消息回调函数
            settings: Settings 配置实例
        """
        self._message_callback = message_callback
        self._settings = settings

        # SSL 白名单检查器
        extra_hostnames = getattr(settings, "ssl_decrypt_extra_hostnames", [])
        self.ssl_checker = SSLWhitelistChecker(extra_hostnames=extra_hostnames)

        # 进程过滤器
        process_filter_list = getattr(settings, "process_filter_list", [])
        self.process_filter = ProcessFilter(allowed_processes=process_filter_list)

        # 去重过滤器
        dedup_window = getattr(settings, "dedup_window_size", 300)
        self._dedup_filter = DedupFilter(window_size=dedup_window)

        # Protobuf 解码器
        self._protobuf_decoder = ProtobufDecoder()

        # 活跃的弹幕 WebSocket 连接：flow_id → room_id
        self._active_ws_flows: Dict[str, str] = {}

    # ===== mitmproxy 钩子方法 =====

    def http_connect(self, flow: Any) -> None:
        """HTTP CONNECT 请求钩子

        记录 CONNECT 请求日志。SSL 解密决策在 tls_clienthello 中执行。

        Args:
            flow: mitmproxy HTTPFlow 对象
        """
        host = flow.request.host
        port = flow.request.port
        logger.debug(f"HTTP CONNECT: {host}:{port}")

    def tls_clienthello(self, data: Any) -> None:
        """TLS ClientHello 钩子 — SSL 解密/直传决策

        根据域名白名单决定是否解密 HTTPS 流量：
        - 白名单内：ignore_connection=False（允许解密）
        - 白名单外：ignore_connection=True（直接转发不解密）

        Args:
            data: mitmproxy ClientHelloData 对象
        """
        hostname = data.client_hello.sni
        if not hostname:
            return

        in_whitelist = self.ssl_checker.check(hostname)
        if not in_whitelist:
            data.ignore_connection = True
            logger.debug(f"SSL passthrough (not in whitelist): {hostname}")
        else:
            logger.debug(f"SSL decrypt (in whitelist): {hostname}")

    def response(self, flow: Any) -> None:
        """HTTP 响应钩子 — CSP 删除 + JS Hook

        处理流程：
        1. 页面 Hook：删除 CSP 头 + 可选禁用自动播放 → AC-006
        2. JS Hook：绕过 PausePop 无操作检测 → AC-015（Task-12 填充）

        Args:
            flow: mitmproxy HTTPFlow 对象
        """
        if not flow.response:
            return

        # 页面 Hook（CSP 删除 + 自动播放控制）
        self._hook_page(flow)

        # JS Hook（Task-12 填充）
        self._hook_js(flow)

    def _hook_page(self, flow: Any) -> None:
        """页面 Hook：CSP 头删除 + 自动播放控制 → AC-006

        条件：host 为抖音域名 + Content-Type 为 text/html

        Args:
            flow: mitmproxy HTTPFlow 对象
        """
        host = flow.request.host
        # 仅处理抖音域名
        if not host.endswith("douyin.com"):
            return

        content_type = flow.response.headers.get("content-type", "")
        if "text/html" not in content_type:
            return

        # 删除 CSP 头 →/ AC-006
        if "Content-Security-Policy" in flow.response.headers:
            del flow.response.headers["Content-Security-Policy"]
            logger.debug(f"Removed CSP header for {flow.request.pretty_url}")

        # 自动播放控制（auto_pause=True → 禁用自动播放）
        auto_pause = getattr(self._settings, "auto_pause", False)
        if auto_pause:
            text = flow.response.get_text()
            if 'autoplay&quot;:true' in text:
                text = text.replace('autoplay&quot;:true', 'autoplay&quot;:false')
                flow.response.set_text(text)
                logger.debug(f"Disabled autoplay for {flow.request.pretty_url}")

    def _hook_js(self, flow: Any) -> None:
        """JS Hook：无操作检测绕过 → AC-015

        条件：application/javascript + status_code=200 + 文件名以 PausePop 开头
        处理：
        1. PausePop 检测绕过：if(!(0,a.DJ)()&&a.includes("live")){ → if(false){
        2. force_polling 模式：if(!this.stopPolling){ → if(true){

        Args:
            flow: mitmproxy HTTPFlow 对象
        """
        content_type = flow.response.headers.get("content-type", "")
        if "application/javascript" not in content_type.lower():
            return

        if flow.response.status_code != 200:
            return

        url = flow.request.pretty_url
        filename = url.split("?")[0].rsplit("/", 1)[-1]

        # 仅处理 PausePop 文件
        if not filename.lower().startswith("pausepop"):
            return

        js = flow.response.get_text()
        modified = False

        # PausePop 无操作检测绕过 → AC-015
        idle_pattern = re.compile(
            r'if\(!\(\d{1,},\w{1,}\.DJ\)\(\).+\w{1,}\.includes\("live"\)\)\{'
        )
        if idle_pattern.search(js):
            js = idle_pattern.sub("if(false){", js)
            modified = True
            logger.info(f"Bypassed JS idle detection: {filename}")

        # force_polling 模式：强制轮询
        force_polling = getattr(self._settings, "force_polling", False)
        if force_polling:
            stop_polling_pattern = re.compile(r'if\(!this\.stopPolling\)\{')
            if stop_polling_pattern.search(js):
                js = stop_polling_pattern.sub("if(true){", js)
                modified = True
                logger.info(f"Force polling enabled: {filename}")

        if modified:
            flow.response.set_text(js)

    def websocket_start(self, flow: Any) -> None:
        """WebSocket 连接建立钩子 → AC-003

        识别弹幕流 WebSocket 连接，提取 room_id，通知 ProxyEngine。

        Args:
            flow: mitmproxy HTTPFlow 对象
        """
        host = flow.request.host

        if not self._WEBCAST_WS_PATTERN.match(host):
            return

        # 提取 room_id
        room_id = self._extract_room_id(flow)

        # 记录活跃 flow
        self._active_ws_flows[flow.id] = room_id

        logger.info(f"WebSocket danmaku stream connected: host={host}, room_id={room_id}")

        # 通知 ProxyEngine
        import asyncio
        asyncio.create_task(self._message_callback({
            "type": "ws_connected",
            "room_id": room_id,
            "host": host,
        }))

    def websocket_message(self, flow: Any) -> None:
        """WebSocket 消息钩子 → AC-004, AC-010, AC-011, AC-018, AC-019

        处理流程：
        1. 检查是否为弹幕流
        2. 忽略客户端消息
        3. Protobuf 解码
        4. 去重过滤
        5. 分发已知消息类型

        Args:
            flow: mitmproxy HTTPFlow 对象
        """
        # 检查是否为弹幕流
        if flow.id not in self._active_ws_flows:
            return

        # 获取最新消息
        if not flow.websocket or not flow.websocket.messages:
            return

        last_msg = flow.websocket.messages[-1]

        # 忽略客户端消息
        if last_msg.from_client:
            return

        # 获取 room_id
        room_id = self._active_ws_flows.get(flow.id, "")

        # Protobuf 解码
        content = last_msg.content
        if isinstance(content, str):
            content = content.encode("utf-8")

        decoded_messages: List[DecodedMessage] = self._protobuf_decoder.decode(content)
        if not decoded_messages:
            return

        # 遍历解码后的消息
        for decoded in decoded_messages:
            # 去重过滤 → AC-019
            if room_id and decoded.msg_id:
                if self._dedup_filter.should_filter(room_id, decoded.msg_id):
                    continue

            # 未知消息类型静默忽略 → AC-018
            if decoded.method not in self._KNOWN_DANMAKU_METHODS:
                continue

            # 分发消息
            import asyncio
            asyncio.create_task(self._message_callback({
                "type": "danmaku",
                "room_id": room_id,
                "method": decoded.method,
                "payload": decoded.payload,
                "msg_id": decoded.msg_id,
                "platform": "douyin",
            }))

    def websocket_end(self, flow: Any) -> None:
        """WebSocket 连接关闭钩子 → AC-012

        检测弹幕流断开，通知 ProxyEngine 触发重连。

        Args:
            flow: mitmproxy HTTPFlow 对象
        """
        # 检查是否为已注册的弹幕流
        if flow.id not in self._active_ws_flows:
            return

        room_id = self._active_ws_flows.pop(flow.id)

        logger.info(f"WebSocket danmaku stream disconnected: room_id={room_id}")

        # 通知 ProxyEngine → 触发重连
        import asyncio
        asyncio.create_task(self._message_callback({
            "type": "ws_disconnect",
            "room_id": room_id,
        }))

    # ===== 内部辅助方法 =====

    def _extract_room_id(self, flow: Any) -> str:
        """从 WebSocket URL 中提取 room_id

        Args:
            flow: mitmproxy HTTPFlow 对象

        Returns:
            room_id 字符串，提取失败返回空字符串
        """
        try:
            url = flow.request.pretty_url
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            room_id_list = params.get("room_id", [])
            return room_id_list[0] if room_id_list else ""
        except Exception as e:
            logger.warning(f"Failed to extract room_id from URL: {e}")
            return ""
