"""設定頁「功能與安裝」的官方工具庫（packs/catalog.py ＋ web/server.py 的 /api/packs/library*）。

- 只在按按鈕（POST＋CSRF、只有擁有者）時連網，網址寫死在程式裡（ADR 0022 決定 25）；送來的資料不能決定連去哪。
- 「安裝」＝伺服器自己下載 → 對檔名、大小、雜湊 → 交給 admin.stage（跟上傳同一條路）→ 報告 → 人按確認才裝。
- 轉址只跟到 GitHub 自己的主機（https）；測試一律用假的 opener，不連網。
"""

import hashlib
import json
import os
import urllib.error

import pytest

from isdtelekit.users.roles import BasicRoles

from synox.packs import catalog
from test_web import Client, _pack_zip, owner_client, ui_of  # noqa: F401  (owner_client 是 fixture)

from conftest import OTHER_ID

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REAL_INDEX = os.path.join(HERE, "fixtures", "libs_index_v0.2.0.json")     # 真的 v0.2.0 發佈的目錄（抓一次存下來）
GH = "https://github.com/ChouYangEn0401/SYNOX_Libs/releases/"
ASSETS = "https://release-assets.githubusercontent.com/github-production-release-asset/1/abc?sig=x"


class FakeWeb:
    """假的網路：url → (status, Location, body)；記下每一個被要求的網址。"""

    def __init__(self, routes=None, fail=None):
        self.routes = dict(routes or {})
        self.fail = fail
        self.calls = []

    def __call__(self, url, timeout, limit):
        self.calls.append(url)
        assert timeout and timeout <= 60                       # 一定有逾時
        if self.fail is not None:
            raise self.fail
        if url not in self.routes:
            return 404, None, b""
        status, location, body = self.routes[url]
        return status, location, body[:limit + 1]


def _zip(name, version):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(_pack_zip(name)), "r") as src, zipfile.ZipFile(buf, "w") as z:
        for info in src.infolist():
            data = src.read(info)
            if info.filename == "pack.json":
                data = json.dumps({**json.loads(data), "version": version}).encode("utf-8")
            z.writestr(info.filename, data)
    return buf.getvalue()


def _entry(name_, version_, blob, **over):
    name, version = name_, version_
    out = {"name": name, "title": "👋 打招呼", "summary": "說嗨", "version": version, "stage": "alpha",
           "kind": "python", "group": name, "access": "owner", "capabilities": [], "requires": {},
           "bundles": [], "file": f"{name}-{version}.synoxpack", "sha256": hashlib.sha256(blob).hexdigest(),
           "size": len(blob)}
    out.update(over)
    return out


def _index(entries, library_version="0.3.0"):
    return json.dumps({"library": "SYNOX_Libs", "library_version": library_version, "packs": entries,
                       "bundles": {}}).encode("utf-8")


def _web(entries, files, library_version="0.3.0", **kw):
    """官方目錄（latest → 轉址到該版的檔 → 轉址到 GitHub 的檔案主機）＋各個工具檔。"""
    tag = f"v{library_version}"
    routes = {
        catalog.OFFICIAL_INDEX_URL: (302, f"{GH}download/{tag}/index.json", b""),
        f"{GH}download/{tag}/index.json": (302, ASSETS + "&f=index", b""),
        ASSETS + "&f=index": (200, None, _index(entries, library_version)),
    }
    for fname, blob in files.items():
        routes[f"{GH}download/{tag}/{fname}"] = (302, ASSETS + "&f=" + fname, b"")
        routes[ASSETS + "&f=" + fname] = (200, None, blob)
    return FakeWeb(routes, **kw)


def _staged(bot):
    staging = os.path.join(bot.app.config.data_dir, "web_uploads")
    return os.listdir(staging) if os.path.isdir(staging) else []


# ── 目錄（純函式）────────────────────────────────────────────────────

def test_constants_are_the_fixed_official_source():
    assert catalog.OFFICIAL_INDEX_URL == \
        "https://github.com/ChouYangEn0401/SYNOX_Libs/releases/download/v0.2.0/index.json"
    assert catalog.DOWNLOAD_PREFIX == "https://github.com/ChouYangEn0401/SYNOX_Libs/releases/download/"
    assert catalog.RELEASES_PAGE == "https://github.com/ChouYangEn0401/SYNOX_Libs/releases"
    assert set(catalog.REDIRECT_HOSTS) == {"github.com", "objects.githubusercontent.com",
                                           "release-assets.githubusercontent.com"}


def test_real_release_index_is_read_into_friendly_cards():
    with open(REAL_INDEX, "rb") as f:
        lib = catalog.parse_index(f.read())
    tools = {t.name: t for t in lib.tools}
    assert set(tools) == {"notes", "todo", "money", "calendar", "bullet", "notion", "todoist", "google-calendar",
                          "apple-reminders"}
    assert lib.tag == "v0.2.0"
    for t in lib.tools:
        assert t.download_url == f"{catalog.DOWNLOAD_PREFIX}v0.2.0/{t.file}"
        assert t.help_url.startswith("https://claude.ai/artifact/")
    assert tools["notes"].help_url == "https://claude.ai/artifact/NpYbd3FtMAkXmASXc1pJzh"
    assert tools["apple-reminders"].help_url == "https://claude.ai/artifact/Jm4tdCTZdaQ1mc1waTatYp"
    view = {v["name"]: v for v in (catalog.card(t, installed="") for t in lib.tools)}
    assert view["money"]["emoji"] == "💰" and view["money"]["title"] == "記帳" and view["money"]["version"] == "0.2.0"
    assert view["notion"]["emoji"] == "🗂" and view["notion"]["title"] == "Notion"
    assert view["bullet"]["emoji"] == "•" and view["bullet"]["title"] == "子彈筆記"
    assert view["notes"]["line"] == "記一筆、找、刪" and view["notes"]["example"] == "/note 買牛奶"
    texts = {name: [b["text"] for b in v["badges"]] for name, v in view.items()}
    for name in ("notion", "todoist", "google-calendar", "apple-reminders"):
        assert "只用模擬測過" in texts[name] and "👤 單人用" in texts[name], name
    for name in ("notes", "todo", "money", "calendar", "bullet"):
        assert "👥 伺服器版也能用" in texts[name] and "只用模擬測過" not in texts[name], name
    assert all("🧪 alpha" in t for t in texts.values())


def test_unknown_tool_falls_back_to_catalog_title_and_summary():
    blob = _pack_zip()
    lib = catalog.parse_index(_index([_entry("hello", "0.1.0", blob)]))
    v = catalog.card(lib.tools[0], installed="")
    assert v["emoji"] == "👋" and v["title"] == "打招呼" and v["line"] == "說嗨"
    assert v["help_url"] == catalog.OVERVIEW_URL                          # 沒有自己的說明頁：給工具庫介紹


@pytest.mark.parametrize("bad", [
    {"file": "../evil.synoxpack"}, {"file": "hello-0.1.0.exe"}, {"file": "other-0.1.0.synoxpack"},
    {"file": "sub/hello-0.1.0.synoxpack"}, {"sha256": "abc"}, {"sha256": ""}, {"name": "Bad Name"},
    {"version": "latest"}, {"size": catalog.MAX_PACK + 1},
])
def test_entries_with_unsafe_or_inconsistent_fields_are_dropped(bad):
    blob = _pack_zip()
    lib = catalog.parse_index(_index([_entry("hello", "0.1.0", blob, **bad)]))
    assert lib.tools == []


@pytest.mark.parametrize("blob", [b"not json", b"[]", b'{"packs": 3}', json.dumps(
    {"library_version": "../x", "packs": []}).encode()])
def test_broken_index_is_a_plain_error(blob):
    with pytest.raises(catalog.CatalogError) as e:
        catalog.parse_index(blob)
    assert "index.json" not in str(e.value) and "sha" not in str(e.value).lower()


def test_installed_and_newer_marks():
    with open(REAL_INDEX, "rb") as f:
        lib = catalog.parse_index(f.read())
    money = next(t for t in lib.tools if t.name == "money")
    assert catalog.card(money, installed="0.1.0")["newer"] is True
    same = catalog.card(money, installed="0.2.0")
    assert same["installed"] == "0.2.0" and same["newer"] is False
    assert catalog.card(money, installed="0.3.0")["newer"] is False
    assert catalog.card(money, installed="")["installed"] == ""


# ── 轉址、大小、逾時（get）────────────────────────────────────────────

def test_get_follows_only_github_https_redirects():
    blob = _pack_zip()
    web = _web([_entry("hello", "0.1.0", blob)], {"hello-0.1.0.synoxpack": blob})
    assert catalog.get(catalog.OFFICIAL_INDEX_URL, 1024, opener=web).startswith(b"{")
    assert web.calls[0] == catalog.OFFICIAL_INDEX_URL and len(web.calls) == 3


@pytest.mark.parametrize("location", [
    "https://evil.example.com/index.json",
    "http://objects.githubusercontent.com/x",                         # 不是 https
    "https://github.com/someone-else/repo/releases/download/v1/index.json",   # github.com 但不是這個工具庫
    "https://objects.githubusercontent.com:8443/x",                   # 奇怪的埠
    "https://user@objects.githubusercontent.com/x",
    "file:///etc/passwd",
])
def test_get_refuses_redirects_elsewhere(location):
    web = FakeWeb({catalog.OFFICIAL_INDEX_URL: (302, location, b"")})
    with pytest.raises(catalog.CatalogError):
        catalog.get(catalog.OFFICIAL_INDEX_URL, 1024, opener=web)
    assert len(web.calls) == 1                                         # 沒有跟過去


def test_get_refuses_a_start_url_outside_the_library():
    web = FakeWeb()
    for url in ("https://evil.example.com/index.json", "http://github.com/ChouYangEn0401/SYNOX_Libs/releases/x"):
        with pytest.raises(catalog.CatalogError):
            catalog.get(url, 1024, opener=web)
    assert web.calls == []


def test_get_stops_redirect_loops_and_oversize():
    loop = FakeWeb({catalog.OFFICIAL_INDEX_URL: (302, catalog.OFFICIAL_INDEX_URL, b"")})
    with pytest.raises(catalog.CatalogError):
        catalog.get(catalog.OFFICIAL_INDEX_URL, 1024, opener=loop)
    assert len(loop.calls) <= catalog.MAX_REDIRECTS + 1
    big = FakeWeb({catalog.OFFICIAL_INDEX_URL: (200, None, b"x" * 2000)})
    with pytest.raises(catalog.CatalogError):
        catalog.get(catalog.OFFICIAL_INDEX_URL, 1000, opener=big)


@pytest.mark.parametrize("error", [urllib.error.URLError("no route"), TimeoutError("slow"), OSError("reset")])
def test_get_turns_network_errors_into_the_offline_message(error):
    with pytest.raises(catalog.CatalogError) as e:
        catalog.get(catalog.OFFICIAL_INDEX_URL, 1024, opener=FakeWeb(fail=error))
    assert str(e.value) == catalog.TEXT["offline"]


def test_default_opener_does_not_follow_redirects_by_itself():
    """真的 opener 不自己跟轉址（每一跳都要經 get 的檢查）。"""
    import urllib.request
    handler = next(h for h in catalog._OPENER.handlers if isinstance(h, urllib.request.HTTPRedirectHandler))
    req = urllib.request.Request("https://github.com/x")
    assert handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example.com/") is None


# ── 網頁 API ─────────────────────────────────────────────────────────

def test_catalog_is_fetched_only_on_the_button(owner_client):
    bot, c = owner_client
    with open(REAL_INDEX, "rb") as f:
        real = f.read()
    web = FakeWeb({catalog.OFFICIAL_INDEX_URL: (302, f"{GH}download/v0.2.0/index.json", b""),
                   f"{GH}download/v0.2.0/index.json": (200, None, real)})
    ui_of(bot).catalog_opener = web
    c.get("/api/settings")
    c.get("/api/tools")
    c.get("/api/me")
    assert web.calls == []                                             # 打開設定頁不會連網
    assert c.raw("GET", "/api/packs/library")[0] in (404, 405) and web.calls == []
    status, data = c.post("/api/packs/library", {"url": "https://evil.example.com/index.json"})
    assert status == 200, data
    assert web.calls[0] == catalog.OFFICIAL_INDEX_URL and not any("evil" in u for u in web.calls)
    assert [t["name"] for t in data["tools"]][:5] == ["notes", "todo", "money", "calendar", "bullet"]   # 網站的順序
    tools = {t["name"]: t for t in data["tools"]}
    assert len(tools) == 9 and data["releases"] == catalog.RELEASES_PAGE and data["overview"] == catalog.OVERVIEW_URL
    assert tools["notes"]["installed"] == "0.1.0" and tools["notes"]["newer"] is True     # 測試的 notes 是 0.1.0
    assert tools["todo"]["installed"] == "" and tools["todo"]["download_url"].endswith("/v0.2.0/todo-0.1.1.synoxpack")


def test_catalog_offline_gives_plain_chinese_and_the_releases_link(owner_client):
    bot, c = owner_client
    ui_of(bot).catalog_opener = FakeWeb(fail=urllib.error.URLError("offline"))
    status, data = c.post("/api/packs/library")
    assert status == 502
    assert data["error"] == "連不到工具庫（可能沒有網路）。可以改用下面的『⬇ 下載』或到 GitHub 發佈頁手動下載。"
    assert data["releases"] == catalog.RELEASES_PAGE


def test_library_api_is_owner_only_and_needs_csrf(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    web = FakeWeb(fail=AssertionError("不該連網"))
    ui_of(bot).catalog_opener = web
    m = Client(ui_of(bot))
    m.login(OTHER_ID)
    assert m.post("/api/packs/library")[0] == 403
    assert m.post("/api/packs/library/install", {"name": "notes"})[0] == 403
    o = Client(ui_of(bot))
    o.login(owner)
    o.csrf = "wrong"
    assert o.post("/api/packs/library")[0] == 403
    assert o.post("/api/packs/library/install", {"name": "notes"})[0] == 403
    anon = Client(ui_of(bot))
    assert anon.post("/api/packs/library")[0] in (401, 403)
    assert web.calls == []


def test_install_downloads_checks_and_only_stages(make_bot, owner, tmp_path):
    user_packs = tmp_path / "userpacks"
    user_packs.mkdir()
    from synox.packs import loader
    bot = make_bot(pack_dirs=(str(user_packs),) + loader.PACK_DIRS)
    c = Client(ui_of(bot))
    c.login(owner)
    blob = _pack_zip()
    web = _web([_entry("hello", "0.1.0", blob)], {"hello-0.1.0.synoxpack": blob})
    ui_of(bot).catalog_opener = web
    status, summary = c.post("/api/packs/library/install", {"name": "hello", "url": "https://evil.example.com/x"})
    assert status == 200, summary
    assert summary["name"] == "hello" and summary["token"] and "scan" in summary          # 跟上傳同一份報告
    assert f"{GH}download/v0.3.0/hello-0.1.0.synoxpack" in web.calls and not any("evil" in u for u in web.calls)
    bot.say(owner, "/hello")
    assert "hi there" not in (bot.last(owner) or "")                       # 還沒按確認：沒裝
    assert [s["token"] for s in c.get("/api/packs/staged")[1]["staged"]] == [summary["token"]]
    status, data = c.post("/api/packs/install", {"token": summary["token"]})
    assert status == 200 and data["status"] == "loaded", data
    bot.say(owner, "/hello")
    assert bot.last(owner) == "hi there"
    # 工具庫出新版：同一條路 → 報告裡有「改了什麼」（升級要另外按確認）
    newer = _zip("hello", "0.2.0")
    ui_of(bot).catalog_opener = _web([_entry("hello", "0.2.0", newer)], {"hello-0.2.0.synoxpack": newer},
                                     library_version="0.4.0")
    status, data = c.post("/api/packs/library")
    assert status == 200 and data["tools"][0]["installed"] == "0.1.0" and data["tools"][0]["newer"] is True
    status, summary = c.post("/api/packs/library/install", {"name": "hello"})
    assert status == 200 and summary["upgrade"] and summary["version"] == "0.2.0", summary


def test_install_refuses_a_file_that_does_not_match_the_catalog(owner_client):
    bot, c = owner_client
    blob = _pack_zip()
    other = _pack_zip(name="howdy")
    web = _web([_entry("hello", "0.1.0", blob)], {"hello-0.1.0.synoxpack": other})
    ui_of(bot).catalog_opener = web
    status, data = c.post("/api/packs/library/install", {"name": "hello"})
    assert status == 400 and data["error"] == catalog.TEXT["mismatch"]
    assert "sha" not in data["error"].lower() and "index" not in data["error"].lower()
    assert _staged(bot) == []


def test_install_refuses_when_the_pack_inside_is_not_the_one_listed(owner_client):
    """目錄寫 hello、雜湊也對，但壓縮檔裡其實是 howdy：不留暫存、不給確認。"""
    bot, c = owner_client
    other = _pack_zip(name="howdy")
    ui_of(bot).catalog_opener = _web([_entry("hello", "0.1.0", other)], {"hello-0.1.0.synoxpack": other})
    status, data = c.post("/api/packs/library/install", {"name": "hello"})
    assert status == 400 and "howdy" not in json.dumps(c.get("/api/packs/staged")[1])
    assert _staged(bot) == []


def test_install_refuses_oversize_and_size_mismatch(owner_client):
    bot, c = owner_client
    blob = _pack_zip()
    ui_of(bot).catalog_opener = _web([_entry("hello", "0.1.0", blob, size=len(blob) + 1)],
                                     {"hello-0.1.0.synoxpack": blob})
    assert c.post("/api/packs/library/install", {"name": "hello"})[0] == 400
    huge = b"PK\x03\x04" + b"\0" * catalog.MAX_PACK
    ui_of(bot).catalog_opener = _web([_entry("hello", "0.1.0", blob)], {"hello-0.1.0.synoxpack": huge})
    status, data = c.post("/api/packs/library/install", {"name": "hello"})
    assert status == 400 and "MB" in data["error"]
    assert _staged(bot) == []


def test_install_unknown_name_and_offline(owner_client):
    bot, c = owner_client
    blob = _pack_zip()
    ui_of(bot).catalog_opener = _web([_entry("hello", "0.1.0", blob)], {"hello-0.1.0.synoxpack": blob})
    assert c.post("/api/packs/library/install", {"name": "nope"})[0] == 404
    assert c.post("/api/packs/library/install", {"name": "../hello"})[0] == 404
    ui_of(bot).catalog_opener = FakeWeb(fail=TimeoutError())
    status, data = c.post("/api/packs/library/install", {"name": "hello"})
    assert status == 502 and data["error"] == catalog.TEXT["offline"] and data["releases"] == catalog.RELEASES_PAGE


def test_install_refuses_redirect_to_another_host(owner_client):
    bot, c = owner_client
    blob = _pack_zip()
    web = _web([_entry("hello", "0.1.0", blob)], {})
    web.routes[f"{GH}download/v0.3.0/hello-0.1.0.synoxpack"] = (302, "https://evil.example.com/hello.synoxpack", b"")
    web.routes["https://evil.example.com/hello.synoxpack"] = (200, None, blob)
    ui_of(bot).catalog_opener = web
    assert c.post("/api/packs/library/install", {"name": "hello"})[0] in (400, 502)
    assert "https://evil.example.com/hello.synoxpack" not in web.calls
    assert _staged(bot) == []


# ── 畫面 ─────────────────────────────────────────────────────────────

def _app_html():
    with open(os.path.join(ROOT, "src", "synox", "web", "static", "app.html"), encoding="utf-8") as f:
        return f.read()


def _section(html, card_id):
    start = html.index(f'<div id="{card_id}"')
    return html[start:html.index("\n      </div>\n", start)]


def test_packs_tab_has_library_skills_and_sandbox_cards():
    html = _app_html()
    tab = html.split('data-tab="packs" role="tabpanel">')[1].split('<div class="tab-panel')[0]
    order = [tab.index(f'id="{i}"') for i in ("set-library", "set-skills", "set-install", "set-packs", "set-sandbox")]
    assert order == sorted(order)
    lib = _section(html, "set-library")
    assert "工具庫（官方）" in lib and 'id="lib-load"' in lib and "載入工具清單" in lib
    assert f'href="{catalog.OVERVIEW_URL}"' in lib and f'href="{catalog.RELEASES_PAGE}"' in lib    # 載入前的連結＝同一組常數
    skills = _section(html, "set-skills")
    assert "OpenClaw" in skills and "Hermes" in skills and "⏳ 尚未完成" in skills
    assert "<button" not in skills                                        # 沒有安裝鈕
    sandbox = _section(html, "set-sandbox")
    assert "⏳ 尚未完成" in sandbox and "disabled" in sandbox and 'type="checkbox"' in sandbox
    assert "Windows" in sandbox


def test_new_cards_and_texts_have_no_jargon_in_the_main_flow():
    html = _app_html()
    visible = "".join(_section(html, i) for i in ("set-library", "set-skills", "set-sandbox"))
    js = html.split("var LIB_TEXT = {")[1].split("};")[0]
    for word in ("sha256", "SHA", "index.json", "CSRF", "csrf", "雜湊", "hash"):
        assert word not in visible and word not in js, word
    for text in catalog.TEXT.values():
        for word in ("sha256", "index.json", "CSRF", "雜湊"):
            assert word not in text, (word, text)


def test_library_ui_never_builds_urls_from_input_and_uses_text_content():
    html = _app_html()
    lib_js = html.split("// ── 工具庫（官方）")[1].split("// ── 工具庫 end")[0]
    assert "innerHTML" not in lib_js
    assert "/api/packs/library/install" in lib_js and "showReview(" in lib_js       # 同一份報告、同一個確認鈕
    assert "/api/packs/install" not in lib_js                                     # 不自己按確認
    assert "https://" not in lib_js                                               # 連結一律用伺服器給的（寫死在 catalog.py）
