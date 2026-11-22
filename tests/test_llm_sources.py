"""AI 來源目錄與 kind=source（docs/adr/0046）：ntu_easy_llm 0.6 的 adapter 包成 SYNOX 的 ChatAdapter。

不連網：kind=source 一律用 ntu_easy_llm 的測試來源 local/fake（FakeAdapter，照劇本回話），或在測試裡用
register_adapter 換一個假的 factory；沒裝 ntu_easy_llm 的情況用擋 import 的方式模擬。"""

import builtins
import sys

import pytest

from synox.llm import kinds, sources
from synox.llm.base import ASSISTANT, SYSTEM, TOOL, USER, ImagePart, LLMError, Message, ToolCall, ToolSpec
from synox.llm.factory import make_adapter

pytestmark = pytest.mark.usefixtures("no_sockets")

SPEC = ToolSpec("money__add", "記一筆", {"type": "object", "properties": {"amount": {"type": "string"}}})


@pytest.fixture
def no_easy(monkeypatch):
    """模擬這台沒裝 ntu_easy_llm：import 一律失敗（已載入的模組先藏起來）。"""
    real = builtins.__import__
    for name in [m for m in sys.modules if m == "ntu_easy_llm" or m.startswith("ntu_easy_llm.")]:
        monkeypatch.delitem(sys.modules, name)

    def fake_import(name, *a, **kw):
        if name == "ntu_easy_llm" or name.startswith("ntu_easy_llm."):
            raise ImportError("no module named ntu_easy_llm")
        return real(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", fake_import)


def needs_06():
    pytest.importorskip("ntu_easy_llm.adapters", reason="要 ntu_easy_llm 0.6（adapters／catalog）")


def fake_source(script, default=None, **extra):
    opts = {"script": list(script)}
    if default is not None:
        opts["default"] = default
    return {"kind": "source", "source": "local/fake", "model": "fake-1", "source_options": opts, **extra}


# ── 形狀檢查（不用 ntu_easy_llm）──────────────────────────────────────


def test_validate_shapes():
    ok = sources.validate({"kind": "source", "source": "remote/api_key/llop", "model": "any",
                           "source_options": {"llop_profile": "default", "transport": "auto", "max_tokens": 4096}})
    assert ok["source"] == "remote/api_key/llop" and ok["options"]["transport"] == "auto"
    assert sources.validate({"source": "local/ollama", "base_url": "http://127.0.0.1:11434/"})["base_url"] == \
        "http://127.0.0.1:11434"
    for bad in ({"source": "openai"}, {"source": "remote/oops/x"}, {"source": "../etc"},
                {"source": "local/ollama", "base_url": "ftp://x"},
                {"source": "local/ollama", "base_url": "http://user:pw@host/v1"},
                {"source": "local/ollama", "source_options": {"api_key": "x"}},
                {"source": "local/ollama", "source_options": {"Bad-Name": 1}},
                {"source": "local/ollama", "source_options": {"x": ["list"]}},
                {"source": "local/ollama", "source_options": {"note": "sk-" + "a" * 30}},
                {"source": "local/ollama", "source_options": []}):
        with pytest.raises(ValueError):
            sources.validate(bad)


def test_kind_messages_are_chinese():
    assert kinds.message_for("quota_exhausted", "OpenAI").startswith("OpenAI：額度用完。")
    assert "連不到 http://x/v1" in kinds.message_for("connection", "http://x/v1")
    assert "（429）" in kinds.message_for("rate_limited", "X", status=429)
    assert "伺服器說：slow down" in kinds.message_for("rate_limited", "X", "slow   down")
    assert kinds.message_for("never-heard", "X").startswith("X：出錯了。")
    assert kinds.label_of("trust") == "加密或金鑰核對失敗"
    assert kinds.http_kind(429, '{"error":{"code":"insufficient_quota"}}') == "quota_exhausted"
    assert [kinds.http_kind(s) for s in (401, 429, 403, 504, 413, 503, 418, 500)] == \
        ["auth_invalid", "rate_limited", "permission", "timeout", "context_too_long", "overloaded", "bad_request",
         "server_error"]
    assert kinds.http_kind(404, "model 'x' not found") == "model_not_found"
    assert LLMError("x").kind == "" and LLMError("x", kind="timeout").kind == "timeout"


def test_config_accepts_source_and_rejects_bad(tmp_path):
    from synox.config import ConfigError, SynoxConfig
    base = {"owner_id": 1, "data_dir": str(tmp_path)}
    c = SynoxConfig.from_dict({**base, "llm": {"kind": "source", "source": "remote/subscription/claude"}},
                              require_token=False, root=str(tmp_path))
    assert c.llm["kind"] == "source"
    with pytest.raises(ConfigError):
        SynoxConfig.from_dict({**base, "llm": {"kind": "source", "source": "nope"}}, require_token=False,
                              root=str(tmp_path))


# ── 沒裝 ntu_easy_llm：內建的照常、目錄只有舊的四個（反灰）──────────────────


def test_without_easy_llm_builtins_still_work(no_easy, tmp_path):
    from synox.llm.easy_llm import MISSING, contract
    assert contract() is None
    assert make_adapter({"llm": {"kind": "fake"}}).kind == "fake"
    assert make_adapter({"llm": {"kind": "claude_code"}}).kind == "claude_code"
    local = make_adapter({"llm": {"kind": "local", "server": "ollama", "model": "m"}})
    assert local.kind == "local"
    with pytest.raises(LLMError) as e:
        make_adapter({"llm": fake_source(["hi"])})
    assert str(e.value) == MISSING
    # 備援寫了也一樣：沒有 router＝只用主要來源，不出錯
    a = make_adapter({"llm": {"kind": "fake", "waterfall": {"mode": "auto", "backups": [{"kind": "claude_code"}]}}})
    assert a.kind == "fake"


def test_tree_without_easy_llm(no_easy):
    t = sources.tree()
    assert t["contract"] is False and t["easy_llm"] == ""
    local, remote, none = t["families"]
    assert [s["id"] for s in local["auths"][0]["services"]] == ["synox/local"]
    assert local["auths"][0]["services"][0]["available"] is True
    keys = remote["auths"][0]["services"]
    assert [s["kind"] for s in keys] == ["openai", "anthropic", "gemini", "openai_compat"]
    assert all(not s["available"] and "還沒安裝 ntu_easy_llm" in s["reason"] for s in keys)
    assert [s["id"] for s in remote["auths"][1]["services"]] == ["synox/claude_code"]
    assert none["id"] == "none"


# ── 有 ntu_easy_llm 0.6 ──────────────────────────────────────────────


def test_tree_with_easy_llm_06():
    needs_06()
    t = sources.tree()
    assert t["contract"] is True
    local, remote, _none = t["families"]
    ids = [s["id"] for s in local["auths"][0]["services"]]
    assert ids[0] == "synox/local" and "local/ollama" in ids                # SYNOX 內建的本地永遠是第一個
    keys = {s["id"]: s for s in remote["auths"][0]["services"]}
    assert keys["remote/api_key/openai"]["kind"] == "openai" and keys["remote/api_key/openai"]["available"]
    llop = keys["remote/api_key/llop"]
    assert llop["kind"] == "source"
    assert any(f["kind"] == "llop_profile" and "終端機" in f["help"] for f in llop["fields"])
    if not llop["available"]:
        assert llop["reason"].startswith("LLOP")
    subs = remote["auths"][1]["services"]
    assert subs[0]["id"] == "synox/claude_code"
    assert all(s["note"] == sources.SUBSCRIPTION_NOTE for s in subs[1:])   # 只標，不擋


def test_clean_options_types_and_unknown_keys():
    service = {"fields": [{"name": "llop_profile", "kind": "llop_profile", "label": "設定檔"},
                          {"name": "model", "kind": "model"}],
               "detail_fields": [{"name": "max_tokens", "kind": "int", "label": "上限"},
                                 {"name": "temperature", "kind": "float"},
                                 {"name": "tools", "kind": "bool"},
                                 {"name": "transport", "kind": "choice", "choices": ["auto", "e2e", "plain"]}]}
    out = sources.clean_options(service, {"llop_profile": "home", "max_tokens": "2048", "temperature": "0.2",
                                          "tools": "true", "transport": "e2e", "evil": "x", "model": "m"})
    assert out == {"llop_profile": "home", "max_tokens": 2048, "temperature": 0.2, "tools": True, "transport": "e2e"}
    assert sources.clean_options(service, {"max_tokens": ""}) == {}
    for bad in ({"max_tokens": "lots"}, {"transport": "carrier-pigeon"}, {"llop_profile": "../x"},
                {"max_tokens": -1}):
        with pytest.raises(ValueError):
            sources.clean_options(service, bad)


def test_source_adapter_chat_tools_stop_images():
    needs_06()
    a = make_adapter({"llm": fake_source([{"text": "", "tool_calls": [{"id": "c9", "name": "money__add",
                                                                        "arguments": {"amount": "80"}}]},
                                          "好"])})
    assert a.kind == "source" and a.supports_tools and a.supports_stop and a.weak     # local/* ＝本地來源
    reply = a.chat([Message(SYSTEM, "sys"), Message(USER, "記 80")], [SPEC], stop=["</x>"])
    assert reply.tool_calls[0].name == "money__add" and reply.tool_calls[0].args == {"amount": "80"}
    call = a.inner.calls[0]
    assert call["stop"] == ("</x>",) and call["tools"][0].name == "money__add"
    msgs = [Message(USER, "看這張", images=[ImagePart("image/png", b"\x89PNG")]),
            Message(ASSISTANT, "", tool_calls=[ToolCall("money__add", {"amount": "1"}, "c0")]),
            Message(TOOL, "ok", tool_call_id="c0", name="money__add")]
    assert a.chat(msgs).text == "好"
    sent = a.inner.calls[1]["messages"]
    assert sent[0].images[0].mime == "image/png" and sent[0].images[0].data == b"\x89PNG"
    assert sent[1].tool_calls[0].id == "c0" and sent[2].tool_call_id == "c0"


def test_source_adapter_errors_by_kind():
    needs_06()
    a = make_adapter({"llm": fake_source([{"error": "quota_exhausted"}, {"error": "connection"},
                                          {"error": "trust"}])})
    with pytest.raises(LLMError) as e:
        a.chat([Message(USER, "hi")])
    assert e.value.kind == "quota_exhausted" and "額度用完" in str(e.value)
    with pytest.raises(LLMError) as e:
        a.chat([Message(USER, "hi")])
    assert e.value.kind == "connection" and "連不到" in str(e.value)
    with pytest.raises(LLMError) as e:
        a.chat([Message(USER, "hi")])
    assert e.value.kind == "trust" and "不會自動換來源" in str(e.value)


def test_source_adapter_probe_and_models():
    needs_06()
    from ntu_easy_llm.adapters import Capabilities, ModelInfo, register_adapter, unregister_adapter
    from ntu_easy_llm.adapters.fake import FakeAdapter

    def factory(profile, *, http=None, resolve_secret=None):
        return FakeAdapter(["好"], profile=profile, capabilities=Capabilities(tools=None, vision=None, stop=False),
                           models=[ModelInfo("b-chat"), ModelInfo("emb", kind="embedding"),
                                   ModelInfo("a-loaded", loaded=True, context=8192)])
    register_adapter("remote/api_key/example_test", factory, replace=True)
    try:
        a = make_adapter({"llm": {"kind": "source", "source": "remote/api_key/example_test", "model": "b-chat"}})
        assert a.supports_tools is True and a.supports_stop is False and a.supports_vision is False
        assert a.weak is False and a.timeout == 90.0
        assert [m["id"] for m in a.list_models()] == ["a-loaded", "b-chat"]     # 已載入的排前面、embedding 不列
        assert a.probe() is None
        on = make_adapter({"llm": {"kind": "source", "source": "remote/api_key/example_test", "model": "m",
                                   "vision": "on"}})
        assert on.supports_vision is True                                       # 不知道（None）＋使用者說 on
    finally:
        unregister_adapter("remote/api_key/example_test")


def test_source_unavailable_says_why():
    needs_06()
    with pytest.raises(LLMError) as e:
        make_adapter({"llm": {"kind": "source", "source": "remote/subscription/no_such_cli", "model": ""}})
    assert "adapter" in str(e.value)


def test_secret_is_given_through_resolver_not_profile(tmp_path):
    needs_06()
    from ntu_easy_llm.adapters import register_adapter, unregister_adapter
    from ntu_easy_llm.adapters.fake import FakeAdapter
    from synox.vault import Vault
    seen = {}

    def factory(profile, *, http=None, resolve_secret=None):
        seen["ref"] = str(profile.secret)
        seen["key"] = resolve_secret(profile.secret)
        seen["dict"] = profile.to_dict()
        return FakeAdapter(default="好", profile=profile)
    register_adapter("remote/api_key/example_test", factory, replace=True)
    try:
        v = Vault(b"x" * 32, str(tmp_path))
        v.set_secret("llm_api_key", "k-123")
        make_adapter({"llm": {"kind": "source", "source": "remote/api_key/example_test", "model": "m",
                              "api_key": "vault:llm_api_key"}}, v)
        assert seen["key"] == "k-123" and seen["ref"] == "synox:llm_api_key"
        assert "k-123" not in repr(seen["dict"])                                # profile 裡只有引用
    finally:
        unregister_adapter("remote/api_key/example_test")


def test_legacy_kind_prefers_new_adapter_when_present():
    """舊的 kind=openai：這台的 ntu_easy_llm 有 remote/api_key/openai 的 adapter 就走它（新路），停止詞照 capabilities。"""
    needs_06()
    from ntu_easy_llm.adapters import register_adapter, unregister_adapter
    from ntu_easy_llm.adapters.fake import FakeAdapter
    seen = {}

    def factory(profile, *, http=None, resolve_secret=None):
        seen["http"], seen["key"], seen["model"] = http, resolve_secret(profile.secret), profile.model
        return FakeAdapter(default="新路", profile=profile)
    register_adapter("remote/api_key/openai", factory, replace=True)
    try:
        marker = object()
        a = make_adapter({"llm": {"kind": "openai", "api_key": "k", "model": "gpt-x"}}, session=marker)
        assert a.kind == "openai" and a.supports_stop is True
        assert a.chat([Message(USER, "hi")], stop=["x"]).text == "新路"
        assert seen == {"http": marker, "key": "k", "model": "gpt-x"}
    finally:
        unregister_adapter("remote/api_key/openai")


def test_legacy_kind_errors_use_kind():
    """舊的 kind（新路有 adapter 就走新路，沒有就走 agent.chat）＋0.6 的錯誤帶 kind：照種類說人話；狀態碼留著。"""
    needs_06()
    from synox.llm.easy_llm import EasyLLMAdapter

    class Resp:
        def __init__(self, data, status):
            import json
            self._data, self.status_code, self.text, self.headers = data, status, json.dumps(data), {}

        def json(self):
            return self._data

    class Session:
        def __init__(self, resp):
            self.resp = resp

        def post(self, url, json=None, headers=None, timeout=None):
            return self.resp
    a = EasyLLMAdapter("openai_compat", "k", "m", base_url="https://gw.example.com/v1",
                       session=Session(Resp({"error": {"code": "insufficient_quota"}}, 429)))
    with pytest.raises(LLMError) as e:
        a.chat([Message(USER, "hi")])
    assert e.value.kind == "quota_exhausted" and "額度用完（429）" in str(e.value)
    assert "gw.example.com" in str(e.value)


def test_subscription_reason_is_chinese_only():
    assert sources.unavailable_text("remote/subscription/x", "要先安裝 x 套件 / install the x package first") \
        .endswith("要先安裝 x 套件。")
