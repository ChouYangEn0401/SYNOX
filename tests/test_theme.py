"""外觀（換裝）：synox/theme（docs/themes.md）。

- 消毒：SVG／HTML／CSS 有程式、事件屬性、javascript:、外部網址、@import、<foreignObject>…一律拒絕；好的照白名單重建
- token 合約：網頁的顏色只從 app.html 最上面的 token 來（例外寫在 COLOR_EXCEPTIONS）；合約的名字都在、預設值對得上
- slot 合約：網頁用到的 data-slot 都在 contract.SLOTS、每個 slot 都有地方用；slots.js 的清單一樣
- 外觀包（kind=theme）：第 1、2 關、信任層級 T0、上傳 → 報告（色票、預覽）→ 確認才裝 → 套用 → 換回原本的
- 自己貼：預覽、套用、拒絕；伺服器版每個人自己一份（沒選的跟擁有者一樣）
不開瀏覽器、不開埠、不連網。
"""

import io
import json
import os
import re
import zipfile

import pytest

from isdtelekit.users.roles import BasicRoles

from synox.packs import admin, loader
from synox.packs.manifest import ManifestError, read, validate
from synox.theme import appearance, contract, defaults, sanitize, tokens as theme_tokens
from synox.theme import pack as theme_pack
from synox.web import server as web_server

from conftest import OTHER_ID
from test_web import Client, ui_of

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "src", "synox", "web", "static")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "theme_pack")


def _read_static(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as f:
        return f.read()


def _zip(folder=FIXTURE, extra=None, drop=(), patch=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for base, _dirs, names in os.walk(folder):
            for n in names:
                rel = os.path.relpath(os.path.join(base, n), folder).replace(os.sep, "/")
                if rel in drop or rel in (extra or {}):
                    continue
                with open(os.path.join(base, n), "rb") as f:
                    data = f.read()
                if rel == "pack.json" and patch:
                    raw = json.loads(data)
                    patch(raw)
                    data = json.dumps(raw, ensure_ascii=False).encode("utf-8")
                z.writestr(rel, data)
        for rel, data in (extra or {}).items():
            z.writestr(rel, data)
    return buf.getvalue()


# ── 消毒：SVG／HTML ────────────────────────────────────────────────────

BAD_MARKUP = [
    ("<svg><script>alert(1)</script></svg>", "script"),
    ('<svg onload="alert(1)"><rect/></svg>', "onload"),
    ('<svg><rect onclick="x()"/></svg>', "onclick"),
    ('<svg><a href="javascript:alert(1)"><rect/></a></svg>', "<a>"),
    ('<svg><rect fill="java&#x09;script:alert(1)"/></svg>', "javascript:"),
    ('<svg><rect fill="url(https://evil.example/x.svg#g)"/></svg>', "外部網址"),
    ('<svg><rect style="fill:url(http://evil.example/)"/></svg>', "外部網址"),
    ('<svg><use href="https://evil.example/s.svg#a"/></svg>', "指到外面"),
    ('<svg><use xlink:href="data:image/svg+xml,&lt;svg&gt;"/></svg>', "data:"),
    ("<svg><foreignObject><div>hi</div></foreignObject></svg>", "foreignObject"),
    ("<svg><style>@import url(https://evil.example/x.css);</style></svg>", "@import"),
    ("<svg><style>.a{background:url(https://evil.example/)}</style></svg>", "外部網址"),
    ('<svg><image href="https://evil.example/x.png"/></svg>', "<image>"),
    ('<img src="x" onerror="alert(1)">', "<img>"),
    ('<svg><set attributeName="onmouseover" to="alert(1)"/></svg>', "<set>"),
    ('<svg><animate attributeName="href" values="javascript:alert(1)"/></svg>', "javascript:"),
    ('<iframe src="https://evil.example"></iframe>', "<iframe>"),
    ('<svg><filter><feImage href="https://evil.example/x"/></filter></svg>', "<feImage>"),
    ("<math><mi>x</mi></math>", "<math>"),
    ('<link rel="stylesheet" href="https://evil.example/x.css">', "<link>"),
]


@pytest.mark.parametrize("text, why", BAD_MARKUP)
def test_sanitizer_rejects_code_and_external_resources(text, why):
    with pytest.raises(sanitize.Rejected) as e:
        sanitize.sanitize_markup(text, "mascot.idle")
    assert why in str(e.value), str(e.value)


def test_sanitizer_rebuilds_good_svg_and_scopes_ids_and_style():
    text = ('<?xml version="1.0"?><!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" '
            'inkscape:label="x"><!-- c --><defs><linearGradient id="g"><stop offset="0" style="stop-color:#f80"/>'
            '</linearGradient></defs><style>.eye{fill:var(--mi)} #g{opacity:.5} @keyframes blink{50%{opacity:0}}'
            '.eye{animation:blink 1s}</style><rect id="r" fill="url(#g)" width="10" height="10"/>'
            '<use href="#r"/><circle class="eye" r="1"/><metadata><x/></metadata><text>a &lt;b&gt;</text></svg>')
    clean = sanitize.sanitize_markup(text, "mascot.idle")
    assert clean.markup.startswith('<svg viewBox="0 0 10 10">')
    assert 'id="ts-mascot-idle-g"' in clean.markup and 'fill="url(#ts-mascot-idle-g)"' in clean.markup
    assert 'href="#ts-mascot-idle-r"' in clean.markup and 'stop-color="#f80"' in clean.markup
    assert "<style" not in clean.markup and "metadata" not in clean.markup and "<!--" not in clean.markup
    assert "a &lt;b&gt;" in clean.markup
    assert '[data-slot="mascot.idle"] .eye { fill: var(--mi) }' in clean.css
    assert '[data-slot="mascot.idle"] #ts-mascot-idle-g' in clean.css
    assert "@keyframes th-mascot-idle-blink" in clean.css and "animation: th-mascot-idle-blink 1s" in clean.css
    assert any("inkscape:label" in n for n in clean.notes)


def test_sanitizer_html_subset_and_context():
    clean = sanitize.sanitize_markup('<div class="w"><b>syn</b>ox<svg viewBox="0 0 2 2"><rect/></svg></div>', "wordmark")
    assert clean.markup == '<div class="w"><b>syn</b>ox<svg viewBox="0 0 2 2"><rect></rect></svg></div>'
    # SVG 裡不能放 HTML（不能跳出 SVG 的解析模式）；HTML 外面的 SVG 元素也不收
    clean = sanitize.sanitize_markup("<svg><div>x</div><rect/></svg>", "wordmark")
    assert "<div" not in clean.markup and any("<div>" in n for n in clean.notes)
    with pytest.raises(sanitize.Rejected, match="剛好是一張"):
        sanitize.sanitize_markup("<div>x</div>", "appicon", kinds=("svg",))
    with pytest.raises(sanitize.Rejected, match="是空的"):
        sanitize.sanitize_markup("<!-- nothing -->", "mascot.idle")
    with pytest.raises(sanitize.Rejected, match="太大"):
        sanitize.sanitize_markup("<svg>" + "x" * (sanitize.MAX_MARKUP + 1) + "</svg>", "mascot.idle")


# ── 消毒：CSS ─────────────────────────────────────────────────────────

BAD_CSS = [
    ("@import url(x.css);", "@import"),
    ("@import 'x.css';", "@import"),
    ("[data-slot] { background: url(https://evil.example/x) }", "外部網址"),
    ("[data-slot] { background: url(data:image/png;base64,AA) }", "外部網址"),
    ("[data-slot] { background: image-set('x.png' 1x) }", "image-set"),
    ("[data-slot] { x: \\75rl(x) }", "反斜線"),
    ("[data-slot] { color: red !important }", "!important"),
    ("[data-slot] { width: expression(alert(1)) }", "expression"),
    ("[data-slot] { -moz-binding: x }", "-moz-binding"),
    ("@font-face { font-family: x; src: local(x) }", "@font-face"),
    (".foo { color: red }", "[data-slot]"),
    ("body { display: none }", "[data-slot]"),
    ("[data-slot] ~ nav { display: none }", "兄弟"),
    ("[data-slot] + * { display: none }", "兄弟"),
    ("[data-slot]:has(.x) { color: red }", ":has"),
    (":root { background: red }", "只能設 token"),
    (":root { --bg: url(x) }", "外部網址"),
    ("@keyframes spin { to { opacity: 0 } }", "th-"),
    ("@page { margin: 0 }", "@ 規則"),
    ("[data-slot] { color: red } }", "大括號"),
    ("[data-slot] { color: red", "大括號"),
    ("[data-slot] { color: red } /* x", "註解"),
    ("[data-slot] { content: '</style><script>x</script>' }", "「<」"),
]


@pytest.mark.parametrize("text, why", BAD_CSS)
def test_css_sanitizer_rejects(text, why):
    with pytest.raises(sanitize.Rejected) as e:
        sanitize.sanitize_css(text)
    assert why in str(e.value), str(e.value)


def test_css_sanitizer_keeps_tokens_scoped_rules_keyframes_and_media():
    css = sanitize.sanitize_css(
        ':root { --bg: #fff; --th-glow: 3px }\n:root[data-theme="dark"] { --bg: #000 }\n'
        '[data-slot="opening"] .a, .theme-slot-opening > g { animation: th-pop 1s; fill: url(#ts-opening-g) }\n'
        "@keyframes th-pop { from { opacity: 0 } 50% { opacity: .5 } to { opacity: 1 } }\n"
        "@media (prefers-reduced-motion: reduce) { [data-slot] * { animation: none } }")
    assert ":root { --bg: #fff; --th-glow: 3px }" in css
    assert "[data-slot=\"opening\"] .a, .theme-slot-opening > g { animation: th-pop 1s; fill: url(#ts-opening-g) }" in css
    assert "@keyframes th-pop" in css and "@media (prefers-reduced-motion: reduce)" in css
    # 自己貼的：每個選擇器自動套上這個 slot
    assert sanitize.sanitize_css("svg .x { fill: red }", slot="wordmark") == '[data-slot="wordmark"] svg .x { fill: red }'
    with pytest.raises(sanitize.Rejected, match="不能"):
        sanitize.sanitize_css(":root { --bg: red }", slot="wordmark")


def test_token_values():
    ok = {"bg": "#fff", "accent": "oklch(70% .1 60)", "soft": "color-mix(in srgb, var(--accent) 12%, transparent)",
          "radius": "12px", "font-ui": '"Noto Sans TC", system-ui, sans-serif', "font-brand": "var(--font-ui)"}
    for name, value in ok.items():
        assert theme_tokens.token_value_problem(name, value) == "", (name, value)
    for name, value in (("bg", "url(x)"), ("bg", "red; background: url(x)"), ("bg", "attr(x)"),
                        ("bg", "var(--evil)"), ("radius", "10vw"), ("font-ui", "x; y"), ("font-ui", "x</style>"),
                        ("bg", "image(x)"), ("accent", "env(x)")):
        assert theme_tokens.token_value_problem(name, value), (name, value)


# ── token 合約 ─────────────────────────────────────────────────────────

# 允許寫死的顏色（每一個都要說為什麼）。空的＝網頁的顏色全部來自 token。
COLOR_EXCEPTIONS = {
    # （目前沒有例外：以前的手機底部分頁陰影 rgba(0,0,0,.4) 改成 --shadow-up、等回覆的方塊改成 .cb-* class）
}
COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|hwb|oklch|oklab|lab|lch)\(|"
                      r"(?<![-\w])(?:white|black|red|blue|green|gray|grey|orange|yellow|purple|pink|silver)(?![-\w])")
CSS_FILES = ("control.css", "tools.css", "tour.css", "packdrop.css", "report.css", "splash.css")
JS_FILES = ("app.html", "control.js", "tools.js", "tour.js", "packdrop.js", "report.js", "splash.js", "slots.js",
            "blocks.js")


def _styles(html):
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.DOTALL))


def _without_token_blocks(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    return css.split("/* ── 基本")[1] if "/* ── 基本" in css else css


def test_web_ui_colours_come_only_from_tokens():
    html = _read_static("app.html")
    head_css = html.split("</style>")[0].split("<style nonce=\"{{NONCE}}\">", 1)[1]
    rest = head_css.split("/* ── 基本", 1)[1]                    # 最上面的 token 區以外
    sources = {"app.html": re.sub(r"/\*.*?\*/", "", rest, flags=re.DOTALL)}
    for name in CSS_FILES:
        sources[name] = re.sub(r"/\*.*?\*/", "", _read_static(name), flags=re.DOTALL)
    found = []
    for name, css in sources.items():
        css = re.sub(r"white-space|#[a-z][\w-]*[a-z_-][\w-]*", " ", css)   # white-space、#id 選擇器不算
        for m in COLOR_RE.finditer(css):
            if (name, m.group(0)) not in COLOR_EXCEPTIONS:
                found.append((name, m.group(0), css[max(0, m.start() - 40):m.end() + 20].strip()))
    assert found == [], "顏色寫進 app.html 最上面的 token：" + repr(found[:5])


def test_scripts_do_not_hard_code_colours():
    for name in JS_FILES:
        text = _read_static(name)
        if name == "app.html":
            text = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", text, re.DOTALL))
        for bad in re.findall(r"(?:fill|stroke|color|background)\s*[=:]\s*[\"']?#[0-9a-fA-F]{3,8}", text):
            pytest.fail(f"{name} 寫死了顏色 {bad}：改成 class＋token")
        assert not re.search(r"[\"']#[0-9a-fA-F]{6}[\"']", text), name


def _root_blocks(html):
    css = _styles(html)
    light = re.search(r":root \{(.*?)\n  \}", css, re.DOTALL).group(1)
    forced_dark = re.search(r':root\[data-theme="dark"\] \{(.*?)\n  \}', css, re.DOTALL).group(1)
    return light, forced_dark


def _decls(block):
    return {m.group(1): " ".join(m.group(2).split()) for m in re.finditer(r"--([a-z0-9-]+):\s*([^;]+);", block)}


def test_contract_tokens_are_defined_and_defaults_match_app_html():
    light, dark = (_decls(b) for b in _root_blocks(_read_static("app.html")))
    for name in contract.TOKENS + contract.MASCOT_TOKENS + contract.ADVANCED_TOKENS:
        assert name in light, f"app.html 的 :root 少了 --{name}"
    for mode, block in (("light", light), ("dark", dark)):
        for name, value in contract.DEFAULTS[mode].items():
            assert block.get(name) == value, (mode, name, block.get(name), value)
    for old, new in (("accent-2", "accent2"), ("accent-soft", "soft"), ("r", "radius"), ("font", "font-ui")):
        assert light[old] == f"var(--{new})"                      # 舊名字是別名
    # 深色那兩段（跟隨系統、強制）一樣
    css = _styles(_read_static("app.html"))
    follow = re.search(r':root:not\(\[data-theme="light"\]\) \{(.*?)\n    \}', css, re.DOTALL).group(1)
    assert _decls(follow) == dark


def test_token_css_covers_all_three_mode_selectors_and_derives_the_rest():
    raw = json.load(open(os.path.join(FIXTURE, "pack.json"), encoding="utf-8"))["theme"]["tokens"]
    toks, problems = theme_tokens.parse_tokens(raw)
    assert problems == []
    css = theme_tokens.token_css(toks)
    assert css.count("--accent:") == 3 and ':root:not([data-theme="light"])' in css and ':root[data-theme="dark"]' in css
    assert "--surface-2: color-mix(" in css and "--radius: 12px" in css
    _toks, problems = theme_tokens.parse_tokens({"light": {"bg": "#fff"}, "dark": {}})
    assert any("少了" in p for p in problems)
    _toks, problems = theme_tokens.parse_tokens({"light": {**raw["light"], "nope": "#fff"}, "dark": raw["dark"]})
    assert any("nope" in p for p in problems)


# ── slot 合約 ──────────────────────────────────────────────────────────

def test_slot_names_match_the_web_ui():
    html = _read_static("app.html")
    used = set(re.findall(r'data-slot="([a-z.]+)"', html))
    used |= set(re.findall(r'slotNode\("([a-z.]+)"', html))
    used |= set(re.findall(r'themed\(doc, "([a-z.]+)"\)', _read_static("splash.js")))
    used |= set(defaults.MARKUP)
    used.add("appicon")                                           # <link rel="icon">（server 依外觀放）
    assert used == set(contract.SLOTS), used ^ set(contract.SLOTS)
    names = re.search(r"var NAMES = \[([^\]]+)\]", _read_static("slots.js")).group(1)
    assert [n.strip().strip('"') for n in names.split(",")] == list(contract.SLOTS)
    for name, (text, since, kinds) in contract.SLOTS.items():
        assert text and since <= contract.CONTRACT_VERSION and set(kinds) <= {"svg", "html"}
    assert contract.CONTRACT_VERSION == 1 and not contract.RENAMED_SLOTS


def test_contract_token_names_are_stable():
    # 給外觀包作者的名字（兄弟工作照這些做包）：只加不改
    assert contract.TOKENS == ("bg", "surface", "text", "muted", "line", "accent", "accent-ink", "accent2", "soft",
                               "ok", "warn", "bad", "radius", "font-ui", "font-brand")
    assert contract.MASCOT_TOKENS == ("m1", "m2", "mi", "mb")
    assert list(contract.SLOTS) == ["mascot.idle", "mascot.think", "mascot.happy", "mascot.warn", "opening",
                                    "wordmark", "appicon"]


def test_slot_elements_are_pinned_so_theme_css_cannot_move_them():
    html = _read_static("app.html")
    rule = re.search(r"\[data-slot\] \{(.*?)\}", html, re.DOTALL).group(1)
    for decl in ("position: relative !important", "transform: none !important", "contain: paint !important",
                 "margin: 0 !important", "overflow: clip !important"):
        assert decl in rule, decl


def test_default_render_has_default_templates_and_no_theme():
    html = web_server.render_app("n0nce")
    for slot in defaults.MARKUP:
        assert f'<template data-slot-default="{slot}">' in html
    assert 'id="synox-theme"' not in html and "data-slot-src=\"mascot" not in html and "<!-- theme -->" not in html
    assert "fill=\"#" not in html.split("<body")[1].split("<script")[0]


# ── 外觀包：第 1、2 關 ──────────────────────────────────────────────────

def test_fixture_theme_pack_passes_gates_and_is_t0(tmp_path):
    m = read(FIXTURE, strict=True)
    assert m.kind == "theme" and set(m.theme["slots"]) == set(contract.SLOTS)
    _m, report, _hashes, problems = admin.run_gates(FIXTURE)
    assert problems == []
    assert admin.tier_of(m, report)["tier"] == "T0"
    bundle = theme_pack.compile_theme(FIXTURE, m.name, m.theme)
    assert "<" not in bundle.stylesheet() and set(bundle.slots) == set(contract.SLOTS)


@pytest.mark.parametrize("key, value, why", [
    ("python", {"module": "pack"}, "不能有 python"),
    ("cli", {"argv": ["x"]}, "不能有 cli"),
    ("capabilities", ["network"], "不能有 capabilities"),
    ("web", {"panel": "p.html"}, "不能有 web"),
    ("mcp", {"url": "https://x"}, "不能有 mcp"),
])
def test_theme_pack_cannot_declare_code(tmp_path, key, value, why):
    raw = json.load(open(os.path.join(FIXTURE, "pack.json"), encoding="utf-8"))
    raw[key] = value
    with pytest.raises(ManifestError, match=why):
        validate(raw, FIXTURE, strict=True)


def test_theme_pack_manifest_checks(tmp_path):
    raw = json.load(open(os.path.join(FIXTURE, "pack.json"), encoding="utf-8"))
    for patch, why in ((lambda r: r["theme"]["slots"].update({"mascot.dance": "slots/idle.svg"}), "不認得"),
                       (lambda r: r["theme"]["slots"].update({"mascot.idle": "../x.svg"}), "不能有 .."),
                       (lambda r: r["theme"]["slots"].update({"appicon": "slots/idle.html"}), "svg"),
                       (lambda r: r["theme"].update({"fonts": ["https://fonts.example/x.woff2"]}), "找不到"),
                       (lambda r: r["theme"].update({"contract": 99}), "請先更新 SYNOX"),
                       (lambda r: r["theme"]["tokens"]["dark"].pop("accent"), "少了 accent")):
        r = json.loads(json.dumps(raw))
        patch(r)
        with pytest.raises(ManifestError, match=why):
            validate(r, FIXTURE, strict=True)


def _unzip(blob, tmp_path):
    folder = tmp_path / "pk"
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        z.extractall(folder)
    return str(folder)


@pytest.mark.parametrize("extra, why", [
    ({"slots/evil.svg": '<svg onload="alert(1)"/>'}, "onload"),
    ({"slots/idle.svg": "<svg><script>alert(1)</script></svg>"}, "script"),
    ({"theme.css": "@import url(https://fonts.googleapis.com/css2?family=X);"}, "@import"),
    ({"theme.css": ".msg { display: none }"}, "[data-slot]"),
    ({"run.py": "print(1)"}, "只能有"),
    ({"x.js": "alert(1)"}, "只能有"),
    ({"slots/think.svg": '<svg><foreignObject><iframe src="https://x"/></foreignObject></svg>'}, "foreignObject"),
])
def test_theme_pack_gate2_rejects_bad_files(tmp_path, extra, why):
    with pytest.raises(admin.GateRefused) as e:
        admin.stage(_zip(extra=extra), str(tmp_path / "data"))
    assert why in str(e.value), str(e.value)


def test_theme_fonts_must_be_bundled_woff2(tmp_path):
    font = b"wOF2" + b"\0" * 60

    def add_font(raw):
        raw["theme"]["fonts"] = [{"family": "Lantern Serif", "file": "fonts/lantern.woff2", "weight": "600"}]
        raw["theme"]["tokens"]["light"]["font-brand"] = '"Lantern Serif", serif'
    token, summary = admin.stage(_zip(extra={"fonts/lantern.woff2": font}, patch=add_font), str(tmp_path / "data"))
    assert summary["theme"]["fonts"] == ["Lantern Serif"]
    with pytest.raises(admin.GateRefused, match="不是 woff2"):
        admin.stage(_zip(extra={"fonts/lantern.woff2": b"<html>"}, patch=add_font), str(tmp_path / "data2"))


# ── 安裝 → 套用 → 換回原本的（網頁） ─────────────────────────────────────

@pytest.fixture
def theme_bot(make_bot, tmp_path):
    def factory(**kw):
        user_packs = tmp_path / "userpacks"
        user_packs.mkdir(exist_ok=True)
        return make_bot(pack_dirs=(str(user_packs),) + loader.PACK_DIRS, **kw)
    return factory


def _install(c):
    status, _h, body = c.raw("POST", "/api/packs/upload", _zip())
    summary = json.loads(body)
    assert status == 200, summary
    status, data = c.post("/api/packs/install", {"token": summary["token"]})
    assert status == 200 and data["status"] == "loaded" and data["kind"] == "theme", data
    return summary


def _page(c, cookie=True):
    status, headers, body = c.raw("GET", "/") if cookie else c.ui.handle("GET", "/", {"Host": c.host})
    assert status == 200
    html = body.decode("utf-8")
    nonce = re.search(r"script-src 'nonce-([^']+)'", dict(headers)["Content-Security-Policy"]).group(1)
    return html, nonce, dict(headers)["Content-Security-Policy"]


def test_theme_pack_upload_report_confirm_apply_and_revert(theme_bot, owner):
    bot = theme_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    status, _h, body = c.raw("POST", "/api/packs/upload", _zip())
    summary = json.loads(body)
    assert status == 200 and summary["kind"] == "theme" and summary["tier"]["tier"] == "T0"
    assert summary["theme"]["tokens"]["light"]["accent"] == "#a85400"         # 色票
    assert "ln-body" in summary["theme"]["markup"]["mascot.idle"]             # 吉祥物預覽（消毒過）
    assert "trust_choices" not in summary and any("外觀包" in w for w in summary["warnings"])
    status, headers, page = c.raw("GET", f"/theme/preview?staged={summary['token']}&mode=dark")   # 報告上的預覽
    text = page.decode("utf-8")
    assert status == 200 and 'data-theme="dark"' in text and "ln-body" in text and "<script" not in text
    assert "script-src" not in dict(headers)["Content-Security-Policy"]
    assert c.get("/api/appearance")[1]["themes"] == []                         # 還沒按確認：沒裝
    html, _n, _csp = _page(c)
    assert 'id="synox-theme"' not in html
    status, data = c.post("/api/packs/install", {"token": summary["token"]})
    assert status == 200 and data["kind"] == "theme"
    look = c.get("/api/appearance")[1]
    assert [t["name"] for t in look["themes"]] == ["sample-lantern"] and look["theme"] == ""
    html, _n, _csp = _page(c)
    assert 'id="synox-theme"' not in html                                       # 裝好不會自己套用
    assert bot.app.registry.node("samplelantern") is None                      # 不進指令表

    status, data = c.post("/api/appearance", {"theme": "sample-lantern"})
    assert status == 200 and data["theme"] == "sample-lantern"
    html, nonce, csp = _page(c)
    assert f'<style nonce="{nonce}" id="synox-theme">' in html and "--accent: #a85400" in html
    assert '<html lang="zh-Hant" data-skin="sample-lantern">' in html
    assert '<template data-slot-src="mascot.idle">' in html and '<template data-slot-src="opening">' in html
    assert '<link rel="icon" href="data:image/svg+xml;base64,' in html and "font-src 'self'" in csp
    head = html.split("</head>")[0]
    assert head.index("--accent2: #2f7fd6") < head.index('id="synox-theme"') < head.index(".sx-splash")   # 蓋過預設 token
    assert head.rstrip().endswith("</style>")
    html, _n, _csp = _page(c, cookie=False)                                     # 還沒登入的畫面：擁有者選的
    assert 'id="synox-theme"' in html
    status, page = c.get("/theme/preview?name=sample-lantern&mode=light")
    assert status == 200 and b"--accent: #a85400" in page

    assert c.post("/api/appearance", {"theme": "nope"})[0] == 400
    assert c.post("/api/appearance", {"mode": "sepia"})[0] == 400
    assert c.post("/api/appearance", {"mode": "dark"})[0] == 200
    html, _n, _csp = _page(c)
    assert '<html lang="zh-Hant" data-theme="dark" data-skin="sample-lantern">' in html
    assert c.post("/api/appearance", {"theme": ""})[0] == 200                  # 換回原本的 SYNOX
    html, _n, _csp = _page(c)
    assert 'id="synox-theme"' not in html and "data-skin" not in html and 'data-theme="dark"' in html


def test_tampered_or_removed_theme_is_not_offered(theme_bot, owner, tmp_path):
    bot = theme_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    _install(c)
    c.post("/api/appearance", {"theme": "sample-lantern"})
    with open(tmp_path / "userpacks" / "sample-lantern" / "theme.css", "a", encoding="utf-8") as f:
        f.write("\n[data-slot] .x { fill: red }\n")
    c.post("/api/packs/reload")
    assert c.get("/api/appearance")[1]["themes"] == []                         # 第 3 關：跟核准時不一樣＝不能用
    html, _n, _csp = _page(c)
    assert 'id="synox-theme"' not in html                                       # 畫面退回原本的 SYNOX
    status, data = c.post("/api/packs/remove", {"name": "sample-lantern"})
    assert status == 200


def test_theme_font_route_serves_only_declared_woff2(theme_bot, owner):
    bot = theme_bot()
    c = Client(ui_of(bot))
    c.login(owner)

    def add_font(raw):
        raw["theme"]["fonts"] = ["fonts/Lantern.woff2"]
    status, _h, body = c.raw("POST", "/api/packs/upload", _zip(extra={"fonts/Lantern.woff2": b"wOF2" + b"\0" * 40},
                                                               patch=add_font))
    token = json.loads(body)["token"]
    assert c.post("/api/packs/install", {"token": token})[0] == 200
    status, headers, blob = c.ui.handle("GET", "/theme/font/sample-lantern/fonts/Lantern.woff2", {})
    assert status == 200 and blob.startswith(b"wOF2") and dict(headers)["Content-Type"] == "font/woff2"
    assert c.ui.handle("GET", "/theme/font/sample-lantern/pack.json", {})[0] == 404
    assert c.ui.handle("GET", "/theme/font/sample-lantern/../x.woff2", {})[0] == 404
    c.post("/api/appearance", {"theme": "sample-lantern"})
    html, _n, _csp = _page(c)
    assert 'src: url("/theme/font/sample-lantern/fonts/Lantern.woff2") format("woff2")' in html
    assert "fonts.googleapis" not in html


def test_preview_needs_login_and_staged_preview_is_owner_only(theme_bot, owner):
    bot = theme_bot(raw={"mode": "server"})
    ui = ui_of(bot)
    assert ui.handle("GET", "/theme/preview", {})[0] == 401
    c = Client(ui)
    c.login(owner)
    status, _h, body = c.raw("POST", "/api/packs/upload", _zip())
    token = json.loads(body)["token"]
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    m = Client(ui)
    m.login(OTHER_ID)
    assert m.raw("GET", f"/theme/preview?staged={token}")[0] == 403
    assert m.raw("POST", "/api/packs/upload", _zip())[0] == 403                # 外觀包只有擁有者能裝
    assert m.get("/theme/preview")[0] == 200                                   # 原本的 SYNOX 誰都能預覽


# ── 自己貼 ────────────────────────────────────────────────────────────

def test_custom_paste_preview_apply_reject_and_clear(theme_bot, owner):
    bot = theme_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    svg = ('<svg viewBox="0 0 10 10"><style>.dot{fill:var(--accent)}</style>'
           '<circle class="dot" cx="5" cy="5" r="4"/></svg>')
    status, data = c.post("/api/appearance/custom", {"slot": "mascot.think", "text": svg, "preview": True})
    assert status == 200 and data["markup"].startswith("<svg") and '[data-slot="mascot.think"] .dot' in data["css"]
    html, _n, _csp = _page(c)
    assert 'data-slot-src="mascot.think"' not in html                          # 預覽不存
    assert c.post("/api/appearance/custom", {"slot": "mascot.think", "text": svg})[0] == 200
    html, nonce, _csp = _page(c)
    assert '<template data-slot-src="mascot.think"><svg viewBox="0 0 10 10">' in html
    assert '[data-slot="mascot.think"] .dot { fill: var(--accent) }' in html
    look = c.get("/api/appearance")[1]
    assert look["custom"]["mascot.think"]["ok"] and look["custom"]["mascot.think"]["text"] == svg
    for bad in ('<svg onload="alert(1)"><rect/></svg>', "<script>alert(1)</script>",
                '<svg><rect fill="url(https://evil.example/)"/></svg>'):
        status, data = c.post("/api/appearance/custom", {"slot": "mascot.idle", "text": bad})
        assert status == 400 and data["error"].startswith("不收")
    assert c.post("/api/appearance/custom", {"slot": "nav", "text": svg})[0] == 400
    assert c.post("/api/appearance/custom", {"slot": "appicon", "text": "<div>x</div>"})[0] == 400
    assert c.post("/api/appearance/custom", {"slot": "mascot.think", "text": ""})[0] == 200   # 拿掉
    html, _n, _csp = _page(c)
    assert 'data-slot-src="mascot.think"' not in html


def test_custom_paste_beats_theme_and_server_mode_is_per_user(theme_bot, owner):
    bot = theme_bot(raw={"mode": "server"})
    ui = ui_of(bot)
    c = Client(ui)
    c.login(owner)
    _install(c)
    c.post("/api/appearance", {"theme": "sample-lantern", "mode": "dark"})
    mine = '<svg viewBox="0 0 4 4"><rect class="mine" width="4" height="4"/></svg>'
    c.post("/api/appearance/custom", {"slot": "mascot.idle", "text": mine})
    html, _n, _csp = _page(c)
    assert 'data-slot-src="mascot.idle"><svg viewBox="0 0 4 4">' in html          # 自己貼的蓋過外觀包的
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    m = Client(ui)
    m.login(OTHER_ID)
    look = m.get("/api/appearance")[1]
    assert look["theme"] == "sample-lantern" and look["scope"] == "user" and set(look["inherited"]) == {"theme", "mode", "custom"}
    html, _n, _csp = _page(m)
    assert 'data-skin="sample-lantern"' in html                                # 沒選過＝跟擁有者一樣
    assert m.post("/api/appearance", {"theme": ""})[0] == 200                  # 成員自己換回原本的
    html, _n, _csp = _page(m)
    assert "data-skin" not in html and 'data-theme="dark"' in html             # 模式還是跟擁有者
    html, _n, _csp = _page(c)
    assert 'data-skin="sample-lantern"' in html                                # 不影響擁有者
    assert c.get("/api/appearance")[1]["scope"] == "owner-default"


def test_stored_custom_is_resanitized_every_render(theme_bot, owner):
    bot = theme_bot()
    ui = ui_of(bot)
    c = Client(ui)
    c.login(owner)
    ui.prefs.set(owner, appearance.PREF_KEY, {"custom": {"mascot.idle": "<svg><script>alert(1)</script></svg>"},
                                              "theme": "../../evil"})
    html, _n, _csp = _page(c)                                                  # 存檔被手改：照樣打得開、不放進去
    assert 'data-slot-src="mascot.idle"' not in html and "alert(1)" not in html and 'id="synox-theme"' not in html


def test_appearance_head_never_breaks_out_of_style():
    head = appearance.head_html("n", "a { } </style><script>x</script>", {})
    assert "<script>" not in head and "<style" not in head
