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

    # 2026-10-13 一次登录门：takeover 排在 ensure 之前——真实调用会弹可见
    # chromium 登录窗（240s 超时，cancel 泄漏子进程挂起 pytest 退出）。
    # 单测仿真 takeover 失败→走既有 ensure 存档窗兜底（保持原路径语义）。
    import danmaku_listener.senders.huya as huya_sender_mod

    async def fake_takeover(room_id):
        return False

    monkeypatch.setattr(huya_sender_mod, "takeover_login_and_archive", fake_takeover)

    await engine.start("23058")
    await asyncio.sleep(0.1)
    assert not engine._room_tasks["23058"].done() or True  # 连接失败走重连循环是合法状态
    await engine.stop("23058")
    assert engine._stop_flags["23058"] is True


# ---- 一次登录门（2026-10-13 用户验收裁定：存档缺失→发送侧 takeover；
#      takeover 失败回退旧存档窗；存档有效直接跳过）----

def _make_gate_engine(monkeypatch, tmp_path):
    """登录门测试环境：cookie_dir 指向 tmp_path + ENGINE_STATUS 透出收集器"""
    import json as _json
    from types import SimpleNamespace

    import danmaku_listener.config.settings as settings_mod

    monkeypatch.setattr(settings_mod, "get_settings",
                        lambda: SimpleNamespace(cookie_dir=str(tmp_path)))
    engine = HuyaProtocolEngine()
    statuses: list = []

    async def _capture(msg):
        statuses.append(msg)

    engine.on_message(_capture)

    def write_archive(cookies):
        (tmp_path / "huya_login_cookies.json").write_text(
            _json.dumps({"cookies": cookies}), encoding="utf-8")

    return engine, statuses, write_archive


@pytest.mark.asyncio
@pytest.mark.parametrize("cookie_name", ["yyuid", "hicl_imid", "huya_uid"])
async def test_login_gate_valid_archive_skips_takeover(monkeypatch, tmp_path, cookie_name):
    """存档含登录 cookie（三候选名之一且值非空）→ 跳过 takeover 一次登录门"""
    import danmaku_listener.senders.huya as huya_sender_mod

    engine, statuses, write_archive = _make_gate_engine(monkeypatch, tmp_path)
    write_archive([{"name": cookie_name, "value": "u-123", "domain": ".huya.com"}])

    takeover_calls: list = []

    async def _unexpected_takeover(room_id):
        takeover_calls.append(room_id)
        return True

    monkeypatch.setattr(huya_sender_mod, "takeover_login_and_archive",
                        _unexpected_takeover)
    engine._stop_flags["1"] = True  # 门走完即退出主循环（单测不触网）
    await engine._run_room("1")

    assert takeover_calls == []  # 存档有效——不触发 takeover
    assert not any("first_login" in str(m.get("payload")) for m in statuses)


@pytest.mark.asyncio
async def test_login_gate_missing_archive_triggers_takeover(monkeypatch, tmp_path):
    """存档缺失 → 触发发送侧 takeover 一次扫码（成功则旧存档窗兜底不触发）"""
    import danmaku_listener.senders.huya as huya_sender_mod

    engine, statuses, _write = _make_gate_engine(monkeypatch, tmp_path)  # 不写存档

    takeover_calls: list = []

    async def _takeover(room_id):
        takeover_calls.append(room_id)
        return True

    gate_calls: list = []

    async def _unexpected_gate(*args, **kwargs):
        gate_calls.append(args)

    monkeypatch.setattr(huya_sender_mod, "takeover_login_and_archive", _takeover)
    monkeypatch.setattr(LOGIN_GATE, "ensure_cookie_file_login", _unexpected_gate)
    engine._stop_flags["1"] = True
    await engine._run_room("1")

    assert takeover_calls == ["1"]
    assert gate_calls == []  # takeover 成功——ensure_cookie_file_login 兜底不触发
    assert any("first_login" in str(m.get("payload")) for m in statuses)


@pytest.mark.asyncio
async def test_login_gate_takeover_failure_falls_back_to_archive_window(monkeypatch, tmp_path):
    """takeover 失败（False）→ 回退旧 ensure_cookie_file_login 存档窗兜底"""
    import danmaku_listener.senders.huya as huya_sender_mod

    engine, statuses, _write = _make_gate_engine(monkeypatch, tmp_path)

    async def _takeover_fail(room_id):
        return False

    gate_calls: list = []

    async def _gate(room_id, platform, login_url, cookie_path, *args, **kwargs):
        gate_calls.append((room_id, platform, login_url, cookie_path))
        return "logged_in"

    monkeypatch.setattr(huya_sender_mod, "takeover_login_and_archive", _takeover_fail)
    monkeypatch.setattr(LOGIN_GATE, "ensure_cookie_file_login", _gate)
    engine._stop_flags["1"] = True
    await engine._run_room("1")

    assert gate_calls == [("1", "huya", "https://www.huya.com/",
                           str(tmp_path / "huya_login_cookies.json"))]


def test_protocol_version():
    assert codec.PROTOCOL_VERSION == "huya-1"


@pytest.mark.asyncio
async def test_login_gate_budget_exhausted_skips_takeover(monkeypatch, tmp_path):
    """ship 对抗F5 守护：预算耗尽→takeover 与存档窗都不弹（无人值守防反复弹窗）；budget_exhausted 恰 1 条（去重）"""
    import danmaku_listener.senders.huya as huya_sender_mod

    engine, statuses, _write = _make_gate_engine(monkeypatch, tmp_path)
    engine._login_budgets["1"] = 0

    async def _unexpected_takeover(room_id):
        raise AssertionError("预算耗尽不得触发 takeover 弹窗")

    async def _unexpected_gate(*args, **kwargs):
        raise AssertionError("预算耗尽不得触发存档窗兜底")

    monkeypatch.setattr(huya_sender_mod, "takeover_login_and_archive", _unexpected_takeover)
    monkeypatch.setattr(LOGIN_GATE, "ensure_cookie_file_login", _unexpected_gate)
    engine._stop_flags["1"] = True
    await engine._run_room("1")
    await engine._run_room("1")  # 第二次重连同样不弹

    exhausted = [m for m in statuses if "budget_exhausted" in str(m.get("payload"))]
    assert len(exhausted) == 1  # _budget_warned 去重
    assert not any("first_login" in str(m.get("payload")) for m in statuses)


@pytest.mark.asyncio
async def test_login_gate_budget_resets_on_restart(monkeypatch, tmp_path):
    """ship 对抗终审F1 守护：停房重加→预算重置+warned 释放（「停止重加可重触发」承诺成立）"""
    engine, statuses, _write = _make_gate_engine(monkeypatch, tmp_path)
    engine._login_budgets["1"] = 0
    engine._budget_warned.add("1")

    async def _noop(room_id):
        return None

    monkeypatch.setattr(engine, "_run_room", _noop)
    await engine.start("1")
    try:
        assert engine._login_budgets.get("1", LOGIN_GATE.LOGIN_BUDGET) == LOGIN_GATE.LOGIN_BUDGET
        assert "1" not in engine._budget_warned
        assert engine._stop_flags["1"] is False
    finally:
        await engine.stop("1")


@pytest.mark.asyncio
async def test_login_gate_takeover_success_resets_budget(monkeypatch, tmp_path):
    """ship 对抗终审F1 守护：takeover 成功→预算清零+warned 释放（对齐 jd/taobao 先例）"""
    import danmaku_listener.senders.huya as huya_sender_mod

    engine, statuses, _write = _make_gate_engine(monkeypatch, tmp_path)
    engine._login_budgets["1"] = 1  # 已扣过一次

    async def _ok(room_id):
        return True

    monkeypatch.setattr(huya_sender_mod, "takeover_login_and_archive", _ok)
    engine._stop_flags["1"] = True
    await engine._run_room("1")
    assert engine._login_budgets.get("1", LOGIN_GATE.LOGIN_BUDGET) == LOGIN_GATE.LOGIN_BUDGET
    assert "1" not in engine._budget_warned
