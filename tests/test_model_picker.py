"""設定頁「AI 從哪裡來」的模型清單：列出模型（API 金鑰來源、OpenAI 相容服務）、打錯模型時「測一下」怎麼說、預設值。

不連網、不開埠：OpenAI 規格的 /models 用假的 opener 回；ntu_easy_llm 的新 adapter 一律當作沒有（走 SYNOX 的退路）。"""

import io
import json
import urllib.error

import pytest

from synox.llm import easy_llm, kinds, model_list
from synox.llm.base import LLMError

from test_web import Client, ui_of

pytestmark = pytest.mark.usefixtures("no_sockets")

KEY = "fake-key-0123456789abcdef"        # 假金鑰：只用來確認它不會出現在回應裡


class FakeResp:
    def __init__(self, data):
        self.body = json.dumps(data).encode("utf-8")
        self.closed = False

    def read(self):
        return self.body

    def close(self):
        self.closed = True


class Opener:
    """假的 urllib opener：記下送出的 request，回固定的內容或丟固定的錯誤。"""

    def __init__(self, data=None, error=None):
        self.data, self.error, self.calls = data, error, []

    def __call__(self, request, timeout):
        self.calls.append({"url": request.full_url, "auth": request.get_header("Authorization"), "timeout": timeout})
        if self.error is not None:
            raise self.error
        return FakeResp(self.data)


def http_error(code, body):
    return urllib.error.HTTPError("https://gw.example.com/v1/models", code, "err", {}, io.BytesIO(body.encode()))


MODELS = {"object": "list", "data": [{"id": "text-embedding-3-small"}, {"id": "zeta-chat"}, {"id": "Alpha-8b"},
                                     {"id": "whisper-1"}, {"id": "gpt-x-mini"}]}


# ── model_list：OpenAI 規格的 GET /models ─────────────────────────────


def test_openai_style_lists_chat_models_sorted():
    op = Opener(MODELS)
    rows = model_list.openai_style("https://gw.example.com/v1/", KEY, opener=op)
    assert [r["id"] for r in rows] == ["Alpha-8b", "gpt-x-mini", "zeta-chat"]     # embedding／語音不列
    assert op.calls[0]["url"] == "https://gw.example.com/v1/models"
    assert op.calls[0]["auth"] == f"Bearer {KEY}"
    assert model_list.openai_style("http://10.0.0.5:8000/v1", "", opener=Opener({"data": []})) == []


def test_openai_style_no_key_no_header():
    op = Opener({"data": [{"id": "m"}]})
    model_list.openai_style("https://gw.example.com/v1", "", opener=op)
    assert op.calls[0]["auth"] is None


def test_openai_style_errors_are_plain_and_keyless():
    with pytest.raises(LLMError) as e:                 # 伺服器把金鑰原樣回在錯誤裡：訊息裡要拿掉
        model_list.openai_style("https://gw.example.com/v1", KEY,
                                opener=Opener(error=http_error(401, f'{{"error": "bad key {KEY}"}}')))
    assert e.value.kind == "auth_invalid" and KEY not in str(e.value) and "金鑰" in str(e.value)
    with pytest.raises(LLMError) as e:
        model_list.openai_style("https://gw.example.com/v1", KEY,
                                opener=Opener(error=urllib.error.URLError("connection refused")))
    assert e.value.kind == "connection" and "連不到" in str(e.value)
    with pytest.raises(LLMError) as e:
        model_list.openai_style("https://gw.example.com", KEY, opener=Opener(error=http_error(404, "Not Found")))
    assert "/v1" in str(e.value)
    with pytest.raises(LLMError) as e:
        model_list.openai_style("https://gw.example.com/v1", KEY, opener=Opener("just text"))
    assert e.value.kind == "bad_response"
    with pytest.raises(LLMError):
        model_list.openai_style("", KEY, opener=Opener(MODELS))


def test_scrub_and_failed_text():
    assert KEY not in model_list.scrub(f"echo {KEY}", KEY)
    assert "sk-other-abcdefghij" not in model_list.scrub("x sk-other-abcdefghij y")     # 像金鑰的字也拿掉
    msg = model_list.failed(LLMError(f"金鑰不對 {KEY}"), KEY)
    assert msg.startswith("❌ 列不出模型") and "自己輸入" in msg and KEY not in msg


def test_fallback_only_for_openai_shapes():
    assert model_list.fallback({"kind": "openai_compat", "base_url": "https://gw.example.com/v1"}) is not None
    assert model_list.fallback({"kind": "openai", "api_key": KEY}) is not None
    assert model_list.fallback({"kind": "gemini"}) is None and model_list.fallback({"kind": "anthropic"}) is None
    assert "更新 SYNOX" in model_list.cannot_list("gemini") and "自己輸入" in model_list.cannot_list("gemini")


def test_http_kind_tells_wrong_model_apart():
    assert kinds.http_kind(404, '{"error":{"code":"model_not_found"}}') == "model_not_found"
    assert kinds.http_kind(400, "model 'qwen-nope' not found") == "model_not_found"
    assert kinds.http_kind(400, "The model `x` does not exist") == "model_not_found"
    assert kinds.http_kind(400, "temperature must be <= 2") == "bad_request"
    assert kinds.http_kind(401, "model not found") == "auth_invalid"


# ── 網頁：POST /api/settings/llm/models（API 金鑰來源）───────────────────


@pytest.fixture
def no_native(monkeypatch):
    """這台的 ntu_easy_llm 當作沒有新 adapter（0.5 或預發布版）：列模型走 SYNOX 的退路。"""
    monkeypatch.setattr(easy_llm, "contract", lambda: None)


@pytest.fixture
def opener(monkeypatch):
    op = Opener(MODELS)
    monkeypatch.setattr(model_list, "_default_opener", lambda base_url: op)
    return op


def owner_client(make_bot, owner, llm=None):
    bot = make_bot(llm=llm)
    c = Client(ui_of(bot))
    c.login(owner)
    return bot, c


def test_list_models_for_openai_compatible_service(make_bot, owner, no_native, opener):
    _bot, c = owner_client(make_bot, owner)
    body = {"choice": "keys", "provider": "openai_compat", "base_url": "https://gw.example.com/v1",
            "api_key": KEY, "model": ""}
    status, data = c.post("/api/settings/llm/models", body)
    assert status == 200 and data["ok"], data
    assert [m["id"] for m in data["models"]] == ["Alpha-8b", "gpt-x-mini", "zeta-chat"]
    assert "找到 3 個模型" in data["message"] and KEY not in json.dumps(data)
    assert opener.calls[0]["auth"] == f"Bearer {KEY}"
    # 網址沒填：一句話說要填網址（不連網）
    calls = len(opener.calls)
    status, data = c.post("/api/settings/llm/models", {**body, "base_url": ""})
    assert status == 400 and len(opener.calls) == calls


def test_list_models_errors_say_why_and_keep_manual(make_bot, owner, no_native, opener):
    _bot, c = owner_client(make_bot, owner)
    body = {"choice": "keys", "provider": "openai_compat", "base_url": "https://gw.example.com/v1", "api_key": KEY}
    opener.error = http_error(401, f'{{"error": "Incorrect API key {KEY}"}}')
    status, data = c.post("/api/settings/llm/models", body)
    assert status == 200 and not data["ok"] and data["kind"] == "auth_invalid"
    assert "列不出模型" in data["message"] and "自己輸入" in data["message"] and KEY not in json.dumps(data)
    opener.error = urllib.error.URLError("refused")
    data = c.post("/api/settings/llm/models", body)[1]
    assert not data["ok"] and data["kind"] == "connection" and "連不到" in data["message"]


def test_list_models_reuses_the_saved_key(make_bot, owner, no_native, opener):
    llm = {"kind": "openai_compat", "base_url": "https://gw.example.com/v1", "api_key": "vault:llm_api_key",
           "model": "old-name"}
    bot, c = owner_client(make_bot, owner, llm=llm)
    bot.app.extras["vault"].set_secret("llm_api_key", KEY)
    status, data = c.post("/api/settings/llm/models", {"choice": "keys", "provider": "openai_compat",
                                                       "base_url": "https://gw.example.com/v1", "api_key": ""})
    assert status == 200 and data["ok"] and opener.calls[-1]["auth"] == f"Bearer {KEY}"   # 留空＝沿用保管箱的
    assert KEY not in json.dumps(data)


def test_list_models_without_a_fallback_says_how_to_update(make_bot, owner, no_native, opener):
    _bot, c = owner_client(make_bot, owner)
    status, data = c.post("/api/settings/llm/models", {"choice": "keys", "provider": "gemini", "api_key": KEY})
    assert status == 200 and not data["ok"] and "更新 SYNOX" in data["message"] and not opener.calls


# ── 「測一下」：模型打錯 vs 連不到 ──────────────────────────────────────


class ProbeAdapter:
    def __init__(self, message, kind):
        self.message, self.kind_ = message, kind
        self.probe_kind = ""

    def probe(self):
        self.probe_kind = self.kind_
        return self.message


@pytest.mark.parametrize("kind,want,relist", [
    ("model_not_found", "列出模型", True),
    ("permission", "列出模型", True),
    ("connection", "跟模型名稱無關", False),
])
def test_test_button_tells_wrong_model_from_no_connection(make_bot, owner, monkeypatch, kind, want, relist):
    import synox.llm
    monkeypatch.setattr(synox.llm, "make_adapter", lambda cfg, *a, **k: ProbeAdapter(f"伺服器說 {KEY}", kind))
    _bot, c = owner_client(make_bot, owner)
    status, data = c.post("/api/settings/llm/test", {"choice": "keys", "provider": "openai_compat",
                                                     "base_url": "https://gw.example.com/v1", "api_key": KEY,
                                                     "model": "typo-model"})
    assert status == 200 and not data["ok"]
    assert want in data["message"] and data["relist"] is relist and data["kind"] == kind
    assert KEY not in json.dumps(data)


def test_old_path_marks_wrong_model_kind(monkeypatch):
    """ntu_easy_llm 0.5（舊路）的 404：訊息照舊，種類補上 model_not_found（測一下才分得出來）。"""
    pytest.importorskip("ntu_easy_llm.agent")
    monkeypatch.setattr(easy_llm, "contract", lambda: None)
    from test_llm import OpenAICompatAdapter, Resp, Session
    a = OpenAICompatAdapter("https://gw.example.com/v1", "k", "typo-model",
                            session=Session(Resp({"error": {"message": "model 'typo-model' not found"}}, 404)))
    msg = a.probe()
    assert msg and "404" in msg and a.probe_kind == "model_not_found"


def test_wrong_model_name_does_not_break_startup():
    """模型名稱打錯只會讓聊天失敗：做 adapter 不連網、不丟錯（SYNOX 照常起得來）。"""
    from synox.llm import make_adapter
    a = make_adapter({"llm": {"kind": "openai_compat", "base_url": "https://gw.example.com/v1",
                              "model": "no-such-model"}})
    assert a is not None and a.model == "no-such-model"


# ── 預設值與畫面 ──────────────────────────────────────────────────────


def test_compatible_service_has_no_prefilled_model(make_bot, owner):
    _bot, c = owner_client(make_bot, owner)
    choices = c.get("/api/settings")[1]["llm_choices"]
    compat = [x for x in choices if x.get("provider") == "openai_compat"][0]
    assert compat["model"] == "" and compat["needs_url"]
    assert [x for x in choices if x.get("provider") == "openai"][0]["model"]        # 其他照舊預填


def test_old_compat_settings_still_load(make_bot, owner):
    """舊設定（openai_compat＋llama3.1＋本機網址）照舊讀得進來、照舊顯示。"""
    llm = {"kind": "openai_compat", "base_url": "http://127.0.0.1:11434/v1", "model": "llama3.1"}
    _bot, c = owner_client(make_bot, owner, llm=llm)
    data = c.get("/api/settings")[1]["llm"]
    assert data["kind"] == "openai_compat" and data["model"] == "llama3.1"
    assert data["base_url"] == "http://127.0.0.1:11434/v1"


def test_page_has_the_picker():
    from importlib import resources
    html = resources.files("synox.web").joinpath("static/app.html").read_text(encoding="utf-8")
    for needle in ('id="llm-model-list"', 'id="llm-model-pick"', 'list="llm-model-names"', 'id="llm-model-filter"',
                   'list="llm-src-names"', 'id="llm-src-filter"', "不會讓 SYNOX 起不來", "function modelPicker",
                   'd.llm.kind === "openai_compat" ? d.llm.base_url'):
        assert needle in html, needle
    assert "llama3.1" not in html
