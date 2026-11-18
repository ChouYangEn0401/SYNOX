"""本地模型清單／載入／卸載（llm/local_models.py）與設定頁的 API：假的 opener，不連網、不載入模型。"""

import json

import pytest

from synox.llm import local, local_models
from synox.llm.base import LLMError
from fake_lmstudio import FakeLMStudio
from test_local_llm import CHAT_PATHS, FakeOpener, FakeResp, json_resp

RAM_BIG = (68_800_000_000, 137_000_000_000)

V1 = {"models": [
    {"type": "llm", "key": "qwen3.5-9b", "display_name": "Qwen3.5 9B", "quantization": {"name": "Q8_0"},
     "size_bytes": 9_304_201_000, "params_string": "9B", "max_context_length": 262144,
     "loaded_instances": [{"id": "qwen3.5-9b", "config": {"context_length": 32768}},
                          {"id": "qwen3.5-9b:2", "config": {"context_length": 32768}}],
     "capabilities": {"vision": True, "trained_for_tool_use": True}},
    {"type": "llm", "key": "qwen3-coder-30b-a3b-instruct", "loaded_instances": [], "max_context_length": 262144,
     "capabilities": {"vision": False, "trained_for_tool_use": True}},
    {"type": "embedding", "key": "text-embedding-nomic-embed-text-v1.5", "loaded_instances": []}]}
V0 = {"data": [{"id": "qwen3.5-9b", "type": "vlm", "state": "loaded", "loaded_context_length": 8192,
                "capabilities": ["tool_use"]},
               {"id": "nomic", "type": "embeddings", "state": "not-loaded"}]}
LMS = "http://localhost:1235/v1"


def test_lmstudio_lists_chat_models_loaded_first_without_embeddings():
    opener = FakeOpener({("GET", "/api/v1/models"): json_resp(V1)})
    out = local_models.list_models("lmstudio", LMS, opener=opener)
    assert [m["id"] for m in out["models"]] == ["qwen3.5-9b", "qwen3-coder-30b-a3b-instruct"] and out["can_load"]
    first = out["models"][0]
    assert first["loaded"] and first["context"] == 32768 and first["vision"] and first["tools"]
    assert first["instances"] == ["qwen3.5-9b", "qwen3.5-9b:2"] and first["label"] == "Qwen3.5 9B"
    assert local_models.pick_default(out["models"]) == "qwen3.5-9b"
    assert opener.calls[0]["url"] == "http://localhost:1235/api/v1/models"
    assert not set(opener.paths()) & set(CHAT_PATHS)


def test_old_lmstudio_falls_back_to_v0_and_cannot_load():
    opener = FakeOpener({("GET", "/api/v0/models"): json_resp(V0)})
    out = local_models.list_models("lmstudio", LMS, opener=opener)
    assert [m["id"] for m in out["models"]] == ["qwen3.5-9b"] and out["models"][0]["vision"] is True
    assert out["can_load"] is False and out["notes"]


def test_lmstudio_load_sends_model_and_context_and_unload_frees_every_instance():
    v1 = json.loads(json.dumps(V1))
    coder = v1["models"][1]

    def load_route():                                    # 載入後清單裡就有那個實例（照帶過去的 context）
        coder["loaded_instances"] = [{"id": "qwen3-coder", "config": {"context_length": 16384}}]
        return FakeResp(body={"instance_id": "qwen3-coder", "load_time_seconds": 9.1})
    opener = FakeOpener({("POST", "/api/v1/models/load"): load_route,
                         ("GET", "/api/v1/models"): lambda: FakeResp(body=v1),
                         ("POST", "/api/v1/models/unload"): lambda: FakeResp(body={"instance_id": "x"})})
    msg = local_models.load("lmstudio", LMS, "qwen3-coder-30b-a3b-instruct", 16384, opener=opener)
    assert "已載入" in msg and "9.1" in msg and "16384" in msg
    assert opener.calls[0]["body"] == {"model": "qwen3-coder-30b-a3b-instruct", "context_length": 16384}
    coder["loaded_instances"] = []
    assert opener.calls[0]["timeout"] == local.DEFAULT_TIMEOUT                  # 載入可能很久：不用 15 秒的探測逾時
    msg = local_models.unload("lmstudio", LMS, opener=opener)                   # 全部卸載＝釋放顯卡
    sent = [c["body"]["instance_id"] for c in opener.calls if c["path"] == "/api/v1/models/unload"]
    assert sent == ["qwen3.5-9b", "qwen3.5-9b:2"] and "已卸載 qwen3.5-9b" in msg
    assert "本來就沒有載入" in local_models.unload("lmstudio", LMS, "qwen3-coder-30b-a3b-instruct", opener=opener)


def test_api_key_goes_along_and_errors_are_one_sentence():
    seen = {}

    def opener(req, timeout):
        seen["auth"] = req.get_header("Authorization")
        return FakeResp(body=V1)
    local_models.list_models("lmstudio", LMS, "tok", opener=opener)
    assert seen["auth"] == "Bearer tok"
    with pytest.raises(LLMError):
        local_models.list_models("lmstudio", LMS, opener=FakeOpener({}))             # 404 兩個都沒有
    with pytest.raises(LLMError):
        local_models.load("lmstudio", LMS, "", opener=FakeOpener({}))


def test_ollama_list_load_and_unload():
    tags = {"models": [{"name": "qwen3.5:9b", "size": 6_600_000_000, "details": {"parameter_size": "9.7B"}},
                       {"name": "nomic-embed-text:latest"}, {"name": "tiny:latest"}]}
    opener = FakeOpener({("GET", "/api/tags"): json_resp(tags), ("GET", "/api/ps"): json_resp({"models": [{"name": "tiny:latest"}]}),
                         ("POST", "/api/generate"): lambda: FakeResp(body={"done": True})})
    out = local_models.list_models("ollama", "", opener=opener)
    assert [m["id"] for m in out["models"]] == ["tiny:latest", "qwen3.5:9b"] and out["models"][0]["loaded"]
    local_models.load("ollama", "", "qwen3.5:9b", 8192, opener=opener)
    body = [c for c in opener.calls if c["path"] == "/api/generate"][0]["body"]
    assert body == {"model": "qwen3.5:9b", "keep_alive": "30m", "options": {"num_ctx": 8192}} and "prompt" not in body
    local_models.unload("ollama", "", opener=opener)
    assert [c for c in opener.calls if c["path"] == "/api/generate"][-1]["body"] == {"model": "tiny:latest", "keep_alive": 0}


def test_vllm_lists_but_cannot_load():
    opener = FakeOpener({("GET", "/v1/models"): json_resp({"data": [{"id": "Qwen/Qwen3-8B", "max_model_len": 32768}]})})
    out = local_models.list_models("vllm", "http://127.0.0.1:8000", opener=opener)
    assert out["models"][0]["max_context"] == 32768 and out["can_load"] is False
    with pytest.raises(LLMError):
        local_models.load("vllm", "http://127.0.0.1:8000", "Qwen/Qwen3-8B", opener=opener)


def test_web_model_list_load_unload_owner_only_and_reuses_the_saved_key(make_bot, owner, tmp_path, monkeypatch):
    from test_web import Client, ui_of
    opener = FakeOpener({("GET", "/api/v1/models"): json_resp(V1),
                         ("POST", "/api/v1/models/load"): json_resp({"instance_id": "q", "load_time_seconds": 1.0}),
                         ("POST", "/api/v1/models/unload"): lambda: FakeResp(body={"instance_id": "x"})})
    auth = []
    monkeypatch.setattr(local, "default_opener", lambda req, t: auth.append(req.get_header("Authorization")) or opener(req, t))
    bot = make_bot()
    ui = ui_of(bot)
    ui.config.llm = {**ui.config.llm, "kind": "local", "server": "lmstudio", "base_url": "http://localhost:1235",
                     "model": "qwen3.5-9b", "api_key": "saved-token"}
    c = Client(ui)
    c.login(owner)
    status, data = c.post("/api/settings/llm/local-models", {"server": "lmstudio", "base_url": LMS})
    assert status == 200 and data["ok"] and data["suggested"] == "qwen3.5-9b" and data["can_load"]
    assert auth[-1] == "Bearer saved-token"                                     # 同一台伺服器：沿用存好的金鑰
    status, data = c.post("/api/settings/llm/local-load", {"server": "lmstudio", "base_url": LMS,
                                                           "model": "qwen3-coder-30b-a3b-instruct"})
    assert data["ok"] and "已載入" in data["message"]                           # 沒帶 context：不用讀回來比
    status, data = c.post("/api/settings/llm/local-unload", {"server": "lmstudio", "base_url": LMS})
    assert data["ok"] and "已卸載" in data["message"]
    c.post("/api/settings/llm/local-models", {"server": "lmstudio", "base_url": "http://192.168.1.9:1234"})
    assert auth[-1] is None                                                     # 別台伺服器：不送存好的金鑰
    assert c.post("/api/settings/llm/local-models", {"server": "x"})[0] == 400
    assert c.post("/api/settings/llm/local-models", {"server": "lmstudio", "base_url": "file:///c:/"})[0] == 400
    assert c.get("/api/settings/llm/local-models")[0] == 404                    # 只收 POST（要 CSRF）
    assert not set(p for p in opener.paths()) & set(CHAT_PATHS)
    assert Client(ui).post("/api/settings/llm/local-unload", {"server": "lmstudio"})[0] in (401, 403)   # 沒登入


def test_settings_page_has_the_model_list_and_gpu_buttons():
    from importlib import resources
    html = resources.files("synox.web").joinpath("static/app.html").read_text(encoding="utf-8")
    for needle in ('id="llm-local-pick"', 'id="llm-local-list"', 'id="llm-local-load"', 'id="llm-local-free"',
                   'id="llm-local-key"', "/api/settings/llm/local-models", "/api/settings/llm/local-unload"):
        assert needle in html


# ── 用選的 context 重新載入（LM Studio）：先估記憶體、只動這個模型、讀回來確認 ─────────────────

def test_reload_honored_reports_success_with_the_value_lm_studio_reads_back():
    fake = FakeLMStudio("honor")
    out = local_models.reload("lmstudio", LMS, "qwen3.5-9b", 16384, opener=fake, ram=RAM_BIG)
    assert out["ok"] is True and out["loaded_context"] == 16384 and "16384" in out["message"] and "✅" in out["message"]
    assert fake.instances("qwen3.5-9b") == [16384]
    assert fake.instances("other-model") == [4096]                              # 別的模型不動
    unloaded = [c["body"]["instance_id"] for c in fake.calls if c["path"] == "/api/v1/models/unload"]
    assert unloaded == ["qwen3.5-9b"]
    load = [c for c in fake.calls if c["path"] == "/api/v1/models/load"]
    assert [c["body"] for c in load] == [{"model": "qwen3.5-9b", "context_length": 16384}]
    assert fake.paths().index("/api/v1/models/unload") < fake.paths().index("/api/v1/models/load")
    assert fake.paths()[-1] == "/api/v1/models"                                 # 最後一定讀回來確認
    assert not set(fake.paths()) & set(CHAT_PATHS)


def test_reload_silently_ignored_is_not_reported_as_success():
    fake = FakeLMStudio("ignore")
    out = local_models.reload("lmstudio", LMS, "qwen3.5-9b", 16384, opener=fake, ram=RAM_BIG)
    assert out["ok"] is False and out["loaded_context"] == 8192 and "✅" not in out["message"]
    assert "8192" in out["message"] and "沒有換成功" in out["message"] and "--context-length 16384" in out["message"]
    with pytest.raises(LLMError) as e:                                          # 「載入這個模型」也一樣讀回來比
        local_models.load("lmstudio", LMS, "other-model", 16384, opener=FakeLMStudio("ignore", loaded={}))
    assert "8192" in str(e.value) and "沒有換成功" in str(e.value)


def test_reload_error_says_what_happened_and_leaves_other_models_alone():
    fake = FakeLMStudio("error")
    out = local_models.reload("lmstudio", LMS, "qwen3.5-9b", 16384, opener=fake, ram=RAM_BIG)
    assert out["ok"] is False and "✅" not in out["message"] and "out of resources" in out["message"]
    assert fake.instances("qwen3.5-9b") == []                                   # 假伺服器連載回去也失敗
    assert "手動載入" in out["message"] and out["loaded_context"] is None
    assert fake.instances("other-model") == [4096]


def test_reload_rolls_back_when_only_the_new_context_fails():
    fake = FakeLMStudio("honor")
    real = fake.__call__

    def opener(request, timeout):                                               # 16384 載不起來、8192 可以
        body = json.loads(request.data.decode("utf-8")) if request.data else {}
        if request.full_url.endswith("/api/v1/models/load") and body.get("context_length") == 16384:
            fake.mode = "error"
            try:
                return real(request, timeout)
            finally:
                fake.mode = "honor"
        return real(request, timeout)
    out = local_models.reload("lmstudio", LMS, "qwen3.5-9b", 16384, opener=opener, ram=RAM_BIG)
    assert out["ok"] is False and "原本的 context 8192" in out["message"] and out["loaded_context"] == 8192
    assert fake.instances("qwen3.5-9b") == [8192]


def test_reload_checks_memory_and_limits_before_touching_anything():
    fake = FakeLMStudio("honor")
    out = local_models.reload("lmstudio", LMS, "qwen3.5-9b", 131072, opener=fake, ram=(16_000_000_000, 32_000_000_000))
    assert out["ok"] is False and "沒有載入" in out["message"] and "撐得住的最大" in out["message"]
    assert out["largest_safe"] and out["largest_safe"] < 131072
    assert "/api/v1/models/unload" not in fake.paths() and "/api/v1/models/load" not in fake.paths()
    assert fake.instances("qwen3.5-9b") == [8192]
    with pytest.raises(LLMError) as e:
        local_models.reload("lmstudio", LMS, "qwen3.5-9b", 524288, opener=fake, ram=RAM_BIG)
    assert "262144" in str(e.value)
    for server in ("ollama", "vllm"):
        with pytest.raises(LLMError):
            local_models.reload(server, "", "m", 16384, opener=fake)
    with pytest.raises(LLMError):
        local_models.reload("lmstudio", LMS, "qwen3.5-9b", 0, opener=fake)
    old = FakeOpener({("GET", "/api/v0/models"): json_resp(V0)})                  # 舊版 LM Studio：說怎麼自己換
    with pytest.raises(LLMError) as e:
        local_models.reload("lmstudio", LMS, "qwen3.5-9b", 16384, opener=old)
    assert "lms load qwen3.5-9b --context-length 16384" in str(e.value)


@pytest.mark.parametrize("mode,ok", [("honor", True), ("ignore", False), ("error", False)])
def test_web_reload_reports_success_only_when_lm_studio_really_changed(make_bot, owner, monkeypatch, mode, ok):
    from synox.llm import local_advice
    from test_web import Client, ui_of
    fake = FakeLMStudio(mode)
    monkeypatch.setattr(local, "default_opener", fake)
    monkeypatch.setattr(local_advice, "system_ram", lambda: RAM_BIG)
    ui = ui_of(make_bot())
    c = Client(ui)
    c.login(owner)
    status, data = c.post("/api/settings/llm/local-reload", {"server": "lmstudio", "base_url": LMS,
                                                             "model": "qwen3.5-9b", "context_length": 16384})
    assert status == 200 and data["ok"] is ok and ("✅" in data["message"]) is ok
    if ok:
        assert data["loaded_context"] == 16384
    assert fake.instances("other-model") == [4096]
    assert c.get("/api/settings/llm/local-reload")[0] == 404                     # 只收 POST（要 CSRF）
    assert Client(ui).post("/api/settings/llm/local-reload", {"server": "lmstudio"})[0] in (401, 403)


def test_settings_page_has_the_reload_button_with_a_confirm():
    from importlib import resources
    html = resources.files("synox.web").joinpath("static/app.html").read_text(encoding="utf-8")
    for needle in ('id="llm-local-reload"', "/api/settings/llm/local-reload", "其他模型不會動", "confirm("):
        assert needle in html
