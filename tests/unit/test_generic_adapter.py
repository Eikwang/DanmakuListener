"""通用平台适配器测试

验证 GenericAdapter 的核心功能：JS 脚本执行、DOM 数据解析、自定义脚本加载。
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from danmaku_listener.adapters.generic import GenericAdapter
from danmaku_listener.bus.message import DanmakuMessage


class TestGenericAdapter:
    """通用平台适配器测试"""

    @pytest.fixture
    def adapter(self):
        """创建通用适配器实例"""
        return GenericAdapter()

    def test_platform_property(self, adapter):
        """测试平台标识为 generic"""
        assert adapter.platform == "generic"

    def test_can_parse_dict_with_type_field(self, adapter):
        """测试能解析包含 type 字段的字典数据"""
        data = {"type": "dom_mutation", "content": "hello", "element": "DIV"}
        assert adapter.can_parse(data) is True

    def test_can_parse_dict_with_content_field(self, adapter):
        """测试能解析包含 content 字段的字典数据"""
        data = {"content": "hello world"}
        assert adapter.can_parse(data) is True

    def test_can_parse_rejects_non_dict(self, adapter):
        """测试拒绝非字典类型数据"""
        assert adapter.can_parse("string data") is False
        assert adapter.can_parse(123) is False
        assert adapter.can_parse(None) is False
        assert adapter.can_parse([]) is False

    def test_can_parse_rejects_empty_dict(self, adapter):
        """测试拒绝空字典"""
        assert adapter.can_parse({}) is False

    def test_can_parse_rejects_dict_without_content(self, adapter):
        """测试拒绝没有 content 也没有 type 的字典"""
        data = {"user": "test", "count": 5}
        assert adapter.can_parse(data) is False

    @pytest.mark.asyncio
    async def test_parse_dom_mutation_data(self, adapter):
        """测试解析 DOM 变异数据"""
        raw_data = {
            "type": "dom_mutation",
            "content": "这是一条弹幕",
            "element": "DIV",
        }
        context = {"platform": "bilibili", "room_id": "789012"}

        message = await adapter.parse(raw_data, context)

        assert message is not None
        assert isinstance(message, DanmakuMessage)
        assert message.content == "这是一条弹幕"
        assert message.platform == "bilibili"
        assert message.room_id == "789012"
        assert message.message_type == "normal"

    @pytest.mark.asyncio
    async def test_parse_with_default_platform(self, adapter):
        """测试无 context 时使用默认平台标识"""
        raw_data = {
            "type": "dom_mutation",
            "content": "hello",
            "element": "SPAN",
        }

        message = await adapter.parse(raw_data)

        assert message is not None
        assert message.platform == "generic"
        assert message.room_id == ""

    @pytest.mark.asyncio
    async def test_parse_extracts_user_name_from_data(self, adapter):
        """测试从数据中提取用户名"""
        raw_data = {
            "type": "dom_mutation",
            "content": "hello",
            "element": "DIV",
            "user": "test_user",
        }
        context = {"platform": "bilibili", "room_id": "123"}

        message = await adapter.parse(raw_data, context)

        assert message is not None
        assert message.user_name == "test_user"

    @pytest.mark.asyncio
    async def test_parse_default_user_name(self, adapter):
        """测试无用户名时使用默认值"""
        raw_data = {
            "type": "dom_mutation",
            "content": "hello",
            "element": "DIV",
        }
        context = {"platform": "bilibili", "room_id": "123"}

        message = await adapter.parse(raw_data, context)

        assert message is not None
        assert message.user_name == "anonymous"

    @pytest.mark.asyncio
    async def test_parse_json_string_data(self, adapter):
        """测试解析 JSON 字符串格式的数据（JS 回调传回的格式）"""
        json_str = json.dumps({
            "type": "dom_mutation",
            "content": "弹幕内容",
            "element": "DIV",
        })
        context = {"platform": "bilibili", "room_id": "456"}

        message = await adapter.parse(json_str, context)

        assert message is not None
        assert message.content == "弹幕内容"

    @pytest.mark.asyncio
    async def test_parse_invalid_json_string_returns_none(self, adapter):
        """测试无效 JSON 字符串返回 None"""
        result = await adapter.parse("not valid json", {"platform": "bilibili"})
        assert result is None

    @pytest.mark.asyncio
    async def test_parse_returns_none_for_unparseable_data(self, adapter):
        """测试无法解析的数据返回 None"""
        result = await adapter.parse(12345, {"platform": "bilibili"})
        assert result is None

    @pytest.mark.asyncio
    async def test_parse_returns_none_for_empty_content(self, adapter):
        """测试空内容返回 None"""
        raw_data = {
            "type": "dom_mutation",
            "content": "",
            "element": "DIV",
        }
        result = await adapter.parse(raw_data, {"platform": "bilibili"})
        assert result is None

    @pytest.mark.asyncio
    async def test_parse_returns_none_for_whitespace_content(self, adapter):
        """测试纯空白内容返回 None"""
        raw_data = {
            "type": "dom_mutation",
            "content": "   \t\n  ",
            "element": "DIV",
        }
        result = await adapter.parse(raw_data, {"platform": "bilibili"})
        assert result is None

    @pytest.mark.asyncio
    async def test_parse_gift_type_message(self, adapter):
        """测试解析礼物类型消息"""
        raw_data = {
            "type": "gift",
            "content": "送出火箭",
            "element": "DIV",
            "user": "土豪哥",
            "gift_name": "火箭",
            "gift_count": 1,
            "gift_value": 1000,
        }
        context = {"platform": "bilibili", "room_id": "789"}

        message = await adapter.parse(raw_data, context)

        assert message is not None
        assert message.message_type == "gift"
        assert message.gift_info is not None
        assert message.gift_info.gift_name == "火箭"
        assert message.gift_info.gift_count == 1
        assert message.gift_info.gift_value == 1000

    @pytest.mark.asyncio
    async def test_parse_system_type_message(self, adapter):
        """测试解析系统类型消息"""
        raw_data = {
            "type": "system",
            "content": "欢迎进入直播间",
            "element": "DIV",
        }
        context = {"platform": "bilibili", "room_id": "789"}

        message = await adapter.parse(raw_data, context)

        assert message is not None
        assert message.message_type == "system"

    @pytest.mark.asyncio
    async def test_parse_exception_returns_none(self, adapter):
        """测试解析异常时返回 None"""
        # 传入一个会导致异常的数据
        raw_data = {"type": "dom_mutation", "content": None}
        # content 为 None 会在 strip() 时抛出 AttributeError
        result = await adapter.parse(raw_data, {"platform": "bilibili"})
        assert result is None


class TestGenericAdapterScriptManagement:
    """通用适配器脚本管理测试"""

    @pytest.fixture
    def adapter(self):
        """创建通用适配器实例"""
        return GenericAdapter()

    def test_default_script_is_not_empty(self, adapter):
        """测试默认脚本不为空"""
        script = adapter.get_script()
        assert isinstance(script, str)
        assert len(script) > 0

    def test_default_script_contains_mutation_observer(self, adapter):
        """测试默认脚本包含 MutationObserver"""
        script = adapter.get_script()
        assert "MutationObserver" in script

    def test_default_script_calls_on_danmaku(self, adapter):
        """测试默认脚本调用 onDanmaku 回调"""
        script = adapter.get_script()
        assert "onDanmaku" in script

    def test_register_custom_script(self, adapter):
        """测试注册自定义脚本"""
        custom_script = "console.log('custom');"
        adapter.register_script("bilibili", custom_script)

        script = adapter.get_script("bilibili")
        assert script == custom_script

    def test_register_custom_script_for_platform(self, adapter):
        """测试不同平台注册不同脚本"""
        adapter.register_script("bilibili", "// bilibili script")
        adapter.register_script("douyu", "// douyu script")

        assert adapter.get_script("bilibili") == "// bilibili script"
        assert adapter.get_script("douyu") == "// douyu script"

    def test_get_script_returns_default_for_unknown_platform(self, adapter):
        """测试未知平台返回默认脚本"""
        script = adapter.get_script("unknown_platform")
        default = adapter.get_script()
        assert script == default

    def test_register_custom_parser(self, adapter):
        """测试注册自定义解析器"""
        async def custom_parser(data, context):
            return DanmakuMessage(
                platform="custom",
                room_id="123",
                user_name="test",
                content=data.get("text", ""),
                timestamp=0,
                message_type="normal",
            )

        adapter.register_parser("custom_type", custom_parser)
        assert "custom_type" in adapter._custom_parsers

    @pytest.mark.asyncio
    async def test_custom_parser_used_for_matching_type(self, adapter):
        """测试自定义解析器被正确调用"""
        async def custom_parser(data, context):
            return DanmakuMessage(
                platform=context.get("platform", "generic") if context else "generic",
                room_id=context.get("room_id", "") if context else "",
                user_name="custom_user",
                content=data.get("text", ""),
                timestamp=0,
                message_type="normal",
            )

        adapter.register_parser("custom_type", custom_parser)

        raw_data = {
            "type": "custom_type",
            "text": "custom message",
        }
        context = {"platform": "bilibili", "room_id": "123"}

        message = await adapter.parse(raw_data, context)
        assert message is not None
        assert message.user_name == "custom_user"
        assert message.content == "custom message"

    @pytest.mark.asyncio
    async def test_custom_parser_returns_none_falls_back(self, adapter):
        """测试自定义解析器返回 None 时回退到默认解析"""
        async def custom_parser(data, context):
            return None  # 解析失败

        adapter.register_parser("custom_type", custom_parser)

        raw_data = {
            "type": "custom_type",
            "content": "fallback content",
            "element": "DIV",
        }
        context = {"platform": "bilibili", "room_id": "123"}

        message = await adapter.parse(raw_data, context)
        # 自定义解析器返回 None，回退到默认解析
        assert message is not None
        assert message.content == "fallback content"


class TestGenericAdapterWithBrowserEngine:
    """通用适配器与 BrowserEngine 集成测试"""

    @pytest.mark.asyncio
    async def test_inject_script_to_browser_engine(self):
        """测试将适配器脚本注入到 BrowserEngine"""
        from danmaku_listener.engines.browser_engine import BrowserEngine

        adapter = GenericAdapter()
        engine = BrowserEngine()

        with patch.object(engine, '_inject_script', new_callable=AsyncMock) as mock_inject:
            await adapter.inject_to_engine(engine, "room1", "bilibili")
            mock_inject.assert_called_once()
            # 验证注入的是 bilibili 平台脚本
            call_args = mock_inject.call_args
            assert call_args[0][0] == "room1"
            assert isinstance(call_args[0][1], str)

    @pytest.mark.asyncio
    async def test_expose_callback_to_browser_engine(self):
        """测试将适配器回调暴露到 BrowserEngine"""
        from danmaku_listener.engines.browser_engine import BrowserEngine

        adapter = GenericAdapter()
        engine = BrowserEngine()

        with patch.object(engine, '_expose_callback', new_callable=AsyncMock) as mock_expose:
            await adapter.expose_callback_to_engine(engine, "room1")
            mock_expose.assert_called_once()
            # 验证暴露的回调名
            call_args = mock_expose.call_args
            assert call_args[0][0] == "room1"
            assert call_args[0][1] == "onDanmaku"

    @pytest.mark.asyncio
    async def test_callback_receives_json_and_routes_to_parse(self):
        """测试回调接收 JSON 数据并路由到 parse 方法"""
        adapter = GenericAdapter()
        received_messages = []

        async def on_message(msg):
            received_messages.append(msg)

        # 模拟 BrowserEngine 的消息回调链
        async def js_callback(json_str: str):
            """模拟 JS 端调用 onDanmaku 传回的 JSON 字符串"""
            data = json.loads(json_str)
            message = await adapter.parse(data, {"platform": "bilibili", "room_id": "123"})
            if message:
                await on_message(message)

        # 模拟 JS 传回弹幕数据
        await js_callback(json.dumps({
            "type": "dom_mutation",
            "content": "测试弹幕",
            "element": "DIV",
        }))

        assert len(received_messages) == 1
        assert received_messages[0].content == "测试弹幕"
        assert received_messages[0].platform == "bilibili"
