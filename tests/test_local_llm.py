"""本地模型（docs/adr/0007）：假的 urllib opener（不 listen 任何 port、不連網、不載入模型）。"""

import json
import logging
import socket
import urllib.error
from urllib.parse import urlsplit

import pytest

from synox.config import SynoxConfig
from synox.llm import local, local_advice
from synox.llm.base import ASSISTANT, SYSTEM, TOOL, USER, LLMError, Message, Reply, ToolCall, ToolSpec
from synox.llm.factory import easy_timeout, make_adapter
from synox.llm.local import LocalAdapter
from synox.wizard import logic

SPEC = ToolSpec("money__add", "記一筆", {"type": "object", "properties": {"amount": {"type": "string"}}})
CHAT_PATHS = ("/api/chat", "/api/generate", "/v1/chat/completions", "/v1/completions")


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakeResp:
    """一行一行吐；step＝每讀一行時鐘前進幾秒（模擬慢慢吐字）；stall_after＝讀到第幾行之後 socket 逾時。"""

    def __init__(self, lines=(), *, status=200, clock=None, step=0.0, stall_after=None, body=None):
        self.lines = [x if isinstance(x, bytes) else (x + "\n").encode("utf-8") for x in lines]
        self.status, self.clock, self.step, self.stall_after = status, clock, step, stall_after
        self.body = body
        self.read_count = 0
        self.closed = False

    def readline(self):
        if self.stall_after is not None and self.read_count >= self.stall_after:
            raise socket.timeout("timed out")
        self.read_count += 1
        if self.clock is not None:
            self.clock.t += self.step
        return self.lines.pop(0) if self.lines else b""

    def read(self):
        if self.body is not None:
            return json.dumps(self.body).encode("utf-8")
        return b"".join(self.lines)

    def close(self):
        self.closed = True


class FakeOpener:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, request, timeout):
        path = urlsplit(request.full_url).path
        body = json.loads(request.data.decode("utf-8")) if request.data else None
        self.calls.append({"method": request.get_method(), "path": path, "body": body, "timeout": timeout,
                           "url": request.full_url})
        route = self.routes.get((request.get_method(), path))
        if route is None:
            raise urllib.error.HTTPError(request.full_url, 404, "not found", {}, None)
        if callable(route) and not isinstance(route, FakeResp):
            route = route()
        if isinstance(route, BaseException):
            raise route
        return route

    def paths(self):
        return [c["path"] for c in self.calls]


def ndjson(*objs):
    return [json.dumps(o, ensure_ascii=False) for o in objs]


def ollama(routes, **kw):
    opener = FakeOpener(routes)
    kw.setdefault("model", "qwen3.5:9b")
    return LocalAdapter(kw.pop("model"), opener=opener, **kw), opener


TAGS = {"models": [{"name": "qwen3.5:9b", "size": 6_594_474_711,
                    "details": {"parameter_size": "9.7B", "quantization_level": "Q4_K_M", "context_length": 262144}},
                   {"name": "tiny:latest", "size": 1_000_000_000, "details": {}}]}
SHOW = {"capabilities": ["completion", "vision", "tools", "thinking"],
        "model_info": {"general.architecture": "qwen35", "qwen35.block_count": 32, "qwen35.context_length": 262144,
                       "qwen35.attention.head_count": 16, "qwen35.attention.head_count_kv": [0, 0, 0, 4] * 8,
                       "qwen35.attention.key_length": 256, "qwen35.attention.value_length": 256,
                       "qwen35.embedding_length": 4096}}


def json_resp(data):
    return lambda: FakeResp(body=data)


# ── Ollama 串流 ──────────────────────────────────────────────────────

def test_ollama_streams_ndjson_with_num_ctx_think_off_and_native_tools():
    stream = FakeResp(ndjson({"message": {"role": "assistant", "content": "好"}, "done": False},
                             {"message": {"role": "assistant", "content": "的"}, "done": False},
                             {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop",
                              "prompt_eval_count": 120, "eval_count": 7}))
    a, opener = ollama({("POST", "/api/chat"): stream}, context_size=8192, max_tokens=300)
    msgs = [Message(SYSTEM, "sys"), Message(USER, "記 80"),
            Message(ASSISTANT, "", tool_calls=[ToolCall("money__add", {"amount": "1"}, "c0")]),
            Message(TOOL, "ok", tool_call_id="c0", name="money__add")]
    reply = a.chat(msgs, [SPEC])
    assert reply.text == "好的" and reply.usage == {"input": 120, "output": 7} and reply.warnings == []
    call = opener.calls[0]
    assert call["url"] == "http://127.0.0.1:11434/api/chat" and call["timeout"] == 450.0
    body = call["body"]
    assert body["stream"] is True and body["think"] is False
    assert body["options"] == {"num_ctx": 8192, "num_predict": 300}
    assert body["tools"][0]["function"]["name"] == "money__add"
    assert body["messages"][2]["tool_calls"][0]["function"]["arguments"] == {"amount": "1"}     # Ollama 收物件
    assert body["messages"][3] == {"role": "tool", "content": "ok", "tool_name": "money__add"}
    assert stream.closed


def test_ollama_tool_calls_and_no_num_ctx_when_zero():
    stream = FakeResp(ndjson({"message": {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "money__add", "arguments": {"amount": "80"}}}]}, "done": False},
        {"done": True, "prompt_eval_count": 50, "eval_count": 9}))
    a, opener = ollama({("POST", "/api/chat"): stream, ("GET", "/api/ps"): json_resp({"models": []})})
    reply = a.chat([Message(USER, "記 80")], [SPEC])
    assert reply.tool_calls[0].name == "money__add" and reply.tool_calls[0].args == {"amount": "80"}
    assert reply.tool_calls[0].id
    assert "num_ctx" not in opener.calls[0]["body"]["options"]


def test_tools_false_sends_no_tools():
    stream = FakeResp(ndjson({"message": {"content": "{\"tool\": \"x\"}"}, "done": True}))
    a, opener = ollama({("POST", "/api/chat"): stream}, tools=False, context_size=8192)
    a.chat([Message(USER, "hi")], [SPEC])
    assert "tools" not in opener.calls[0]["body"] and a.supports_tools is False


def test_think_is_dropped_once_when_the_server_rejects_it():
    calls = {"n": 0}

    def chat():
        calls["n"] += 1
        if calls["n"] == 1:
            return urllib.error.HTTPError("u", 400, "bad", {}, _Body(b'{"error":"unknown field think"}'))
        return FakeResp(ndjson({"message": {"content": "ok"}, "done": True}))
    a, opener = ollama({("POST", "/api/chat"): chat}, context_size=8192)
    assert a.chat([Message(USER, "hi")]).text == "ok"
    assert "think" in opener.calls[0]["body"] and "think" not in opener.calls[1]["body"]


class _Body:
    def __init__(self, data):
        self.data = data

    def read(self, *a):
        out, self.data = self.data, b""
        return out

    def close(self):
        pass


# ── OpenAI 相容 SSE（vLLM、LM Studio、其他）──────────────────────────────

def test_sse_tool_call_deltas_are_assembled():
    chunks = [
        {"choices": [{"index": 0, "delta": {"role": "assistant", "content": "我來"}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "id": "call_a", "type": "function", "function": {"name": "money__add", "arguments": ""}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{\"amou"}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 1, "id": "call_b", "function": {"name": "note__add", "arguments": "{\"text\":"}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "nt\": \"80\"}"}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 1, "function": {"arguments": " \"牛奶\"}"}}]}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 200, "completion_tokens": 30}},
    ]
    lines = [": keep-alive"] + [f"data: {json.dumps(c, ensure_ascii=False)}" for c in chunks] + ["", "data: [DONE]"]
    a, opener = ollama({("POST", "/v1/chat/completions"): FakeResp(lines), ("GET", "/v1/models"):
                        json_resp({"data": [{"id": "qwen", "max_model_len": 32768}]})},
                       model="qwen", server="vllm", base_url="http://127.0.0.1:8000/v1/", context_size=8192)
    reply = a.chat([Message(USER, "記 80，再記牛奶")], [SPEC])
    assert reply.text == "我來"
    assert [(c.name, c.args, c.id) for c in reply.tool_calls] == [
        ("money__add", {"amount": "80"}, "call_a"), ("note__add", {"text": "牛奶"}, "call_b")]
    assert reply.usage == {"input": 200, "output": 30}
    call = opener.calls[0]
    assert call["url"] == "http://127.0.0.1:8000/v1/chat/completions"         # 貼 /v1/ 也對
    assert call["body"]["stream"] is True and call["body"]["stream_options"] == {"include_usage": True}
    assert "options" not in call["body"] and "num_ctx" not in json.dumps(call["body"])     # context 客戶端設不了
    assert a.server_ctx == 32768                                                # /v1/models 讀到的


def test_sse_bad_arguments_become_empty_with_warning():
    lines = [f"data: {json.dumps(c)}" for c in (
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "x", "function": {"name": "a", "arguments": "{oops"}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]})] + ["data: [DONE]"]
    a, _ = ollama({("POST", "/v1/chat/completions"): FakeResp(lines)}, model="m", server="lmstudio")
    reply = a.chat([Message(USER, "hi")], [SPEC])
    assert reply.tool_calls[0].args == {} and any("JSON" in w for w in reply.warnings)


# ── 逾時：無進展 vs 總上限 ───────────────────────────────────────────

def test_no_progress_timeout_is_named():
    stream = FakeResp(ndjson({"message": {"content": "好"}, "done": False}), stall_after=1)
    a, _ = ollama({("POST", "/api/chat"): stream}, context_size=8192, timeout=30)
    with pytest.raises(LLMError) as e:
        a.chat([Message(USER, "hi")])
    assert "無進展" in str(e.value) and "30 秒" in str(e.value) and stream.closed


def test_no_progress_before_first_token_counts_too():
    a, opener = ollama({("POST", "/api/chat"): urllib.error.URLError(socket.timeout("timed out"))}, context_size=8192)
    with pytest.raises(LLMError) as e:
        a.chat([Message(USER, "hi")])
    assert "無進展" in str(e.value) and opener.calls[0]["timeout"] == 450.0


def test_keeps_going_while_the_model_is_still_answering():
    clock = Clock()
    parts = [{"message": {"content": "字"}, "done": False}] * 12 + [{"done": True, "prompt_eval_count": 10, "eval_count": 12}]
    stream = FakeResp(ndjson(*parts), clock=clock, step=100.0)       # 每 100 秒吐一點：遠超過 450 的總時間也不砍
    a, _ = ollama({("POST", "/api/chat"): stream}, context_size=8192, clock=clock)
    reply = a.chat([Message(USER, "hi")])
    assert reply.text == "字" * 12 and clock.t >= 1300


def test_total_cap_stops_a_never_ending_answer():
    clock = Clock()
    parts = [{"message": {"content": "字"}, "done": False}] * 40
    stream = FakeResp(ndjson(*parts), clock=clock, step=100.0)
    a, _ = ollama({("POST", "/api/chat"): stream}, context_size=8192, clock=clock, max_total_timeout=1800)
    with pytest.raises(LLMError) as e:
        a.chat([Message(USER, "hi")])
    assert "總上限" in str(e.value) and "1800" in str(e.value) and stream.closed


def test_stream_without_done_is_an_error():
    a, _ = ollama({("POST", "/api/chat"): FakeResp(ndjson({"message": {"content": "半"}, "done": False}))},
                  context_size=8192)
    with pytest.raises(LLMError) as e:
        a.chat([Message(USER, "hi")])
    assert "中途斷了" in str(e.value)


# ── 截斷提醒 ─────────────────────────────────────────────────────────

def test_truncation_warning_is_loud(caplog):
    stream = FakeResp(ndjson({"message": {"content": "好"}, "done": True, "prompt_eval_count": 4000, "eval_count": 1}))
    a, _ = ollama({("POST", "/api/chat"): stream}, context_size=4096)
    with caplog.at_level(logging.WARNING):
        reply = a.chat([Message(USER, "hi")])
    assert reply.warnings and "截斷" in reply.warnings[0] and "4096" in reply.warnings[0]
    assert a.last_warning == reply.warnings[0]
    assert any("截斷" in r.getMessage() for r in caplog.records)


def test_truncation_uses_the_context_ollama_reports_when_not_set():
    stream = FakeResp(ndjson({"message": {"content": "好"}, "done": True, "prompt_eval_count": 8000, "eval_count": 1}))
    a, opener = ollama({("POST", "/api/chat"): stream,
                        ("GET", "/api/ps"): json_resp({"models": [{"name": "qwen3.5:9b", "context_length": 8192}]})})
    reply = a.chat([Message(USER, "hi")])
    assert a.server_ctx == 8192 and reply.warnings and "8192" in reply.warnings[0]
    assert ("GET", "/api/ps") in [(c["method"], c["path"]) for c in opener.calls]


def test_no_warning_with_room_and_preflight_estimate():
    ok = FakeResp(ndjson({"message": {"content": "好"}, "done": True, "prompt_eval_count": 1000, "eval_count": 1}))
    a, _ = ollama({("POST", "/api/chat"): ok}, context_size=8192)
    assert a.chat([Message(USER, "hi")]).warnings == []
    cached = FakeResp(ndjson({"message": {"content": "好"}, "done": True, "prompt_eval_count": 10, "eval_count": 1}))
    b, _ = ollama({("POST", "/api/chat"): cached}, context_size=1024)
    reply = b.chat([Message(SYSTEM, "字" * 3000), Message(USER, "hi")])      # 回報很少（快取），但送出的明顯超過
    assert reply.warnings and "估計" in reply.warnings[0]


def test_agent_loop_tells_the_user_about_warnings(make_bot, owner):
    bot = make_bot([Reply(text="好了", warnings=["提示用了 4000 tokens，很可能被截斷"])])
    bot.talk(owner, "嗨")
    texts = bot.texts(owner)
    assert "好了" in texts and any("很可能被截斷" in t for t in texts)
    loop = bot.app.extras["synox_agent"]
    assert all("截斷" not in m.content for msgs in loop.history.values() for m in msgs)    # 不進對話記憶


# ── 錯誤翻成中文 ─────────────────────────────────────────────────────

def test_errors_are_one_chinese_sentence():
    down, _ = ollama({("POST", "/api/chat"): urllib.error.URLError(ConnectionRefusedError(10061, "refused"))},
                     context_size=8192)
    with pytest.raises(LLMError) as e:
        down.chat([Message(USER, "hi")])
    assert "連不到" in str(e.value) and "Ollama" in str(e.value)
    missing, _ = ollama({("POST", "/api/chat"): urllib.error.HTTPError(
        "u", 404, "nf", {}, _Body(b'{"error":"model \'nope\' not found"}'))}, model="nope", context_size=8192)
    with pytest.raises(LLMError) as e:
        missing.chat([Message(USER, "hi")])
    assert "ollama pull nope" in str(e.value)
    oom, _ = ollama({("POST", "/api/chat"): FakeResp(ndjson(
        {"error": "model requires more system memory (20 GiB) than is available (8 GiB)"}))}, context_size=8192)
    with pytest.raises(LLMError) as e:
        oom.chat([Message(USER, "hi")])
    assert "記憶體不夠" in str(e.value) and "context_size" in str(e.value)
    with pytest.raises(LLMError) as e:
        LocalAdapter("", opener=FakeOpener({})).chat([Message(USER, "hi")])
    assert "模型" in str(e.value)


# ── 唯讀的探測 ───────────────────────────────────────────────────────

def test_probe_is_read_only_and_reports_the_model():
    a, opener = ollama({("GET", "/api/tags"): json_resp(TAGS), ("POST", "/api/show"): json_resp(SHOW)},
                       context_size=8192)
    assert a.probe() is None
    report = a.inspect()
    assert report["model_found"] is True and report["max_context"] == 262144 and report["model_size"] == 6_594_474_711
    assert "vision" in report["capabilities"]
    assert not set(opener.paths()) & set(CHAT_PATHS)                     # 絕不送 chat／generate
    assert opener.calls[1]["body"] == {"model": "qwen3.5:9b"}            # /api/show 只讀模型資料
    assert any("模型 qwen3.5:9b" in line for line in local.report_lines(report))


def test_probe_problems():
    routes = {("GET", "/api/tags"): json_resp(TAGS), ("POST", "/api/show"): json_resp(SHOW)}
    a, opener = ollama(routes, model="llama9")
    assert "ollama pull llama9" in a.probe()
    b, _ = ollama(routes, context_size=1048576)
    assert "上限 262144" in b.probe()
    no_tools = {("GET", "/api/tags"): json_resp(TAGS),
                ("POST", "/api/show"): json_resp({**SHOW, "capabilities": ["completion"]})}
    c, _ = ollama(no_tools, context_size=8192)
    assert "tools" in c.probe()
    d, _ = ollama(routes)                                                     # 沒設 context：提醒（不是錯）
    assert d.probe() is None and any("沒設 context_size" in n for n in d.inspect()["notes"])
    e, _ = ollama({("GET", "/api/tags"): urllib.error.URLError(ConnectionRefusedError())})
    assert "連不到" in e.probe()
    for adapter in (a, b, c, d, e):
        assert not set(p for p in opener.paths()) & set(CHAT_PATHS)


def test_vllm_probe_reads_max_model_len_and_says_context_is_server_side():
    a, opener = ollama({("GET", "/v1/models"): json_resp({"data": [{"id": "qwen", "max_model_len": 16384}]})},
                       model="qwen", server="vllm", context_size=8192)
    report = a.inspect()
    assert report["model_found"] and report["max_context"] == 16384 and a.probe() is None
    assert any("--max-model-len" in n for n in report["notes"])
    assert opener.paths() and set(opener.paths()) == {"/v1/models"}


# ── 網址 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url,kind", [("http://127.0.0.1:11434", "loopback"), ("http://localhost:11434", "loopback"),
                                      ("http://[::1]:11434", "loopback"), ("http://192.168.1.20:11434", "private"),
                                      ("http://10.0.0.5:8000", "private"), ("http://gpu-box:11434", "private"),
                                      ("http://nas.lan:1234", "private"), ("http://8.8.8.8:11434", "public"),
                                      ("https://llm.example.com", "unknown")])
def test_url_kinds_and_warnings(url, kind):
    assert local.host_kind(url) == kind
    assert bool(local.url_warning(url)) == (kind in ("public", "unknown"))


# ── 建議（純函式）────────────────────────────────────────────────────

def test_kv_bytes_per_token():
    assert local_advice.kv_bytes_per_token(SHOW["model_info"]) == (32 * 512 * 2, "exact")     # 混合架構：只有 8 層有 KV
    dense = {"general.architecture": "llama", "llama.block_count": 32, "llama.attention.head_count": 32,
             "llama.attention.head_count_kv": 8, "llama.embedding_length": 4096}
    assert local_advice.kv_bytes_per_token(dense) == (2 * 32 * 8 * 128 * 2, "exact")
    assert local_advice.kv_bytes_per_token({"general.architecture": "x", "x.block_count": 10,
                                            "x.embedding_length": 1000})[1] == "rough"
    assert local_advice.kv_bytes_per_token({}) == (local_advice.STATIC_KV_PER_TOKEN, "static")


def test_advise_levels_truncation_and_conservative_pick():
    gb = 1_000_000_000
    out = local_advice.advise(avail_ram=16 * gb, total_ram=32 * gb, weights_bytes=6 * gb,
                              kv_per_token=144 * 1024, kv_source="exact", model_max_ctx=65536,
                              prompt_tokens=3500, max_tokens=1024)
    ctxs = [r["ctx"] for r in out["options"]]
    assert ctxs == [4096, 8192, 16384, 32768, 65536]                       # 不超過模型上限
    by = {r["ctx"]: r for r in out["options"]}
    assert by[4096]["truncates"] is True and "會截斷" in by[4096]["text"]   # 測試紀錄：4096 會靜默截斷
    assert by[8192]["level"] == "ok" and by[65536]["level"] == "risky"
    assert out["recommended"] == 8192 and by[8192]["recommended"]            # 夠用的最小那個（偏保守）
    assert out["min_context"] == 4524 and "估算" in out["notes"][0]
    assert local_advice.option_label(by[8192]) == "8192（推薦）"
    assert local_advice.option_label(by[4096]) == "4096（會截斷）"
    assert any("← 推薦" in line for line in local_advice.lines(out))


def test_advise_without_ram_or_model_falls_back_to_static():
    out = local_advice.from_report(None, ram=(None, None))
    assert out["source"] == "static" and all(r["level"] == "unknown" for r in out["options"])
    assert any("沒連上 Ollama" in n for n in out["notes"]) and any("量不到" in n for n in out["notes"])
    assert out["prompt_measured"] is False and out["prompt_tokens"] == local_advice.DEFAULT_PROMPT_TOKENS
    tiny = local_advice.advise(avail_ram=2 * 10 ** 9, prompt_tokens=100000)
    assert tiny["recommended"] is None and any("沒有一個選項" in n for n in tiny["notes"])
    assert local_advice.tokens_from_chars(25) == 10


def test_adapter_advice_reads_the_model_and_ram():
    a, opener = ollama({("GET", "/api/tags"): json_resp(TAGS), ("POST", "/api/show"): json_resp(SHOW)})
    out = a.advice(prompt_chars=8000, ram=(20 * 10 ** 9, 32 * 10 ** 9))
    assert out["source"] == "ollama" and out["prompt_measured"] and out["prompt_tokens"] == 3200
    assert out["recommended"] == 8192 and out["model_max_ctx"] == 262144
    assert not set(opener.paths()) & set(CHAT_PATHS)


# ── 設定、factory、精靈 ──────────────────────────────────────────────

def test_config_validation(tmp_path):
    def load(llm):
        return SynoxConfig.from_dict({"owner_id": 1, "llm": llm}, require_token=False, root=str(tmp_path)).llm
    llm = load({"kind": "local", "model": "qwen3.5:9b"})
    assert llm["server"] == "ollama" and llm["base_url"] == "http://127.0.0.1:11434"
    assert llm["context_size"] == 0 and llm["timeout"] == 0 and llm["max_total_timeout"] == 1800 and llm["tools"] is True
    assert load({"kind": "local", "server": "lmstudio"})["base_url"] == "http://127.0.0.1:1234"
    for bad in ({"server": "llamacpp"}, {"context_size": 100}, {"context_size": True}, {"context_size": 4096.5},
                {"context_size": 2_000_000}, {"timeout": -1}, {"timeout": "450"}, {"max_total_timeout": 0},
                {"timeout": 500, "max_total_timeout": 400}, {"tools": "yes"}, {"base_url": "ftp://x"}):
        with pytest.raises(Exception) as e:
            load({"kind": "local", "model": "m", **bad})
        assert "config.json" in str(e.value), bad
    with pytest.raises(Exception):
        load({"kind": "openai_compat", "base_url": "http://x/v1", "timeout": "slow"})
    assert load({"kind": "openai_compat", "base_url": "http://x/v1", "timeout": 120})["timeout"] == 120


def test_factory_builds_local_and_passes_openai_compat_timeout():
    opener = FakeOpener({})
    a = make_adapter({"llm": {"kind": "local", "model": "m", "context_size": 16384, "max_tokens": 512}}, opener=opener)
    assert isinstance(a, LocalAdapter) and a.kind == "local" and a.context_size == 16384
    assert a.timeout == 450.0 and a.max_total == 1800.0 and a.max_tokens == 512 and a._open is opener
    assert make_adapter({"llm": {"kind": "local", "model": "m", "timeout": 600, "max_total_timeout": 3600}}).timeout == 600
    with pytest.raises(LLMError):
        make_adapter({"llm": {"kind": "local", "server": "nope"}})
    assert easy_timeout({"kind": "openai_compat", "base_url": "http://127.0.0.1:11434/v1"}) == 450.0
    assert easy_timeout({"kind": "openai_compat", "base_url": "http://192.168.0.9:8000/v1"}) == 450.0
    assert easy_timeout({"kind": "openai_compat", "base_url": "https://gw.example.com/v1"}) == 90.0
    assert easy_timeout({"kind": "openai", "timeout": 120}) == 120.0 and easy_timeout({"kind": "anthropic"}) == 90.0
    compat = make_adapter({"llm": {"kind": "openai_compat", "base_url": "http://localhost:11434/v1", "model": "m"}})
    assert compat.timeout == 450.0                                           # 以前沒有把 timeout 傳下去


def test_wizard_logic_local_settings_and_advice():
    llm, err = logic.llm_settings("local", model="qwen3.5:9b", context_size="16384")
    assert err == "" and llm == {"kind": "local", "server": "ollama", "base_url": "http://127.0.0.1:11434",
                                 "model": "qwen3.5:9b", "context_size": 16384, "timeout": 450,
                                 "max_total_timeout": 1800, "tools": True}
    assert logic.llm_settings("local", model="")[1]
    assert logic.llm_settings("local", model="m", base_url="ftp://x")[1]
    assert "context_size" in logic.llm_settings("local", model="m", context_size=99)[1]
    assert logic.llm_settings("local", model="m", server="vllm")[0]["base_url"] == "http://127.0.0.1:8000"
    assert "local" in logic.CHOICES
    opener = FakeOpener({("GET", "/api/tags"): json_resp(TAGS), ("POST", "/api/show"): json_resp(SHOW)})
    out = logic.local_advice("ollama", "", "qwen3.5:9b", opener=opener, ram=(20 * 10 ** 9, 32 * 10 ** 9))
    assert out["source"] == "ollama" and out["recommended"]
    assert logic.probe_llm({"kind": "local", "model": "m"},
                           make=lambda c: make_adapter(c, opener=FakeOpener({}))) is not None   # 連不到也只回一句話


def test_init_cli_non_interactive_local(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from synox.wizard import init_cli
    seen = {}

    def fake_advice(server, base_url, model, **kw):
        seen.update(server=server, base_url=base_url, model=model)
        return local_advice.advise(avail_ram=None, prompt_tokens=3000)

    monkeypatch.setattr(logic, "local_advice", fake_advice)
    out = []
    args = SimpleNamespace(non_interactive=True, dry_run=True, mode="personal", telegram_token=None, owner_id=None,
                           llm="local", model="qwen3.5:9b", base_url=None, server="ollama", context_size=None,
                           api_key_env=None, library="", tools=None)
    assert init_cli.run(args, config_path=str(tmp_path / "config.json"), out=out.append) == 0
    text = "\n".join(out)
    assert '"kind": "local"' in text and '"context_size": 8192' in text and "← 推薦" in text
    assert seen == {"server": "ollama", "base_url": "http://127.0.0.1:11434", "model": "qwen3.5:9b"}
    assert not (tmp_path / "config.json").exists()


# ── 網頁設定頁 ───────────────────────────────────────────────────────

def test_web_settings_local_choice_save_test_and_advice(make_bot, owner, tmp_path, monkeypatch):
    from test_web import Client, ui_of
    routes = {("GET", "/api/tags"): json_resp(TAGS), ("POST", "/api/show"): json_resp(SHOW)}
    opener = FakeOpener(routes)
    monkeypatch.setattr(local, "default_opener", opener)
    monkeypatch.setattr(local_advice, "system_ram", lambda: (20 * 10 ** 9, 32 * 10 ** 9))
    bot = make_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    choice = next(x for x in c.get("/api/settings")[1]["llm_choices"] if x["choice"] == "local")
    assert [s["value"] for s in choice["servers"]] == ["ollama", "vllm", "lmstudio", "other"]
    assert choice["context_options"] == list(local_advice.OPTIONS)

    status, data = c.post("/api/settings/llm/test", {"choice": "local", "model": "qwen3.5:9b", "context_size": 8192})
    assert status == 200 and data["ok"] is True and data["lines"]
    status, data = c.post("/api/settings/llm/test", {"choice": "local", "model": "nope", "context_size": 8192})
    assert data["ok"] is False and "ollama pull nope" in data["message"]

    status, data = c.post("/api/settings/llm/local-advice", {"server": "ollama", "model": "qwen3.5:9b"})
    assert status == 200 and data["source"] == "ollama" and data["prompt_measured"] is True
    assert data["recommended"] in local_advice.OPTIONS and all("label" in r for r in data["options"])
    assert c.post("/api/settings/llm/local-advice", {"server": "x"})[0] == 400
    assert c.post("/api/settings/llm/local-advice", {"base_url": "file:///c:/"})[0] == 400
    assert c.get("/api/settings/llm/local-advice")[0] == 404                 # 只收 POST（要 CSRF）
    assert not set(opener.paths()) & set(CHAT_PATHS)

    status, data = c.post("/api/settings/llm", {"choice": "local", "server": "ollama", "model": "qwen3.5:9b",
                                                "context_size": 16384})
    assert status == 200 and data["applied"] is True, data
    cfg = json.load(open(tmp_path / "config.json", encoding="utf-8"))
    assert cfg["llm"]["kind"] == "local" and cfg["llm"]["context_size"] == 16384 and cfg["llm"]["timeout"] == 450
    loop = bot.app.extras["synox_agent"]
    assert isinstance(loop.adapter, LocalAdapter) and loop.adapter.context_size == 16384
    loop.adapter.last_warning = "提示很可能被截斷"
    llm = c.get("/api/settings")[1]["llm"]
    assert llm["kind"] == "local" and llm["context_size"] == 16384 and llm["warning"] == "提示很可能被截斷"
    status, data = c.post("/api/settings/llm", {"choice": "none"})
    assert "context_size" not in ui_of(bot).config.llm                       # 換來源：舊欄位不留


def test_settings_page_has_the_local_fields():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = open(os.path.join(root, "src", "synox", "web", "static", "app.html"), encoding="utf-8").read()
    for needle in ('id="llm-local-ctx"', 'id="llm-local-advice"', "/api/settings/llm/local-advice",
                   "建議值都是估算", "llm.timeout"):
        assert needle in html, needle
