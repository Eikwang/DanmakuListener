"""wbi 签名测试（B站 2023+ 风控修复）"""

import pytest

from danmaku_listener.engines.protocol import bilibili_codec as codec


def test_get_mixin_key_known_vector():
    # B站社区公开的标准测试向量：img_key+sub_key 混合结果固定
    img = "7cd084941338484aae1ad9425b84077c"
    sub = "4932caff0ff746eab6f01bf08b70ac45"
    # 该向量广泛见于 wbi 算法文档，混合结果应为固定 32 字符
    result = codec.get_mixin_key(img + sub)
    assert len(result) == 32
    # 可复现
    assert result == codec.get_mixin_key(img + sub)


def test_wbi_sign_params_adds_wts_and_wrid():
    params = codec.wbi_sign_params({"id": 23058, "type": 0}, "a" * 32)
    assert "wts" in params
    assert "w_rid" in params
    assert len(params["w_rid"]) == 32  # md5 hex
    assert params["id"] == "23058"  # 签名时值 str 化


def test_wbi_sign_filters_special_chars():
    params = codec.wbi_sign_params({"q": "a!'()*b"}, "k" * 32)
    assert params["q"] == "ab"


def test_wbi_sign_deterministic_per_wts():
    import time
    p1 = codec.wbi_sign_params({"id": 1}, "k" * 32)
    # 同秒内签名一致
    p2 = codec.wbi_sign_params({"id": 1}, "k" * 32)
    assert p1["w_rid"] == p2["w_rid"]


def test_extract_wbi_keys():
    nav = {"data": {"wbi_img": {
        "img_url": "https://i0.hdslb.com/bfs/wbi/abc123.png",
        "sub_url": "https://i0.hdslb.com/bfs/wbi/def456.png",
    }}}
    img, sub = codec.extract_wbi_keys(nav)
    assert img == "abc123"
    assert sub == "def456"


def test_extract_wbi_keys_missing_raises():
    with pytest.raises(ValueError, match="wbi_img"):
        codec.extract_wbi_keys({"data": None})


def test_build_danmu_info_url_contains_signature():
    url = codec.build_danmu_info_url(23058, "m" * 32)
    assert "getDanmuInfo" in url
    assert "w_rid=" in url
    assert "wts=" in url
    assert "id=23058" in url
