"""網頁「工具」頁：群組排版（每個人自己的）、工具的說明與參數表單資訊（pack.json 的檢查在 test_pack_docs.py）。

只用 tmp 裡自己做的假 pack（不依賴內建的 notes／money／remind），直接呼叫 WebUI.handle（不開埠、不連網）。
"""

import json
import os
import re

import pytest

from isdtelekit.users.roles import BasicRoles

from synox.web import server as web_server
from synox.web import toolpage

from conftest import OTHER_ID
from test_web import Client, ui_of

SKILL = "---\nname: {name}\ndescription: 使用者想{what}的時候使用。\n---\n\n# {name}\n"

PY_PACK = '''from isdtelekit.core.registry import DANGER, WRITE, Field
from synox.packs import kit


def install(app, pack):
    def add(api, chat_id, user, values):
        api.send_message(chat_id, "記下了：" + values["text"] + "／" + values.get("tag", "") + "／" + values.get("n", "-"))

    kit.command(pack.group, "add", add, "記一則", default=True, effect=WRITE,
                fields=[Field("text", "內容", required=True), Field("tag", "標籤", default="一般"),
                        Field("n", "數量", check=kit.number), Field("at", "時間", check=kit.hhmm)])

    def wipe(api, chat_id, user, values):
        api.send_message(chat_id, "全刪了")

    kit.command(pack.group, "wipe", wipe, "全部刪掉", effect=DANGER)
'''


def _write(folder, rel, text):
    os.makedirs(os.path.dirname(os.path.join(folder, rel)), exist_ok=True)
    with open(os.path.join(folder, rel), "w", encoding="utf-8") as f:
        f.write(text)


def make_packs(base):
    """兩個假 pack：python 的 memo（category 生活）、cli 的 calc（沒寫 category＝未分類；欄位有 help／default）。"""
    memo = os.path.join(base, "memo")
    _write(memo, "pack.json", json.dumps({
        "name": "memo", "title": "📝 備忘", "summary": "記一則、全部刪掉", "version": "0.1.0", "kind": "python",
        "category": "生活", "access": "member", "surfaces": ["dm"], "data": "user", "storage": "vault",
        "python": {"module": "pack"}, "skill": "SKILL.md"}, ensure_ascii=False))
    _write(memo, "SKILL.md", SKILL.format(name="memo", what="記事情"))
    _write(memo, "pack.py", PY_PACK)
    calc = os.path.join(base, "calc")
    _write(calc, "pack.json", json.dumps({
        "name": "calc", "title": "🧮 計算", "summary": "算小費", "version": "0.1.0", "kind": "cli",
        "access": "member", "data": "none", "capabilities": [], "skill": "SKILL.md",
        "cli": {"argv": ["{python}", "./tool.py"], "cwd": ".", "commands": [
            {"name": "tip", "effect": "READ", "summary": "算含小費的總額", "default": True,
             "argv": ["tip", "--amount={amount}", "--percent={percent}", "--round={round}", "--style={style}"],
             "fields": [{"name": "amount", "ask": "帳單金額", "kind": "number", "required": True,
                         "help": "只放數字，例如 1200"},
                        {"name": "percent", "ask": "小費幾 %", "kind": "int", "default": 10},
                        {"name": "round", "ask": "要不要進位", "kind": "bool", "default": False},
                        {"name": "style", "ask": "語氣", "kind": "choice", "choices": ["casual", "formal"]}]}]}},
        ensure_ascii=False))
    _write(calc, "SKILL.md", SKILL.format(name="calc", what="算錢"))
    _write(calc, "tool.py", "print('{}')\n")
    return [memo, calc]


@pytest.fixture
def tools_bot(make_bot, tmp_path):
    def factory(raw=None):
        return make_bot(raw=raw, pack_dirs=make_packs(str(tmp_path / "packs")))
    return factory


def owner_of(bot, owner):
    c = Client(ui_of(bot))
    c.login(owner)
    return c


# ── 排版的規則（純函式） ──────────────────────────────────────────────

def test_effective_layout_follows_pack_suggestions_until_the_user_arranges():
    tools = [("memo", "生活"), ("calc", ""), ("_basics", toolpage.BUILTIN), ("agent", toolpage.BUILTIN),
             ("money", "生活")]
    lay = toolpage.effective(None, tools)
    assert [(g["title"], g["tools"], g["auto"]) for g in lay["groups"]] == [
        ("生活", ["memo", "money"], True), ("未分類", ["calc"], True), ("內建", ["_basics", "agent"], True)]
    assert lay["custom"] is False
    stored = {"groups": [{"id": "g1", "title": "常用", "tools": ["calc", "money", "gone"]},
                         {"id": "g2", "title": "空的", "tools": []}]}
    lay = toolpage.effective(stored, tools)
    assert [(g["title"], g["tools"]) for g in lay["groups"]] == [
        ("常用", ["calc", "money"]), ("空的", []), ("生活", ["memo"]), ("內建", ["_basics", "agent"])]
    assert lay["custom"] is True and "gone" not in json.dumps(lay)        # 看不到的不出現
    # 使用者自己的群組剛好跟建議同名：沒排過的工具放進去，不另開一個
    lay = toolpage.effective({"groups": [{"id": "x", "title": "生活", "tools": []}]}, tools)
    assert lay["groups"][0] == {"id": "x", "title": "生活", "tools": ["memo", "money"], "auto": False}
    # 存檔壞了：當作沒排過，不丟錯
    assert toolpage.effective({"groups": "壞掉"}, tools)["custom"] is False


@pytest.mark.parametrize("data, why", [
    ({}, "groups"),
    ({"groups": [{"id": "Bad Id", "title": "a", "tools": []}]}, "id"),
    ({"groups": [{"id": "a", "title": "", "tools": []}]}, "群組名稱"),
    ({"groups": [{"id": "a", "title": "第一行\n第二行", "tools": []}]}, "換行"),
    ({"groups": [{"id": "a", "title": "x" * 25, "tools": []}]}, "太長"),
    ({"groups": [{"id": "a", "title": "同名", "tools": []}, {"id": "b", "title": "同名", "tools": []}]}, "重複"),
    ({"groups": [{"id": "a", "title": "x", "tools": []}, {"id": "a", "title": "y", "tools": []}]}, "重複"),
    ({"groups": [{"id": "a", "title": "x", "tools": ["../etc"]}]}, "tools"),
    ({"groups": [{"id": f"g{i}", "title": f"g{i}", "tools": []} for i in range(31)]}, "最多"),
])
def test_parse_layout_rejects_bad_input(data, why):
    with pytest.raises(toolpage.LayoutError, match=why):
        toolpage.parse_layout(data)


def test_parse_layout_keeps_a_tool_in_one_group_only():
    lay = toolpage.parse_layout({"groups": [{"id": "a", "title": " A ", "tools": ["memo", "memo"]},
                                            {"id": "b", "title": "B", "tools": ["memo", "calc"]}]})
    assert lay["groups"] == [{"id": "a", "title": "A", "tools": ["memo"]}, {"id": "b", "title": "B", "tools": ["calc"]}]


# ── /api/tools：說明與參數表單 ───────────────────────────────────────

def test_tools_api_gives_descriptions_fields_and_default_layout(tools_bot, owner):
    bot = tools_bot()
    status, data = owner_of(bot, owner).get("/api/tools")
    assert status == 200
    packs = {p["id"]: p for p in data["packs"]}
    assert set(packs) == {"memo", "calc"}                                  # 只有 tmp 的假 pack
    memo, calc = packs["memo"], packs["calc"]
    assert memo["category"] == "生活" and calc["category"] == ""
    assert memo["description"] == "使用者想記事情的時候使用。"
    cmds = {c["command"]: c for c in memo["commands"]}
    assert cmds["/memo_wipe"]["effect"] == "danger" and cmds["/memo"]["default"] is True
    fields = {f["name"]: f for f in cmds["/memo"]["fields"]}
    assert fields["text"] == {"name": "text", "label": "內容", "required": True, "kind": "text", "default": ""}
    assert fields["tag"]["default"] == "一般" and fields["n"]["kind"] == "number"
    assert fields["at"]["help"] == "時間，例如 08:00"
    tip = {f["name"]: f for f in calc["commands"][0]["fields"]}
    assert tip["amount"]["help"] == "只放數字，例如 1200" and tip["amount"]["kind"] == "number"
    assert tip["percent"]["default"] == "10" and tip["round"]["default"] == "false"     # 布林寫成 true／false
    assert tip["style"]["choices"] == ["casual", "formal"] and tip["style"]["kind"] == "choice"
    titles = [g["title"] for g in data["layout"]["groups"]]
    assert titles[0] == "生活" and titles[-2:] == ["未分類", "內建"]
    builtin = data["layout"]["groups"][-1]["tools"]
    assert toolpage.BASICS_ID in builtin and all(g["id"] in builtin for g in data["groups"])


def test_form_text_runs_through_the_same_dispatcher(tools_bot, owner):
    """表單送出的是 key=value（kit.parse_args 收）；跟預設值一樣的不送也會補上。"""
    bot = tools_bot()
    c = owner_of(bot, owner)
    c.say("tools", "/memo text=買牛奶 兩瓶 n=3")
    assert any(m["text"] == "記下了：買牛奶 兩瓶／一般／3" for m in c.events("tools"))
    c.say("tools", "/memo n=abc text=x")
    assert any("數量要是數字" in m["text"] for m in c.events("tools"))


# ── 排版的存取（每個人自己的） ───────────────────────────────────────

def test_save_layout_needs_csrf_and_is_encrypted_per_user(tools_bot, owner):
    bot = tools_bot()
    c = owner_of(bot, owner)
    body = {"groups": [{"id": "g1", "title": "每天用", "tools": ["calc", "memo"]}]}
    status, _h, _b = c.raw("POST", "/api/tools/layout", json.dumps(body).encode(), headers={"X-SYNOX-CSRF": "nope"})
    assert status == 403
    status, data = c.post("/api/tools/layout", body)
    assert status == 200 and data["ok"]
    assert [(g["title"], g["tools"]) for g in data["layout"]["groups"]][0] == ("每天用", ["calc", "memo"])
    assert c.get("/api/tools")[1]["layout"]["custom"] is True
    folder = os.path.join(bot.app.config.data_dir, "web_prefs")
    files = os.listdir(folder)
    assert files == [f"{owner}.json.enc"]                                  # 保管箱：密文
    with open(os.path.join(folder, files[0]), "rb") as f:
        assert "每天用".encode() not in f.read()
    for pack in ("memo", "calc"):                                           # 不寫進 pack 資料夾
        assert not any("layout" in n or "prefs" in n for n in os.listdir(
            os.path.dirname(next(p.manifest.folder for p in bot.app.extras["synox_packs"] if p.name == pack))))
    status, data = c.post("/api/tools/layout", {"groups": [{"id": "g1", "title": "", "tools": []}]})
    assert status == 400 and "群組名稱" in data["error"]
    status, data = c.post("/api/tools/layout", {"reset": True})
    assert status == 200 and data["layout"]["custom"] is False and data["layout"]["groups"][0]["title"] == "生活"


def test_owner_and_member_layouts_are_separate_and_hidden_tools_stay_put(tools_bot, owner):
    bot = tools_bot(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    o, m = owner_of(bot, owner), Client(ui_of(bot))
    m.login(OTHER_ID)
    member_sees = [tid for g in m.get("/api/tools")[1]["layout"]["groups"] for tid in g["tools"]]
    assert "memo" not in member_sees                       # 伺服器版：沒鎖的第三方 python pack 只給擁有者（PERM-8）
    status, _ = m.post("/api/tools/layout", {"groups": [{"id": "mine", "title": "我的", "tools": member_sees}]})
    assert status == 200
    assert m.get("/api/tools")[1]["layout"]["groups"][0]["title"] == "我的"
    assert all(g["title"] != "我的" for g in o.get("/api/tools")[1]["layout"]["groups"])   # 擁有者的沒變
    # 擁有者把 memo 排進「工作」；之後 memo 暫時看不到（例如 pack 沒載入），再存一次也不會弄丟它的位置
    o.post("/api/tools/layout", {"groups": [{"id": "w", "title": "工作", "tools": ["memo", "calc"]}]})
    ui = ui_of(bot)
    owner_user = bot.app.users.get_or_create(owner)
    real = ui.tools
    ui.tools = lambda user: {**real(user), "packs": [p for p in real(user)["packs"] if p["id"] != "memo"]}
    try:
        status, _h, _b = ui.save_layout(owner_user, {"groups": [{"id": "w", "title": "工作", "tools": ["calc"]}]})
    finally:
        del ui.tools
    assert status == 200
    assert o.get("/api/tools")[1]["layout"]["groups"][0]["tools"] == ["calc", "memo"]


def test_unreadable_layout_is_not_overwritten(tools_bot, owner):
    bot = tools_bot()
    c = owner_of(bot, owner)
    c.post("/api/tools/layout", {"groups": [{"id": "g1", "title": "A", "tools": []}]})
    ui = ui_of(bot)
    path = ui.prefs.path(owner)
    with open(path, "wb") as f:
        f.write(b"not a vault blob")
    status, data = c.get("/api/tools")
    assert status == 200 and "layout_error" in data and data["layout"]["custom"] is False
    status, data = c.post("/api/tools/layout", {"groups": [{"id": "g2", "title": "B", "tools": []}]})
    assert status == 409
    with open(path, "rb") as f:
        assert f.read() == b"not a vault blob"


# ── 頁面：tools.css／tools.js 放進 app.html ──────────────────────────

def test_app_page_inlines_tools_files_with_the_nonce(tools_bot, owner):
    bot = tools_bot()
    c = owner_of(bot, owner)
    status, headers, body = c.raw("GET", "/")
    html = body.decode("utf-8")
    nonce = re.search(r"script-src 'nonce-([^']+)'", dict(headers)["Content-Security-Policy"]).group(1)
    assert status == 200 and "<!-- include:" not in html
    assert f'<style nonce="{nonce}">\n  /* ── 工具頁' in html and "window.SynoxTools" in html
    assert html.count(f'<script nonce="{nonce}">') == 3 and 'id="tools-root"' in html   # inline app script + tools.js + control.js


def test_render_app_refuses_unknown_includes(monkeypatch, tmp_path):
    (tmp_path / "app.html").write_text("<!-- include: evil.js -->", encoding="utf-8")
    monkeypatch.setattr(web_server, "STATIC", str(tmp_path))
    with pytest.raises(ValueError):
        web_server.render_app("n")


def test_tools_assets_use_tokens_and_no_inline_html():
    static = os.path.join(os.path.dirname(web_server.__file__), "static")
    with open(os.path.join(static, "tools.css"), encoding="utf-8") as f:
        css = f.read()
    with open(os.path.join(static, "tools.js"), encoding="utf-8") as f:
        js = f.read()
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b", css) == [], "顏色寫進 app.html 的 token"
    assert "@media (max-width: 760px)" in css
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "onclick=", "http://",
                "https://"):
        assert bad not in js, bad
