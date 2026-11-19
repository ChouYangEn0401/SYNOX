"""外觀的顏色只宣告一次、舊外觀包遇到新 token 不會壞、套用檢查（ADR 0042）。

- 單一來源：SYNOX 的顏色只在 synox/theme/contract.py（DEFAULTS、FIXED）；app.html 的 :root、登入小頁、提醒視窗、
  預覽頁都從那裡拿；還留著的靜態副本（工具服務的 kit.css、手機入口）跟它對得上
- 向前相容：只給舊 token 的外觀包照裝、照套用，沒給的都有值（SYNOX 的預設）；外觀包比 SYNOX 新（多了不認得的 token、
  slot、值裡用到不認得的 var）＝忽略那一項、記提示，整個外觀照樣能用
- 套用檢查：每個 token（淺色、深色分開）、每個 slot 的結果；終端機預設只印摘要與要注意的，--details 全部，--json 給 AI
全部用假的外觀包（tests/fixtures/theme_pack 改出來的）。不開瀏覽器、不開埠、不連網。
"""

import argparse
import json
import os
import re
import shutil

import pytest

from synox import __main__ as cli
from synox.packs import admin
from synox.packs.manifest import read
from synox.remindwin import style as desk_style
from synox.theme import appearance, check as theme_check, contract, tokens as theme_tokens
from synox.theme import pack as theme_pack
from synox.web import server as web_server

from test_theme import (CSS_FILES, FIXTURE, JS_FILES, STATIC, Client, _decls, _install, _page, _read_static,  # noqa: F401
                        _root_blocks, _styles, _zip, theme_bot, ui_of)

NEW = "glow-ink"          # 假裝 SYNOX 新版本多了這個顏色 token


def _fixture_raw():
    with open(os.path.join(FIXTURE, "pack.json"), encoding="utf-8") as f:
        return json.load(f)


def _old_tokens(raw):
    """只留合約第 1 版的核心 12 色（最舊、最少的外觀包）。"""
    for mode in ("light", "dark"):
        raw["theme"]["tokens"][mode] = {k: v for k, v in raw["theme"]["tokens"][mode].items()
                                        if k in contract.REQUIRED_COLORS}


def _pack_dir(tmp_path, patch):
    folder = tmp_path / "pk"
    shutil.copytree(FIXTURE, folder)
    raw = _fixture_raw()
    patch(raw)
    (folder / "pack.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return str(folder)


@pytest.fixture
def newer_synox(monkeypatch):
    """SYNOX 多了一個顏色 token（淺色、深色各一個預設），外觀包都還沒更新。"""
    monkeypatch.setattr(contract, "ALL_TOKENS", contract.ALL_TOKENS + (NEW,))
    monkeypatch.setitem(contract.TOKEN_KIND, NEW, "color")
    monkeypatch.setitem(contract.DEFAULTS["light"], NEW, "#123456")
    monkeypatch.setitem(contract.DEFAULTS["dark"], NEW, "#abcdef")


# ── 單一來源 ───────────────────────────────────────────────────────────

def test_every_contract_token_has_a_light_default_and_dark_only_overrides():
    assert set(contract.DEFAULTS["light"]) == set(contract.ALL_TOKENS)
    assert set(contract.DEFAULTS["dark"]) <= set(contract.ALL_TOKENS)
    assert set(contract.FIXED["dark"]) <= set(contract.FIXED["light"])
    assert not set(contract.FIXED["light"]) & set(contract.ALL_TOKENS)          # 外觀包換不到的跟換得到的不重名
    assert contract.REQUIRED_COLORS == ("bg", "surface", "text", "muted", "line", "accent", "accent-ink", "accent2",
                                        "soft", "ok", "warn", "bad")              # 合約第 1 版：以後加的都選填


def test_other_places_take_colours_from_the_contract():
    for mode in ("light", "dark"):
        full = contract.default_tokens(mode)
        for name, value in desk_style.DEFAULTS[mode].items():                    # 電腦提醒視窗
            assert value == full[name]
    assert desk_style.DERIVED == {k: v for k, v in contract.DERIVED.items() if k in desk_style.WINDOW_TOKENS}
    page = web_server.PAGE_CSS                                                   # 登入的小頁
    for mode, chunk in (("light", page.split("@media")[0]), ("dark", page.split("@media")[1].split("}}")[0])):
        found = dict(re.findall(r"--([a-z-]+):([^;}]+)", chunk))
        assert found["bg"] == contract.default_tokens(mode)["bg"]
        assert found["accent-soft"] == contract.default_tokens(mode)["soft"]
    assert contract.FIXED["light"]["shadow-md"] in page


def _static_root(name):
    css = re.sub(r"/\*.*?\*/", "", _read_static(name), flags=re.DOTALL)
    light = re.search(r"^:root \{(.*?)\}", css, re.DOTALL | re.MULTILINE).group(1)
    dark = re.search(r"@media \(prefers-color-scheme: dark\) \{\s*:root \{(.*?)\}", css, re.DOTALL).group(1)
    return _decls(light), _decls(dark)


@pytest.mark.parametrize("name", ["appkit.css", "remote_enter.css"])
def test_static_copies_still_match_the_contract(name):
    # 這兩個是不經 render_app 的靜態檔（工具服務的 /_synox/kit.css、手機入口的進門頁），留著副本；值要跟 contract 一樣
    for mode, block in zip(("light", "dark"), _static_root(name)):
        full = contract.default_tokens(mode)
        for key, value in block.items():
            token = "soft" if key == "accent-soft" else key
            if token in full:
                assert value == full[token], (name, mode, key, value, full[token])


def test_every_var_used_by_the_web_ui_is_declared():
    """網頁用到的 var(--x)（沒有後備值的）都在送出去那一頁的 :root 有值：不會有沒定義的顏色。"""
    css = _styles(web_server.render_app("n0nce"))
    declared = set(re.findall(r"--([a-z0-9-]+)\s*:", css))
    sources = {"app.html": css + "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", web_server.render_app("n"),
                                                      re.DOTALL))}
    for name in set(CSS_FILES) | set(JS_FILES) - {"app.html"}:
        sources[name] = _read_static(name)
    sources["preview"] = appearance.PREVIEW_CSS
    missing = []
    for name, text in sources.items():
        own = set(re.findall(r"--([a-z0-9-]+)\s*:", text))
        for ref, comma in re.findall(r"var\(\s*--([a-z0-9-]+)\s*(,?)", text):
            if not comma and ref not in declared and ref not in own:
                missing.append((name, ref))
    assert missing == []


def _luminance(value, tokens):
    r, g, b, _a = desk_style.parse_color(value, tokens)
    def lin(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_synox_defaults_are_readable(mode):
    # 沒給的沿用預設：預設本身的字要看得清楚（不會黑底黑字）
    toks = contract.default_tokens(mode)
    for fg, bg in (("text", "bg"), ("text", "surface"), ("accent-ink", "accent"), ("me-ink", "me")):
        a, b = _luminance(toks[fg], toks), _luminance(toks[bg], toks)
        ratio = (max(a, b) + 0.05) / (min(a, b) + 0.05)
        assert ratio >= 4.5, (mode, fg, bg, ratio)


# ── 向前相容：舊外觀包（只有舊 token）────────────────────────────────────

def test_old_pack_with_only_the_core_colours_passes_and_every_token_has_a_value(tmp_path):
    folder = _pack_dir(tmp_path, _old_tokens)
    m = read(folder, strict=True)
    _m, _report, _hashes, problems = admin.run_gates(folder)
    assert problems == []
    check = theme_check.coverage(m.theme)
    assert check["blocking"] is False and check["issues"] == []
    for mode in ("light", "dark"):
        rows = {r["token"]: r for r in check["tokens"][mode]}
        assert set(rows) == set(contract.ALL_TOKENS)
        assert all(r["value"] for r in rows.values())                            # 每一個都有值
        assert {n for n, r in rows.items() if r["status"] == "provided"} == set(contract.REQUIRED_COLORS)
        assert rows["m1"]["status"] == "derived" and rows["radius"]["status"] == "default"
    assert {r["slot"]: r["status"] for r in check["slots"]}["opening"] == "provided"


def test_newer_synox_old_pack_falls_back_to_synox_defaults(tmp_path, newer_synox):
    folder = _pack_dir(tmp_path, _old_tokens)
    m = read(folder, strict=True)                                               # 不會因為少了新 token 就裝不上
    check = theme_check.coverage(m.theme)
    for mode, value in (("light", "#123456"), ("dark", "#abcdef")):
        row = next(r for r in check["tokens"][mode] if r["token"] == NEW)
        assert row["status"] == "default" and row["value"] == value and row["issue"] is True
    assert [(i["mode"], i["name"]) for i in check["issues"]] == [("light", NEW), ("dark", NEW)]
    # 網頁：SYNOX 自己的 :root 有新 token（淺色、兩段深色），外觀包的 CSS 沒有蓋它
    light, dark = (_decls(b) for b in _root_blocks(web_server.render_app("n")))
    assert light[NEW] == "#123456" and dark[NEW] == "#abcdef"
    bundle = theme_pack.compile_theme(folder, m.name, m.theme)
    assert NEW not in bundle.stylesheet()
    # 預覽頁也先墊 SYNOX 的：不會缺色
    page = appearance.preview_page(m.title, "dark", bundle, m.theme["tokens"])
    assert f"--{NEW}: #123456" in page and f"--{NEW}: #abcdef" in page


def test_newer_synox_old_pack_applies_in_the_real_page(theme_bot, owner, newer_synox):
    bot = theme_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    summary = _install(c)
    assert any(i["name"] == NEW for i in summary["theme"]["check"]["issues"])   # 安裝報告就看得到
    assert c.post("/api/appearance", {"theme": "sample-lantern"})[0] == 200
    look = c.get("/api/appearance")[1]
    assert any(i["name"] == NEW for i in look["themes"][0]["check"]["issues"])  # 設定 → 外觀的卡片也有
    for mode in ("light", "dark"):
        assert c.post("/api/appearance", {"mode": mode})[0] == 200
        html, _n, _csp = _page(c)
        assert 'id="synox-theme"' in html and "--accent: #a85400" in html
        light, dark = (_decls(b) for b in _root_blocks(html))
        assert light[NEW] == "#123456" and dark[NEW] == "#abcdef"
        theme_css = html.split('id="synox-theme">', 1)[1].split("</style>", 1)[0]
        assert NEW not in theme_css


# ── 向前相容：外觀包比 SYNOX 新 ─────────────────────────────────────────

def _newer_pack(raw):
    raw["theme"]["tokens"]["light"]["--glow-x"] = "#ff00aa"                       # SYNOX 還沒有的 token
    raw["theme"]["tokens"]["dark"]["soft"] = "color-mix(in srgb, var(--future-tone) 20%, transparent)"
    raw["theme"]["slots"]["mascot.dance"] = "slots/idle.svg"                      # SYNOX 還沒有的位置


def test_newer_pack_installs_and_ignores_what_synox_does_not_know(tmp_path):
    token, summary = admin.stage(_zip(patch=_newer_pack), str(tmp_path / "data"))
    assert token and not summary["scan"]["problems"]
    check = summary["theme"]["check"]
    got = {(i["kind"], i["mode"], i["name"], i["status"]) for i in check["issues"]}
    assert got == {("token", "light", "glow-x", "ignored"), ("token", "dark", "soft", "default"),
                   ("slot", "", "mascot.dance", "ignored")}
    dark = {r["token"]: r for r in check["tokens"]["dark"]}
    assert dark["soft"]["value"] == contract.DEFAULTS["dark"]["soft"] and "future-tone" in dark["soft"]["why"]
    m = read(os.path.join(admin._staged_root(token, str(tmp_path / "data")), "pack"), strict=True)
    css = theme_pack.compile_theme(m.folder, m.name, m.theme).stylesheet()
    assert "glow-x" not in css and "future-tone" not in css and "mascot.dance" not in m.theme["slots"]
    text = admin.format_summary(summary)
    assert "要注意 3 項" in text and "--glow-x" in text and "mascot.dance" in text


def test_value_problems_are_still_refused():
    # 向前相容只放過「不認得的名字」；值本身有問題（網址、程式）照樣拒
    raw = _fixture_raw()["theme"]["tokens"]
    raw["light"]["bg"] = "url(https://evil.example/x.png)"
    _toks, problems, _notes = theme_tokens.parse_tokens_full(raw)
    assert any("bg" in p for p in problems)
    raw = _fixture_raw()["theme"]["tokens"]
    raw["light"]["soft"] = "color-mix(in srgb, var(--future) 20%, url(x))"
    _toks, problems, _notes = theme_tokens.parse_tokens_full(raw)
    assert any("soft" in p for p in problems)


# ── 套用檢查的輸出 ───────────────────────────────────────────────────────

def test_full_pack_check_lists_every_token_per_mode():
    m = read(FIXTURE, strict=True)
    check = theme_check.coverage(m.theme)
    assert check["issues"] == []
    dark = {r["token"]: r for r in check["tokens"]["dark"]}
    assert dark["radius"]["status"] == "provided" and dark["radius"]["from"] == "light"   # 深色沿用淺色的圓角
    assert dark["surface-2"]["status"] == "derived"
    assert dark["scrim"]["status"] == "default" and dark["scrim"]["issue"] is False        # 暗幕：哪一套都合用
    assert check["counts"]["slots"] == {"provided": len(contract.SLOTS), "default": 0, "ignored": 0}
    json.dumps(check)                                                                       # 給 AI：純 JSON


def _args(target, **kw):
    return argparse.Namespace(target=target, details=kw.get("details", False), json=kw.get("json", False))


def test_cli_theme_check_summary_details_and_json(tmp_path, capsys, newer_synox):
    assert cli.cmd_theme_check(_args(FIXTURE), {}) == 10                       # 新 token 沒給：有要注意的（不擋）
    out = capsys.readouterr().out
    assert "套用檢查" in out and f"--{NEW}" in out and "要看每一項：加 --details" in out
    assert "--surface-2" not in out                                             # 預設只有摘要與要注意的
    assert cli.cmd_theme_check(_args(FIXTURE, details=True), {}) == 10
    out = capsys.readouterr().out
    assert "淺色的每一個 token" in out and "深色的每一個 token" in out and "--surface-2" in out and "mascot.idle" in out
    assert cli.cmd_theme_check(_args(FIXTURE, json=True), {}) == 10
    data = json.loads(capsys.readouterr().out)
    assert data["name"] == "sample-lantern" and data["blocking"] is False
    assert {"tokens", "slots", "counts", "issues"} <= set(data)
    assert cli.cmd_theme_check(_args(str(tmp_path)), {}) == 2                   # 不是 pack


def test_cli_entry_points(tmp_path, capsys):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": 1, "data_dir": str(tmp_path / "data")}), encoding="utf-8")
    assert cli.main(["-q", "--config", str(cfg), "packs", "theme-check", FIXTURE, "--json"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out[out.index("{"):])
    assert data["name"] == "sample-lantern" and data["issues"] == []
    blob = tmp_path / "sample-lantern.synoxpack"
    blob.write_bytes(_zip())
    args = argparse.Namespace(config=str(cfg), file=str(blob), yes=False, packs_dir=str(tmp_path / "packs"),
                              trust_publisher=None, runtime=None, details=True)
    assert cli.cmd_install(args, is_up=lambda _port: False) == 1                 # 沒核准：只印報告
    out = capsys.readouterr().out
    assert "套用檢查" in out and "淺色的每一個 token" in out and "--surface-2" in out
