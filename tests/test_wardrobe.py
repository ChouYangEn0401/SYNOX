"""設定 → 🎨 外觀：衣櫃（SYNOX 衣櫃，官方清單裡 kind=theme 的外觀包）與背景（slot chat.background）。

- 衣櫃跟工具庫是同一份官方清單、同一個寫死的網址、同一套安全的抓法；只在按「看衣櫃」時連網。
- 外觀包不出現在「功能與安裝」的工具清單；工具不出現在衣櫃。
- 安裝走同一條路：下載 → 大小、雜湊對清單 → admin.stage → 報告 → 人按確認；清單說是外觀包，裡面就要是外觀包。
- 清單裡還沒有外觀包：回空的，網頁說「衣櫃還沒上架，先到網頁看看」。
- 背景：跟著外觀／不要／純色／花紋／自己貼 SVG；自己選的蓋過外觀包的；不收外部網址。
測試一律用假的網路（FakeWeb），不連網、不開瀏覽器。
"""

import json
import os
import re

import pytest

from isdtelekit.users.roles import BasicRoles

from synox.packs import catalog
from synox.theme import appearance, contract
from synox.web import server as web_server

from conftest import OTHER_ID
from test_pack_library import GH, REAL_INDEX, FakeWeb, _entry, _index, _staged, _web
from test_theme import _install, _page, _zip, theme_bot  # noqa: F401  (theme_bot 是 fixture)
from test_web import Client, _pack_zip, owner_client, ui_of  # noqa: F401  (owner_client 是 fixture)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATIC = os.path.join(ROOT, "src", "synox", "web", "static")


def _app_html():
    with open(os.path.join(STATIC, "app.html"), encoding="utf-8") as f:
        return f.read()


def _theme_entry(name, version, blob, series="", **over):
    """衣櫃的一筆（跟 SYNOX_Libs scripts/build_costumes.index_entry 同一個樣子）。"""
    return _entry(name, version, blob, kind="theme", category="衣櫃／外觀", collection="wardrobe", series=series,
                  title=over.pop("title", name), line=over.pop("line", "一句話"), capabilities=[], **over)


def _wardrobe_index(entries, library_version="0.3.0"):
    raw = json.loads(_index(entries, library_version))
    raw["collections"] = {"wardrobe": {"title": "SYNOX 衣櫃", "category": "衣櫃／外觀", "summary": "整套外觀",
                                       "packs": [e["name"] for e in entries if e.get("kind") == "theme"]}}
    return json.dumps(raw).encode("utf-8")


def _mixed_web(entries, files, library_version="0.3.0"):
    """跟 test_pack_library._web 一樣（轉址兩次），清單多了 collections.wardrobe。"""
    web = _web(entries, files, library_version)
    index_url = next(u for u in web.routes if u.endswith("&f=index"))
    web.routes[index_url] = (200, None, _wardrobe_index(entries, library_version))
    return web


# ── 清單（純函式）────────────────────────────────────────────────────

def test_themes_are_split_from_tools_and_read_into_wardrobe_cards():
    tool = _pack_zip()
    lantern = _zip()
    lib = catalog.parse_index(_wardrobe_index([
        _entry("hello", "0.1.0", tool),
        _theme_entry("costume-b-lantern", "1.0.0", lantern, series="B", title="提燈", line="幫你顧家的一盞小燈"),
        _theme_entry("costume-a-bubble", "1.0.0", lantern, series="A",
                     swatches=["#F5F3EF", "#0a7c70", "url(https://evil.example/x.png)", "red", "#123"]),
    ]))
    assert [t.name for t in lib.themes] == ["costume-b-lantern", "costume-a-bubble"]
    assert [c["name"] for c in catalog.cards(lib, {})] == ["hello"]                       # 工具清單不列外觀包
    cards = catalog.wardrobe_cards(lib, {"costume-b-lantern": "0.9.0"})
    assert [c["name"] for c in cards] == ["costume-a-bubble", "costume-b-lantern"]       # 照系列字母
    bubble, lantern_card = cards
    assert bubble["swatches"] == ["#f5f3ef", "#0a7c70", "#123"]                          # 只收 #hex，不收網址
    assert lantern_card["swatches"] == [] and lantern_card["letter"] == "B"              # 沒有預覽＝字母方塊
    assert lantern_card["title"] == "提燈" and lantern_card["line"] == "幫你顧家的一盞小燈"
    assert lantern_card["installed"] == "0.9.0" and lantern_card["newer"] is True
    assert bubble["installed"] == "" and bubble["newer"] is False
    assert catalog.wardrobe_info(lib) == {"title": "SYNOX 衣櫃", "summary": "整套外觀"}
    for c in cards:                                                                       # 卡片裡沒有任何網址
        assert "http" not in json.dumps(c)


def test_entries_without_kind_theme_are_tools_and_series_is_one_letter():
    blob = _pack_zip()
    lib = catalog.parse_index(_index([_entry("hello", "0.1.0", blob, series="B", swatches=["#fff"])]))
    assert lib.themes == [] and lib.tools[0].series == "" and lib.tools[0].swatches == []
    lib = catalog.parse_index(_index([_theme_entry("costume-x", "1.0.0", blob, series="<b>")]))
    card = catalog.wardrobe_cards(lib, {})[0]
    assert card["letter"] == "C" and card["swatches"] == []                               # 不像字母＝用名字的第一個字


def test_the_real_pinned_index_has_no_themes_yet():
    with open(REAL_INDEX, "rb") as f:
        lib = catalog.parse_index(f.read())
    assert lib.themes == [] and catalog.wardrobe_cards(lib, {}) == [] and len(catalog.cards(lib, {})) == 9


def test_wardrobe_page_is_one_constant():
    assert catalog.WARDROBE_URL == "https://claude.ai/artifact/USzGNERZ2477E7XzPaPCsR"
    assert catalog.TEXT["wardrobe_empty"] == "衣櫃還沒上架，先到網頁看看"


# ── /api/packs/wardrobe ──────────────────────────────────────────────

def test_wardrobe_is_fetched_only_on_the_button_and_lists_only_themes(owner_client):
    bot, c = owner_client
    tool, lantern = _pack_zip(), _zip()
    entries = [_entry("hello", "0.1.0", tool), _theme_entry("costume-b-lantern", "1.0.0", lantern, series="B")]
    web = _mixed_web(entries, {})
    ui_of(bot).catalog_opener = web
    c.get("/api/settings")
    c.get("/api/appearance")
    assert web.calls == []                                                 # 打開設定、外觀都不連網
    assert c.raw("GET", "/api/packs/wardrobe")[0] in (404, 405) and web.calls == []
    status, data = c.post("/api/packs/wardrobe", {"url": "https://evil.example.com/index.json"})
    assert status == 200, data
    assert web.calls[0] == catalog.OFFICIAL_INDEX_URL and not any("evil" in u for u in web.calls)
    assert [t["name"] for t in data["themes"]] == ["costume-b-lantern"] and data["empty"] == ""
    assert data["page"] == catalog.WARDROBE_URL and data["title"] == "SYNOX 衣櫃"
    status, lib = c.post("/api/packs/library")
    assert status == 200 and [t["name"] for t in lib["tools"]] == ["hello"]           # 工具清單沒有外觀包


def test_wardrobe_empty_index_says_not_on_shelves_yet(owner_client):
    bot, c = owner_client
    with open(REAL_INDEX, "rb") as f:
        real = f.read()
    ui_of(bot).catalog_opener = FakeWeb({catalog.OFFICIAL_INDEX_URL: (200, None, real)})
    status, data = c.post("/api/packs/wardrobe")
    assert status == 200 and data["themes"] == []
    assert data["empty"] == "衣櫃還沒上架，先到網頁看看" and data["page"] == catalog.WARDROBE_URL


def test_wardrobe_offline_and_permissions(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    web = FakeWeb(fail=AssertionError("不該連網"))
    ui_of(bot).catalog_opener = web
    m = Client(ui_of(bot))
    m.login(OTHER_ID)
    assert m.post("/api/packs/wardrobe")[0] == 403
    o = Client(ui_of(bot))
    o.login(owner)
    o.csrf = "wrong"
    assert o.post("/api/packs/wardrobe")[0] == 403
    assert Client(ui_of(bot)).post("/api/packs/wardrobe")[0] in (401, 403)
    assert web.calls == []
    import urllib.error
    o = Client(ui_of(bot))
    o.login(owner)
    ui_of(bot).catalog_opener = FakeWeb(fail=urllib.error.URLError("offline"))
    status, data = o.post("/api/packs/wardrobe")
    assert status == 502 and data["error"] == catalog.TEXT["offline"]


def test_install_from_wardrobe_goes_through_report_confirm_then_apply(theme_bot, owner):
    bot = theme_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    blob = _zip()
    entries = [_theme_entry("sample-lantern", "1.0.0", blob, series="B")]
    web = _mixed_web(entries, {"sample-lantern-1.0.0.synoxpack": blob})
    ui_of(bot).catalog_opener = web
    status, summary = c.post("/api/packs/library/install", {"name": "sample-lantern"})
    assert status == 200, summary
    assert summary["kind"] == "theme" and summary["token"] and summary["tier"]["tier"] == "T0"     # 同一份報告
    assert f"{GH}download/v0.3.0/sample-lantern-1.0.0.synoxpack" in web.calls
    assert c.get("/api/appearance")[1]["themes"] == []                     # 還沒按確認：沒裝
    status, data = c.post("/api/packs/install", {"token": summary["token"]})
    assert status == 200 and data["kind"] == "theme" and data["status"] == "loaded", data
    status, data = c.post("/api/packs/wardrobe")
    assert data["themes"][0]["installed"] == "1.0.0" and data["themes"][0]["newer"] is False
    assert "data-skin" not in _page(c)[0]                                  # 裝好不會自己套用
    assert c.post("/api/appearance", {"theme": "sample-lantern"})[0] == 200
    assert 'data-skin="sample-lantern"' in _page(c)[0]


def test_install_refuses_when_the_listed_kind_does_not_match(owner_client):
    bot, c = owner_client
    tool = _pack_zip()
    # 清單說是外觀包，壓縮檔裡其實是有程式的工具：不留暫存、不給確認
    ui_of(bot).catalog_opener = _mixed_web([_theme_entry("hello", "0.1.0", tool)], {"hello-0.1.0.synoxpack": tool})
    status, data = c.post("/api/packs/library/install", {"name": "hello"})
    assert status == 400 and data["error"] == catalog.TEXT["not_listed"]
    assert _staged(bot) == []


def test_install_refuses_a_theme_listed_as_a_tool(theme_bot, owner):
    bot = theme_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    blob = _zip()
    ui_of(bot).catalog_opener = _web([_entry("sample-lantern", "1.0.0", blob)], {"sample-lantern-1.0.0.synoxpack": blob})
    status, data = c.post("/api/packs/library/install", {"name": "sample-lantern"})
    assert status == 400 and data["error"] == catalog.TEXT["not_listed"]
    assert _staged(bot) == []


# ── 畫面：衣櫃 ───────────────────────────────────────────────────────

def _look_tab(html):
    return html.split('data-tab="appearance" role="tabpanel">')[1].split('<div class="tab-panel')[0]


def test_appearance_tab_has_wardrobe_and_background_cards_in_order():
    tab = _look_tab(_app_html())
    order = [tab.index(f'id="{i}"') for i in ("set-look", "set-wardrobe", "set-bg", "set-custom", "set-mode")]
    assert order == sorted(order)
    wd = tab[tab.index('id="set-wardrobe"'):tab.index('id="set-bg"')]
    assert "衣櫃" in wd and 'id="wd-load"' in wd and "看衣櫃（要連到網路）" in wd
    assert f'href="{catalog.WARDROBE_URL}"' in wd and "到衣櫃網頁看完整預覽" in wd
    bg = tab[tab.index('id="set-bg"'):tab.index('id="set-custom"')]
    for kind in contract.BACKGROUND_KINDS:
        assert f'name="bg-kind" value="{kind}"' in bg, kind


def test_wardrobe_ui_reuses_the_install_flow_and_builds_no_urls():
    html = _app_html()
    js = html.split("// ── 外觀 → 衣櫃（SYNOX 衣櫃）")[1].split("// ── 衣櫃 end")[0]
    assert "innerHTML" not in js and "https://" not in js                   # 連結一律用伺服器給的（寫死在 catalog.py）
    assert '"/api/packs/wardrobe"' in js and '"/api/packs/library/install"' in js and "showReview(" in js
    assert "/api/packs/install\"" not in js                                  # 不自己按確認
    assert "applyLook(" in js                                                 # 裝好之後「套用」照原本的
    assert "衣櫃還沒上架，先到網頁看看" in js
    for word in ("已安裝", "有新版", "安裝", "套用"):
        assert word in js, word
    for word in ("sha256", "SHA", "index.json", "雜湊"):
        assert word not in js, word


def test_wardrobe_is_not_shown_in_the_tool_library_js():
    html = _app_html()
    lib_js = html.split("// ── 工具庫（官方）")[1].split("// ── 工具庫 end")[0]
    assert "/api/packs/wardrobe" not in lib_js


# ── 背景 ─────────────────────────────────────────────────────────────

def test_background_slot_is_in_the_contract_and_svg_only():
    assert contract.SLOTS["chat.background"][2] == ("svg",) and contract.slot_name("chat.background") == "chat.background"
    assert contract.BACKGROUND_KINDS == ("theme", "none", "color", "pattern", "svg")
    assert set(web_server.CHAT_BG_VALUES) == {"none", "color"} | set(contract.BACKGROUND_PATTERNS)


def test_builtin_patterns_are_css_only_and_token_based():
    html = _app_html()
    css = html.split("</style>")[0]
    for name in contract.BACKGROUND_PATTERNS:
        rule = re.search(r':root\[data-chat-bg="' + name + r'"\] \.chat-bg, \.bg-tile\.' + name + r' \{(.*?)\}', css, re.DOTALL)
        assert rule, name
        assert "url(" not in rule.group(1) and "var(--" in rule.group(1), name
    assert ':root[data-chat-bg="none"] .chat-bg { display: none; }' in css
    assert "var(--chat-bg-color" in css
    bg = re.search(r"\.chat-bg \{(.*?)\}", css, re.DOTALL).group(1)
    assert "pointer-events: none" in bg and "z-index: -1" in bg


def test_slots_js_pauses_the_background_animation_for_reduced_motion():
    with open(os.path.join(STATIC, "slots.js"), encoding="utf-8") as f:
        js = f.read()
    assert "prefers-reduced-motion: reduce" in js and "pauseAnimations" in js and '"chat.background"' in js


def test_background_choices_save_render_and_validate(theme_bot, owner):
    bot = theme_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    look = c.get("/api/appearance")[1]
    assert look["background"] == {"kind": "theme"}
    assert [p["name"] for p in look["patterns"]] == list(contract.BACKGROUND_PATTERNS)
    html = _page(c)[0]
    assert "data-chat-bg" not in html.split(">", 2)[1] and 'data-slot-src="chat.background"' not in html
    status, data = c.post("/api/appearance", {"background": {"kind": "pattern", "pattern": "grid"}})
    assert status == 200 and data["background"] == {"kind": "pattern", "pattern": "grid"}
    assert '<html lang="zh-Hant" data-chat-bg="grid">' in _page(c)[0]
    assert c.post("/api/appearance", {"background": {"kind": "color", "color": "#AA3366"}})[0] == 200
    html = _page(c)[0]
    assert 'data-chat-bg="color"' in html and ":root { --chat-bg-color: #aa3366; }" in html
    for bad in ({"kind": "color", "color": "red; background: url(https://evil.example/x)"},
                {"kind": "color", "color": "url(https://evil.example/x.png)"},
                {"kind": "pattern", "pattern": "../x"}, {"kind": "image", "url": "https://evil.example/x.png"},
                {"kind": "svg"}, "dots"):
        status, data = c.post("/api/appearance", {"background": bad})
        assert status == 400, bad
    assert c.get("/api/appearance")[1]["background"] == {"kind": "color", "color": "#aa3366"}      # 沒有被改掉
    assert c.post("/api/appearance", {"background": {"kind": "none"}})[0] == 200
    assert 'data-chat-bg="none"' in _page(c)[0]


def test_theme_background_is_used_unless_the_person_chose_their_own(theme_bot, owner):
    bot = theme_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    _install(c)
    c.post("/api/appearance", {"theme": "sample-lantern"})
    html = _page(c)[0]
    assert '<template data-slot-src="chat.background"><svg' in html and "data-chat-bg" not in html.split(">", 2)[1]
    c.post("/api/appearance", {"background": {"kind": "pattern", "pattern": "dots"}})
    html = _page(c)[0]
    assert 'data-slot-src="chat.background"' not in html and 'data-chat-bg="dots"' in html     # 自己選的蓋過外觀包的
    c.post("/api/appearance", {"background": {"kind": "none"}})
    assert 'data-slot-src="chat.background"' not in _page(c)[0]
    c.post("/api/appearance", {"background": {"kind": "theme"}})
    assert 'data-slot-src="chat.background"' in _page(c)[0]


def test_pasted_background_svg_is_sanitized_and_wins(theme_bot, owner):
    bot = theme_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    _install(c)
    c.post("/api/appearance", {"theme": "sample-lantern"})
    status, data = c.post("/api/appearance/custom", {"slot": "chat.background",
                                                     "text": '<svg><image href="https://evil.example/x.png"/></svg>'})
    assert status == 400                                                    # 外面的圖片不收
    status, data = c.post("/api/appearance/custom", {"slot": "chat.background",
                                                     "text": '<div>not svg</div>'})
    assert status == 400                                                    # 背景只收 SVG
    mine = '<svg viewBox="0 0 8 8"><circle class="mine" cx="4" cy="4" r="2"/></svg>'
    assert c.post("/api/appearance/custom", {"slot": "chat.background", "text": mine})[0] == 200
    look = c.get("/api/appearance")[1]
    assert look["background"] == {"kind": "svg"}
    html = _page(c)[0]
    assert '<template data-slot-src="chat.background"><svg viewBox="0 0 8 8">' in html
    c.post("/api/appearance", {"background": {"kind": "pattern", "pattern": "glow"}})
    assert 'data-slot-src="chat.background"' not in _page(c)[0]                         # 貼的還在，但沒在用
    assert c.post("/api/appearance", {"background": {"kind": "svg"}})[0] == 200
    assert '<template data-slot-src="chat.background"><svg viewBox="0 0 8 8">' in _page(c)[0]
    assert c.post("/api/appearance/custom", {"slot": "chat.background", "text": ""})[0] == 200   # 拿掉＝回到跟著外觀
    assert c.get("/api/appearance")[1]["background"] == {"kind": "theme"}
    assert '<template data-slot-src="chat.background"><svg viewBox="0 0 400 300"' in _page(c)[0]


def test_background_is_per_person_in_server_mode(theme_bot, owner):
    bot = theme_bot(raw={"mode": "server"})
    ui = ui_of(bot)
    c = Client(ui)
    c.login(owner)
    c.post("/api/appearance", {"background": {"kind": "pattern", "pattern": "stripes"}})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    m = Client(ui)
    m.login(OTHER_ID)
    assert 'data-chat-bg="stripes"' in _page(m)[0]                          # 沒選過＝跟擁有者一樣
    assert m.post("/api/appearance", {"background": {"kind": "none"}})[0] == 200
    assert 'data-chat-bg="none"' in _page(m)[0] and 'data-chat-bg="stripes"' in _page(c)[0]


def test_stored_background_garbage_is_ignored(theme_bot, owner):
    bot = theme_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    ui_of(bot).prefs.set(owner, appearance.PREF_KEY, {"background": {"kind": "color", "color": "x</style><script>"}})
    html = _page(c)[0]
    assert "x</style><script>" not in html and ":root { --chat-bg-color" not in html and "data-chat-bg" not in html.split(">", 2)[1]
    assert appearance.clean_background({"kind": "pattern", "pattern": "dots"}) == {"kind": "pattern", "pattern": "dots"}
    assert appearance.clean_background({"kind": "color", "color": "#abc"}) == {"kind": "color", "color": "#abc"}
    assert appearance.clean_background({"kind": "color"}) is None and appearance.clean_background("none") is None


def test_render_app_only_accepts_known_background_values():
    assert 'data-chat-bg="dots"' in web_server.render_app("n", chat_bg="dots")
    assert "data-chat-bg" not in web_server.render_app("n", chat_bg='x" onload="y').split(">", 2)[1]
