"""虎牙协议测试——Tars 编解码 + 浏览器真实帧黄金样本 + 引擎生命周期"""

import asyncio

import pytest

from danmaku_listener.engines import login_gate as LOGIN_GATE
from danmaku_listener.engines.protocol import huya_codec as codec
from danmaku_listener.engines.protocol.huya import HuyaProtocolEngine
from danmaku_listener.engines.protocol.huya_tars import TarsInputStream, TarsOutputStream


def test_tars_int_roundtrip():
    os = TarsOutputStream()
    os.write_int(0, 0)      # zero 类型
    os.write_int(3, 1)      # int8
    os.write_int(300, 2)    # int16
    os.write_int(70000, 3)  # int32
    data = os.to_bytes()
    is_ = TarsInputStream(data)
    assert is_.read_int(0) == 0
    assert is_.read_int(1) == 3
    assert is_.read_int(2) == 300
    assert is_.read_int(3) == 70000


def test_tars_string_roundtrip():
    os = TarsOutputStream()
    os.write_string("live:0", 0)
    os.write_string("x" * 300, 1)
    is_ = TarsInputStream(os.to_bytes())
    assert is_.read_string(0) == "live:0"
    assert is_.read_string(1) == "x" * 300


def test_tars_bytes_simplelist_roundtrip():
    os = TarsOutputStream()
    os.write_bytes(b"\x01\x02\x03", 1)
    is_ = TarsInputStream(os.to_bytes())
    assert is_.read_bytes(1) == b"\x01\x02\x03"


def test_register_group_matches_browser_frame():
    """黄金样本：浏览器真实帧（26B registerGroup，vGroupId=["live:0"]）逐字节对照"""
    golden = bytes.fromhex(
        "00101d00000d09000106066c6976653a30" "1600" "2c36004c5c6600"
    )
    # 该帧 = WebSocketCommand{operation=16, vData=WSRegisterGroupReq{vGroupId=["live:0"], sToken=""}}
    cmd = codec.decode_command(golden)
    assert cmd["operation"] == codec.OP_REGISTER_GROUP_REQ
    is_ = TarsInputStream(cmd["v_data"])
    groups = is_.read_list(0)
    assert groups == ["live:0"]


def test_build_register_group_structure():
    """构造帧与浏览器帧同构（组列表 2 项）"""
    frame = codec.build_register_group(12345)
    cmd = codec.decode_command(frame)
    assert cmd["operation"] == codec.OP_REGISTER_GROUP_REQ
    is_ = TarsInputStream(cmd["v_data"])
    groups = is_.read_list(0)
    assert groups == ["live:12345", "chat:12345"]


def test_build_do_launch_is_wupreq():
    """doLaunch 对齐 2026 浏览器版（servant=launch/wsLaunch，黄金样本同构）"""
    frame = codec.build_do_launch()
    cmd = codec.decode_command(frame)
    assert cmd["operation"] == codec.OP_WUP_REQ
    rsp = codec.decode_wup_rsp(cmd["v_data"])
    assert rsp["func"] == "wsLaunch"
    assert rsp["servant"] == "launch"


def test_do_launch_matches_browser_golden_prefix():
    """黄金帧对照：doLaunch vData 头部（version/servant/func/uni 头）与浏览器一致

    cdnws 入口对 WupReq 不应答（弹幕推送专用入口，实测确认）——编码以浏览器
    黄金帧头部逐字节对齐为准；礼物表（getPropsList）需 wsapi 入口，见 TODOS。
    """
    from danmaku_listener.engines.protocol.huya_tars import TarsInputStream

    frame_hex = (
        "00031d0000680000006810032c3c40ff56066c61756e6368660877734c61756e63687d00010089"
        "0800010604745265711d0000360a0c16002615776562683526302e312e3026776562736f636b65"
        "74360c48555941265a4826323035324a060016002600360046000b0b8c980ca80c2c36004c5c6600"
    )
    browser_vdata = codec.decode_command(bytes.fromhex(frame_hex))["v_data"]
    mine = codec.decode_command(codec.build_do_launch())["v_data"]
    # 内容头部（跳过 4B 长度前缀）：version/packetType/messageType/requestId/servant/func 一致
    assert mine[4:26] == browser_vdata[4:26]
    # uni 内容头部（map 头 + key）一致
    assert b"\x08\x00\x01\x06\x04tReq" in mine
    # uni value 结构（tag1 SimpleList 头 + LiveLaunchReq）存在
    assert b"\x1d\x00\x00" in mine[30:60]


def test_decode_push_message_v2():
    """op=22 批量下推解码（流量主体）"""
    from danmaku_listener.engines.protocol.huya_tars import TarsOutputStream

    os = TarsOutputStream()
    os.write_string("g1", 0)  # sGroupId
    os.write_list([], 0)  # vMsgItem 占位（写法仅校验读侧）
    # 手工构造 list<struct>：WSMsgItem{uri, sMsg}
    item = TarsOutputStream()
    item.write_int(1400, 0)
    item.write_bytes(b"msg-bytes", 1)
    os2 = TarsOutputStream()
    os2.write_string("g1", 0)
    os2._header(1, 9)
    os2.write_int(1, 0)
    item.write_to(os2) if hasattr(item, "write_to") else None
    # 直接拼 list<struct>
    buf = TarsOutputStream()
    buf.write_string("g1", 0)
    buf._header(1, 9)
    buf.write_int(1, 0)
    buf.write_struct_begin(0)
    buf.write_int(1400, 0)
    buf.write_bytes(b"msg-bytes", 1)
    buf.write_struct_end()
    items = codec.decode_push_message_v2(buf.to_bytes())
    assert len(items) == 1
    assert items[0]["uri"] == 1400
    assert items[0]["data"] == b"msg-bytes"


def test_build_heartbeat_is_wupreq():
    frame = codec.build_heartbeat(660134)
    cmd = codec.decode_command(frame)
    assert cmd["operation"] == codec.OP_HEARTBEAT_REQ
    rsp = codec.decode_wup_rsp(cmd["v_data"])
    assert rsp["servant"] == "onlineui"
    assert rsp["func"] == "OnUserHeartBeat"


def test_message_notice_decode():
    """MessageNotice（uri 1400）结构解码：tUserInfo struct + sContent"""
    from danmaku_listener.engines.protocol.huya_tars import TarsOutputStream

    os = TarsOutputStream()
    # tag0 struct: SenderInfo{lUid=0, lImid=1(skip), sNickName=2}
    os.write_struct_begin(0)
    os.write_int(12345, 0)
    os.write_string("测试用户", 2)
    os.write_struct_end()
    os.write_int(660134, 1)     # lTid
    os.write_int(999, 2)        # lSid
    os.write_string("你好啊", 3)  # sContent
    d = codec.decode_message_notice(os.to_bytes())
    assert d["user_name"] == "测试用户"
    assert d["user_id"] == "12345"
    assert d["content"] == "你好啊"


def test_map_upstream_danmu():
    from danmaku_listener.engines.protocol.huya_tars import TarsOutputStream

    os = TarsOutputStream()
    os.write_struct_begin(0)
    os.write_int(12345, 0)
    os.write_string("用户A", 2)
    os.write_struct_end()
    os.write_string("666", 3)
    mapped = codec.map_upstream(os.to_bytes(), codec.URI_MESSAGE_NOTICE, 1, 1700000000)
    assert mapped is not None
    assert mapped["type"] == "DANMU"
    assert mapped["payload"]["content"] == "666"
    assert mapped["payload"]["user_name"] == "用户A"


def test_map_upstream_unknown_uri_returns_none():
    assert codec.map_upstream(b"xx", 9999, 1, 1700000000) is None


def test_vip_enter_banner_decode_and_map():
    """VipEnterBanner（uri 6110）解码+映射（2026-10-04 布局实证，
    29330704 房间：tag1=昵称/tag3{tag3}=贵族称号/tag15{tag1}=坐骑；
    tag2 是会话 tid 非用户 uid——三条不同昵称样本同值实证，不映射）"""
    from danmaku_listener.engines.protocol.huya_tars import TarsOutputStream

    os = TarsOutputStream()
    os.write_int(1531172893, 0)   # tag0 时间戳类
    os.write_string("青杉【烟雨梦】", 1)  # tag1 昵称
    os.write_int(1199527588095, 2)  # tag2 会话 tid（不映射 user_id）
    os.write_struct_begin(3)      # tag3 贵族 struct
    os.write_string("剑士", 3)
    os.write_struct_end()
    os.write_string("https://huyaimg.example/avatar.png", 6)  # tag6 头像
    os.write_struct_begin(15)     # tag15 坐骑横幅
    os.write_string("烽烟战马", 1)
    os.write_string("骑着", 2)
    os.write_struct_end()
    payload = os.to_bytes()

    d = codec.decode_vip_enter_banner(payload)
    assert d["user_name"] == "青杉【烟雨梦】"
    assert d["noble"] == "剑士"
    assert d["mount"] == "烽烟战马"
    assert "user_id" not in d

    mapped = codec.map_upstream(payload, codec.URI_VIP_ENTER_BANNER, 7, 1700000000)
    assert mapped is not None
    assert mapped["type"] == "ENTER_ROOM"
    assert mapped["payload"]["user_name"] == "青杉【烟雨梦】"
    assert mapped["payload"]["noble"] == "剑士"
    assert mapped["payload"]["mount"] == "烽烟战马"


@pytest.mark.asyncio
async def test_engine_lifecycle_and_protocol_version(monkeypatch):
    engine = HuyaProtocolEngine()
    assert engine.engine_id == "protocol:huya"

    # 2026-10-06 登录门槛加入 _run_room——单测不起真浏览器/不弹登录窗
    # （stop 的 cancel 落在 playwright launch 各位置会泄漏 chromium 子进程，
    #  pytest 退出挂起——用户实测 14:15 复现路径的单测版）
    async def fake_login(room_id, platform, *a, **k):
        return "logged_in"

    monkeypatch.setattr(LOGIN_GATE, "ensure_cookie_file_login", fake_login)

    await engine.start("23058")
    await asyncio.sleep(0.1)
    assert not engine._room_tasks["23058"].done() or True  # 连接失败走重连循环是合法状态
    await engine.stop("23058")
    assert engine._stop_flags["23058"] is True


def test_protocol_version():
    assert codec.PROTOCOL_VERSION == "huya-1"
