"""虎牙直播弹幕协议编解码器（阶段 3b）

**协议状态：draft（huya-0-draft）**——帧结构与嵌入式 protobuf 消息细节
需抓包实测校准（计划 Open Questions 已列）。当前实现覆盖社区已知的
帧布局与生命周期，消息解析留接口（parse_payload 钩子）。

社区已知帧布局（大端）：
- 4B 总长 + 2B 头长(=8?) + 2B 版本 + 4B 序列 + ... + 嵌入式 protobuf payload
- WS: wss://hws.huya.com/wsc/websocket

引擎生命周期（连接/心跳/重连/GAP）与其它协议引擎同构；payload 解析
经 ``parse_payload`` 钩子注入——实测后以 huya proto 定义替换。
"""

import struct
from typing import Any, Callable, Dict, List, Optional, Tuple

PROTOCOL_VERSION = "huya-0-draft"
HEADER_SIZE = 12
WS_URL = "wss://hws.huya.com/wsc/websocket"
HEARTBEAT_INTERVAL = 30.0


class HuyaFrameError(ValueError):
    """帧解析失败"""


def encode_frame(payload: bytes, proto_ver: int = 1, seq: int = 0) -> bytes:
    """编码一帧（大端：4B 总长 + 2B 头长(=12) + 2B 版本 + 4B 序列 + payload）

    帧细节（头长/版本/序列字段布局）为 draft，以抓包校准为准。
    """
    header_len = HEADER_SIZE
    total = header_len + len(payload)
    return struct.pack(">IHHI", total, header_len, proto_ver, seq) + payload


def decode_frames(data: bytes) -> List[Tuple[int, int, bytes]]:
    """解码粘包流：返回 [(proto_ver, seq, payload)]"""
    frames: List[Tuple[int, int, bytes]] = []
    offset = 0
    total_len = len(data)
    while offset + HEADER_SIZE <= total_len:
        total, header_len, proto_ver, seq = struct.unpack(">IHHI", data[offset : offset + HEADER_SIZE])
        if total < header_len or offset + total > total_len:
            raise HuyaFrameError(f"total={total} 超出缓冲（offset={offset} total={total_len}）")
        payload = data[offset + header_len : offset + total]
        frames.append((proto_ver, seq, payload))
        offset += total
    return frames


def map_payload(payload: bytes, seq: int, ts: int, parse_hook: Optional[Callable] = None) -> List[Dict[str, Any]]:
    """payload → 契约线格式片段

    实测校准前默认返回空（未知结构不猜测）；注入 parse_hook（实测后实现）
    可在不改引擎的情况下接入真实解析。
    """
    if parse_hook is None:
        return []
    return parse_hook(payload, seq, ts)
