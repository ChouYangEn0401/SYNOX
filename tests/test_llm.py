"""adapter：requests 換成假的 session（不連網；經 ntu_easy_llm.agent 的 session=），claude 換成假的 runner／which（不開子程序）。"""

import json
import subprocess

import pytest

from synox.llm.base import ASSISTANT, SYSTEM, TOOL, USER, LLMError, Message, ToolCall, ToolSpec
from synox.llm.claude_code import NOT_FOUND, ClaudeCodeAdapter, flatten
from synox.llm.factory import make_adapter, resolve_secret
from synox.llm.easy_llm import MISSING, EasyLLMAdapter


def OpenAICompatAdapter(base_url, api_key="", model="", *, tools=True, session=None):
    return EasyLLMAdapter("openai_compat", api_key, model, base_url=base_url, tools=tools, session=session)


def AnthropicAdapter(api_key, model, *, session=None):
    return EasyLLMAdapter("anthropic", api_key, model, session=session)

SPEC = ToolSpec("money__add", "記一筆", {"type": "object", "properties": {"amount": {"type": "string"}}})


class Resp:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.text = data, status, json.dumps(data)

    def json(self):
        return self._data


class Session:
    def __init__(self, resp):
        self.resp = resp
        self.sent = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.sent.append((url, json, headers))
        return self.resp


def test_openai_tool_call_round_trip():
    s = Session(Resp({"choices": [{"message": {"content": None, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "money__add", "arguments": "{\"amount\": \"80\"}"}}]}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3}}))
    a = OpenAICompatAdapter("https://gw.example.com/v1/", "k", "m", session=s)
    msgs = [Message(SYSTEM, "sys"), Message(USER, "記 80"),
            Message(ASSISTANT, "", tool_calls=[ToolCall("money__add", {"amount": "1"}, "c0")]),
            Message(TOOL, "ok", tool_call_id="c0", name="money__add")]
    reply = a.chat(msgs, [SPEC])
    assert reply.tool_calls[0].name == "money__add" and reply.tool_calls[0].args == {"amount": "80"}
    assert reply.usage == {"input": 12, "output": 3}
    url, body, headers = s.sent[0]
    assert url == "https://gw.example.com/v1/chat/completions" and headers["Authorization"] == "Bearer k"
    assert body["tools"][0]["function"]["name"] == "money__add"
    assert body["messages"][2]["tool_calls"][0]["function"]["arguments"] == '{"amount": "1"}'
    assert body["messages"][3] == {"role": "tool", "tool_call_id": "c0", "content": "ok"}


def test_openai_no_tools_flag_and_errors():
    s = Session(Resp({"choices": [{"message": {"content": "好"}}]}))
    a = OpenAICompatAdapter("http://localhost:11434/v1", "", "llama", tools=False, session=s)
    assert a.chat([Message(USER, "hi")], [SPEC]).text == "好"
    assert "tools" not in s.sent[0][1] and "Authorization" not in s.sent[0][2]
    assert a.probe() is None
    bad = OpenAICompatAdapter("https://x/v1", "k", "m", session=Session(Resp({"error": "no"}, 401)))
    assert "金鑰不對" in bad.probe()
    assert "模型" in OpenAICompatAdapter("https://x/v1", "k", "", session=s).probe()


def test_anthropic_wire_and_parse():
    s = Session(Resp({"content": [{"type": "text", "text": "我來記"},
                                  {"type": "tool_use", "id": "t1", "name": "money__add", "input": {"amount": "8"}}],
                      "usage": {"input_tokens": 20, "output_tokens": 4}}))
    a = AnthropicAdapter("k", "some-model", session=s)
    msgs = [Message(SYSTEM, "sys"), Message(USER, "hi"),
            Message(ASSISTANT, "", tool_calls=[ToolCall("a", {}, "x1"), ToolCall("b", {}, "x2")]),
            Message(TOOL, "r1", tool_call_id="x1"), Message(TOOL, "r2", tool_call_id="x2")]
    reply = a.chat(msgs, [SPEC])
    assert reply.text == "我來記" and reply.tool_calls[0].args == {"amount": "8"} and reply.usage["input"] == 20
    url, body, headers = s.sent[0]
    assert url == "https://api.anthropic.com/v1/messages" and headers["x-api-key"] == "k" and body["system"] == "sys"
    assert body["tools"][0]["input_schema"]["properties"] == {"amount": {"type": "string"}}
    assert [b["tool_use_id"] for b in body["messages"][2]["content"]] == ["x1", "x2"]   # 兩個結果併成一則 user
    with pytest.raises(LLMError):
        AnthropicAdapter("", "m", session=s).chat([Message(USER, "hi")])


def test_claude_code_not_found():
    a = ClaudeCodeAdapter(which=lambda: None)
    assert a.probe() == NOT_FOUND
    with pytest.raises(LLMError):
        a.chat([Message(USER, "hi")])


def test_claude_code_runs_without_tools(tmp_path):
    seen = {}

    def runner(argv, **kw):
        seen["argv"], seen["input"], seen["cwd"] = argv, kw["input"], kw["cwd"]
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(
            {"type": "result", "result": "好", "is_error": False, "usage": {"input_tokens": 5, "output_tokens": 1}}),
            stderr="")

    a = ClaudeCodeAdapter("m1", workdir=str(tmp_path / "ws"), runner=runner, which=lambda: "claude.exe")
    reply = a.chat([Message(SYSTEM, "s"), Message(USER, "嗨")])
    assert reply.text == "好" and reply.usage == {"input": 5, "output": 1}
    assert seen["argv"][:4] == ["claude.exe", "-p", "--output-format", "json"]
    assert ["--tools", ""] == seen["argv"][4:6] and "--strict-mcp-config" in seen["argv"]
    assert seen["argv"][-2:] == ["--model", "m1"] and "［使用者］\n嗨" in seen["input"]
    assert a.supports_tools is False


def test_claude_code_error():
    def runner(argv, **kw):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="not logged in")
    with pytest.raises(LLMError) as e:
        ClaudeCodeAdapter(runner=runner, which=lambda: "claude").chat([Message(USER, "hi")])
    assert "not logged in" in str(e.value)


def test_flatten_order():
    text = flatten([Message(SYSTEM, "a"), Message(USER, "b"), Message(ASSISTANT, "c")])
    assert text.index("a") < text.index("b") < text.index("c") and text.endswith("［助理］")


def test_factory_kinds_and_secrets(tmp_path):
    from synox.vault import Vault
    assert make_adapter({"llm": {"kind": "none"}}) is None
    assert make_adapter({"llm": {"kind": "fake"}}).kind == "fake"
    v = Vault(b"x" * 32, str(tmp_path))
    v.set_secret("llm_api_key", "sk-1")
    a = make_adapter({"llm": {"kind": "openai_compat", "base_url": "https://x/v1", "api_key": "vault:llm_api_key",
                              "model": "m"}}, v)
    assert a.api_key == "sk-1"
    with pytest.raises(LLMError):
        resolve_secret("vault:missing", v)
    assert make_adapter({"llm": {"kind": "anthropic", "api_key": "k", "model": "m"}}).kind == "anthropic"


def test_openai_and_gemini_kinds_use_their_endpoints():
    s = Session(Resp({"choices": [{"message": {"content": "好"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}))
    a = make_adapter({"llm": {"kind": "openai", "api_key": "k", "model": "gpt-x"}}, session=s)
    assert a.chat([Message(USER, "hi")]).text == "好" and a.name.startswith("OpenAI")
    assert s.sent[-1][0] == "https://api.openai.com/v1/chat/completions"
    g = make_adapter({"llm": {"kind": "gemini", "api_key": "k", "model": "gemini-x"}}, session=s)
    g.chat([Message(USER, "hi")])
    assert s.sent[-1][0].startswith("https://generativelanguage.googleapis.com/") and g.supports_tools
    with pytest.raises(LLMError) as e:
        make_adapter({"llm": {"kind": "openai", "api_key": "", "model": "m"}}, session=s).chat([Message(USER, "x")])
    assert "API key" in str(e.value)


def test_errors_are_chinese():
    from ntu_easy_llm.agent import LLMConnectionError
    class Down:
        def post(self, *a, **kw):
            raise OSError("refused")
    a = OpenAICompatAdapter("http://localhost:11434/v1", "", "llama", session=Down())
    assert "連不到 http://localhost:11434/v1" in a.probe()
    assert "格式看不懂" in OpenAICompatAdapter("https://x/v1", "k", "m", session=Session(Resp({"x": 1}))).probe()
    assert "429" in OpenAICompatAdapter("https://x/v1", "k", "m", session=Session(Resp({}, 429))).probe()
    with pytest.raises(LLMError):
        EasyLLMAdapter("openai_compat", "k", "m", base_url="")
    assert LLMConnectionError


def test_missing_ntu_easy_llm_says_how_to_install(monkeypatch):
    import builtins
    real = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "ntu_easy_llm" or name.startswith("ntu_easy_llm."):
            raise ImportError("no module")
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    a = EasyLLMAdapter("openai", "k", "m", session=Session(Resp({})))
    assert a.probe() == MISSING and MISSING.startswith("還沒安裝 ntu_easy_llm：")
    with pytest.raises(LLMError) as e:
        a.chat([Message(USER, "hi")])
    assert "還沒安裝 ntu_easy_llm" in str(e.value)


def test_find_claude_falls_back_to_native_install_dir(tmp_path, monkeypatch):
    """PATH 上沒有 claude，但官方安裝程式的位置（~/.local/bin）有：要找得到。"""
    from synox.llm import claude_code
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: None)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert claude_code.find_claude() is None
    exe = tmp_path / ".local" / "bin" / "claude.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert claude_code.find_claude() == str(exe)


def test_find_claude_falls_back_to_npm_global_dir(tmp_path, monkeypatch):
    """用 npm 裝的 claude（%APPDATA%\\npm\\claude.cmd）：PATH 還是舊的時候也要找得到。"""
    from synox.llm import claude_code
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: None)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert claude_code.find_claude() is None
    cmd = tmp_path / "Roaming" / "npm" / "claude.cmd"
    cmd.parent.mkdir(parents=True)
    cmd.write_bytes(b"")
    assert claude_code.find_claude() == str(cmd)


def test_claude_code_passes_through_the_cost_it_reports():
    def runner(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(
            {"type": "result", "result": "好", "is_error": False, "total_cost_usd": 0.0123,
             "usage": {"input_tokens": 5, "output_tokens": 1}}), stderr="")
    reply = ClaudeCodeAdapter(runner=runner, which=lambda: "claude").chat([Message(USER, "hi")])
    assert reply.usage == {"input": 5, "output": 1, "usd": 0.0123}
