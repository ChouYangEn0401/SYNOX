"""設定頁的 AI 來源目錄、列模型、kind=source 的存取、備援（docs/adr/0046）。

直接呼叫 WebUI.handle（不開埠）；來源一律是假的：ntu_easy_llm 的 register_adapter 換一個假 factory（不連網）。"""

import json

import pytest

from synox.llm import router as wf

from conftest import OTHER_ID
from test_web import Client, ui_of
from isdtelekit.users.roles import BasicRoles

pytestmark = pytest.mark.usefixtures("no_sockets")

TEST_SOURCE = "remote/api_key/example_test"


def needs_06():
    pytest.importorskip("ntu_easy_llm.catalog", reason="要 ntu_easy_llm 0.6（來源目錄）")


@pytest.fixture
def owner_web(make_bot, owner):
    bot = make_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    return bot, c


@pytest.fixture
def example_source(monkeypatch):
    """目錄上多一個假的 API 金鑰來源（真的目錄只認得它的分類樹；這裡把它塞進 remote/api_key 那一組）。"""
    needs_06()
    from ntu_easy_llm import catalog as cat
    from ntu_easy_llm.adapters import ModelInfo, register_adapter, unregister_adapter
    from ntu_easy_llm.adapters.fake import FakeAdapter
    seen = {}

    def factory(profile, *, http=None, resolve_secret=None):
        seen["key"] = resolve_secret(profile.secret) if profile.secret else ""
        seen["profile"] = profile
        return FakeAdapter(default="好", profile=profile,
                           models=[ModelInfo("m-b"), ModelInfo("m-a", loaded=True), ModelInfo("e", kind="embedding")])
    register_adapter(TEST_SOURCE, factory, replace=True)
    monkeypatch.setattr(cat, "_API_KEY", cat._API_KEY + ("example_test",))
    yield seen
    unregister_adapter(TEST_SOURCE)


def config_of(tmp_path):
    with open(tmp_path / "config.json", encoding="utf-8") as f:
        return json.load(f)


def test_catalog_is_owner_only_and_offline(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    m = Client(ui_of(bot))
    m.login(OTHER_ID)
    assert m.get("/api/settings/llm/catalog")[0] == 403
    for path in ("/api/settings/llm/models", "/api/settings/llm/waterfall"):
        assert m.post(path, {})[0] == 403, path
    o = Client(ui_of(bot))
    o.login(owner)
    status, data = o.get("/api/settings/llm/catalog")
    assert status == 200
    fams = [f["id"] for f in data["tree"]["families"]]
    assert fams == ["local", "remote", "none"]
    assert data["current"]["kind"] == "fake" and data["waterfall"]["mode"] == "off"
    assert o.raw("POST", "/api/settings/llm/models", b"{}", headers={"X-SYNOX-CSRF": "wrong"})[0] == 403   # CSRF


def test_settings_still_lists_old_choices_plus_source(owner_web):
    _bot, c = owner_web
    data = c.get("/api/settings")[1]
    choices = [x["choice"] for x in data["llm_choices"]]
    assert choices[:1] == ["claude_code"] and "keys" in choices and "local" in choices and choices[-1] == "source"
    assert data["llm"]["waterfall"] == "備援：關（只用主要來源）"


def test_save_and_list_a_source(owner_web, example_source, tmp_path):
    bot, c = owner_web
    status, data = c.post("/api/settings/llm/models", {"choice": "source", "source": TEST_SOURCE,
                                                       "api_key": "k-live-1"})
    assert status == 200 and data["ok"] and [m["id"] for m in data["models"]] == ["m-a", "m-b"]
    assert example_source["key"] == "k-live-1"
    body = {"choice": "source", "source": TEST_SOURCE, "model": "m-a", "api_key": "k-live-1",
            "options": {"max_tokens": "2048", "temperature": "0.3", "evil": "x"}}
    status, data = c.post("/api/settings/llm", body)
    assert status == 200 and data["applied"], data
    llm = config_of(tmp_path)["llm"]
    assert llm["kind"] == "source" and llm["source"] == TEST_SOURCE and llm["model"] == "m-a"
    assert llm["api_key"] == "vault:llm_api_key" and llm["source_options"] == {"max_tokens": 2048, "temperature": 0.3}
    assert "k-live-1" not in json.dumps(config_of(tmp_path))
    assert bot.app.extras["vault"].secret("llm_api_key") == "k-live-1"
    agent = bot.app.extras["synox_agent"]
    assert agent.adapter.kind == "source" and agent.adapter.max_tokens == 2048
    status, data = c.post("/api/settings/llm", {**body, "api_key": "", "model": "m-b"})     # 留空＝沿用
    assert status == 200 and config_of(tmp_path)["llm"]["api_key"] == "vault:llm_api_key"
    status, data = c.post("/api/settings/llm/test", {**body, "api_key": ""})
    assert status == 200 and data["ok"], data
    cur = c.get("/api/settings/llm/catalog")[1]["current"]
    assert cur["kind"] == "source" and cur["source"] == TEST_SOURCE and cur["options"]["max_tokens"] == 2048
    # 換回本地內建：source 的欄位不留在設定裡
    status, data = c.post("/api/settings/llm", {"choice": "local", "server": "ollama", "model": "qwen"})
    assert status == 200
    llm = config_of(tmp_path)["llm"]
    assert llm["kind"] == "local" and "source" not in llm and "source_options" not in llm


def test_source_errors(owner_web, example_source):
    _bot, c = owner_web
    assert c.post("/api/settings/llm", {"choice": "source", "source": "local/nope_nope"})[0] == 400
    assert c.post("/api/settings/llm", {"choice": "source", "source": "remote/api_key/openai"})[0] == 400  # 用 keys 設
    status, data = c.post("/api/settings/llm", {"choice": "source", "source": TEST_SOURCE, "model": "m"})
    assert status == 400 and "金鑰" in data["error"]
    status, data = c.post("/api/settings/llm", {"choice": "source", "source": TEST_SOURCE, "model": "m",
                                                "api_key": "k", "options": {"max_tokens": "many"}})
    assert status == 400 and "整數" in data["error"]
    status, data = c.post("/api/settings/llm", {"choice": "source", "source": TEST_SOURCE, "api_key": "k"})
    assert status == 400 and "模型" in data["error"]


def test_unavailable_source_cannot_be_saved(owner_web):
    needs_06()
    _bot, c = owner_web
    tree = c.get("/api/settings/llm/catalog")[1]["tree"]
    subs = tree["families"][1]["auths"][1]["services"]
    grey = [s for s in subs if not s["available"]]
    if not grey:
        pytest.skip("這台的 ntu_easy_llm 每個訂閱來源都能用了")
    status, data = c.post("/api/settings/llm", {"choice": "source", "source": grey[0]["source"]})
    assert status == 400 and data["error"] == grey[0]["reason"]


def test_waterfall_api_add_reorder_remove(owner_web, tmp_path, monkeypatch):
    bot, c = owner_web
    monkeypatch.setattr(wf, "router_class", lambda: None)         # 這台的 ntu_easy_llm 還沒有 router
    status, data = c.post("/api/settings/llm/waterfall", {"mode": "auto", "add": {"choice": "claude_code"}})
    assert status == 200, data
    status, data = c.post("/api/settings/llm/waterfall", {"mode": "ask", "add": {
        "choice": "keys", "provider": "openai", "api_key": "sk-backup-123", "model": "gpt-x"}})
    assert status == 200, data
    wfc = config_of(tmp_path)["llm"]["waterfall"]
    assert wfc["mode"] == "ask" and [b["kind"] for b in wfc["backups"]] == ["claude_code", "openai"]
    assert wfc["backups"][1]["api_key"] == "vault:llm_api_key_backup_1"
    assert "sk-backup" not in json.dumps(config_of(tmp_path))
    assert bot.app.extras["vault"].secret("llm_api_key_backup_1") == "sk-backup-123"
    assert data["waterfall"]["status"] == wf.NO_ROUTER and data["waterfall"]["backups"][0]["label"] == "Claude Code"
    status, data = c.post("/api/settings/llm/waterfall", {"mode": "ask", "keep": [1, 0]})
    assert [b["kind"] for b in config_of(tmp_path)["llm"]["waterfall"]["backups"]] == ["openai", "claude_code"]
    for bad in ({"mode": "ask", "keep": [5]}, {"mode": "ask", "keep": [0, 0]}, {"mode": "sometimes"},
                {"mode": "auto", "add": {"choice": "none"}}):
        assert c.post("/api/settings/llm/waterfall", bad)[0] == 400, bad
    # 換主要來源不洗掉備援
    assert c.post("/api/settings/llm", {"choice": "claude_code", "model": "sonnet"})[0] == 200
    assert len(config_of(tmp_path)["llm"]["waterfall"]["backups"]) == 2
    status, data = c.post("/api/settings/llm/waterfall", {"mode": "off", "keep": []})
    assert status == 200 and "waterfall" not in config_of(tmp_path)["llm"]      # 全拿掉＝回到沒寫
    assert data["waterfall"]["status"] == "備援：關（只用主要來源）"
