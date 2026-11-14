"""網頁的開場動畫與微動畫（src/synox/web/static/splash.js／splash.css；說明 docs/ui/motion-notes.md）。

- 什麼時候播、一定收得掉：tests/js/test_splash.js，用 node 跑（找不到 node 就跳過）。
- 靜態檢查：塞進 app.html 之後一頁、同一個 nonce、沒有外部資源；有 reduced-motion 規則；CSS 只用 token 顏色；JS 只寫文字。
不開瀏覽器、不開埠、不連網。
"""
import os
import re
import shutil
import subprocess

import pytest

from synox.web import server as web_server

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "src", "synox", "web", "static")


def _read(name):
    with open(os.path.join(STATIC, name), "r", encoding="utf-8") as f:
        return f.read()


def test_splash_js_with_fake_dom():
    node = shutil.which("node")
    if not node:
        pytest.skip("這台沒有 node：tests/js/test_splash.js 沒跑")
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP")}
    proc = subprocess.run([node, os.path.join(ROOT, "tests", "js", "test_splash.js")], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_app_html_inlines_splash_files_with_the_same_nonce():
    html = web_server.render_app("n0nce")
    assert "{{INCLUDE" not in html and "{{NONCE}}" not in html
    assert "SynoxSplash" in html and ".sx-splash" in html
    for tag in re.findall(r"<(?:script|style)\b[^>]*>", html):
        assert 'nonce="n0nce"' in tag, tag
    assert not re.search(r"<(script|link|img|iframe)[^>]+(src|href)=", html)     # 沒有外部檔
    head = html.split("<body")[0]                                                # 全部的樣式
    assert "url(" not in head and "@import" not in head and "@font-face" not in head


def test_splash_hooks_sit_where_they_should():
    html = _read("app.html")
    # 樣式排在其他樣式後面（才蓋得過按鈕的 transition）；程式在 body 一開始（第一次畫面就有開場，不會先閃一下內容）
    head = html.split("</head>")[0]
    assert head.rstrip().endswith('<style nonce="{{NONCE}}">/*{{INCLUDE:splash.css}}*/</style>')
    body = html.split("<body", 1)[1]
    first = body.split("\n", 2)[1]
    assert first == '<script nonce="{{NONCE}}">/*{{INCLUDE:splash.js}}*/</script>'


def test_splash_files_cannot_break_out_of_their_tag():
    for name in ("splash.js", "splash.css"):
        text = _read(name).lower()
        for bad in ("</script", "</style", "<!--", "{{nonce}}", "{{include"):
            assert bad not in text, (name, bad)


def test_splash_css_only_uses_the_design_tokens_and_no_resources():
    css = _read("splash.css")
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b", css) == [], "顏色用 app.html 最上面的 token"
    assert not re.search(r"\b(rgba?|hsla?)\(", css)
    assert not re.search(r"(?<![-\w])(white|black)(?![-\w])", css)           # white-space 不算
    assert not re.search(r"url\(|@import|@font-face", css)


def test_motion_respects_reduced_motion():
    css = _read("splash.css")
    block = css.split("@media (prefers-reduced-motion: reduce)")[1]
    assert ".sx-splash.sx-gate { display: grid !important; }" in block       # 門照樣出現（停在最後一格等你點）
    assert "body::before, body::after" in block and "animation: none !important" in block
    assert "prefers-reduced-motion: reduce" in _read("splash.js")            # 減少動態效果 → .sx-still
    assert re.search(r"\.sx-gate\.sx-still \*[^{]*\{ animation: none !important;", css)   # 不動的最後一格
    assert ".sx-gate.sx-still .sx-flip { transform: rotateY(180deg); }" in css   # S 標誌朝前
    assert ".sx-gate.sx-still .sx-hint { opacity: 1; }" in css               # 提示亮著
    assert "@media (prefers-reduced-motion: reduce)" in _read("app.html")    # 全域規則還在


def test_splash_fades_out_by_itself_and_does_not_steal_the_mouse_afterwards():
    css = _read("splash.css")
    assert re.search(r"@keyframes sx-out \{ to \{ opacity: 0; visibility: hidden; \} \}", css)
    assert re.search(r"\.sx-splash \{[^}]*animation: sx-out [^;]*forwards", css)
    assert re.search(r"body::before, body::after \{[^}]*pointer-events: none", css)


def test_splash_js_writes_text_only_and_touches_nothing_else():
    js = _read("splash.js")
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\(|new Function", js)
    assert not re.search(r"fetch\(|XMLHttpRequest|WebSocket|http://|https://|\.style\b|setAttribute\(\"style", js)
    assert "aria-hidden" in js


def test_gate_waits_for_a_click_instead_of_fading_out_by_itself():
    css = _read("splash.css")
    assert ".sx-splash.sx-gate { animation: none; }" in css                  # 不自動淡出
    assert re.search(r"\.sx-splash\.sx-gate\.sx-leave \{[^}]*animation: sx-out [^;]*forwards", css)   # 點了才淡出
    assert re.search(r"\.sx-gate \.sx-enter:focus-visible \{[^}]*outline", css)                       # 鍵盤看得到焦點
    # 介紹頁（scripts/make_landing.py）只取到「開場時：」：門的樣式在那之後，不會跑進介紹頁
    assert css.index("/* 開場時：") < css.index(".sx-splash.sx-gate {")
    js = _read("splash.js")
    assert '"點一下打開 SYNOX"' in js and 'setAttribute("aria-label"' in js and 'el(doc, "button", "sx-enter")' in js
    assert "window.SYNOX_NO_SPLASH" in js or "root.SYNOX_NO_SPLASH" in js
    assert "SAFETY" not in js                                                 # 沒有「時間到自己收掉」


def test_brand_mark_replays_the_opening():
    html = _read("app.html")
    brand = html.split('<div class="brand">', 1)[1].split("</div>", 1)[0]
    assert brand.startswith('<button id="brand-mark" class="mark" type="button" data-splash-replay '
                            'title="再看一次開場" aria-label="再看一次開場">')
    assert 'data-slot="mascot.idle"' in brand and 'data-slot="wordmark"' in brand     # 外觀的 slot 照舊
    assert "[data-splash-replay]" in _read("splash.js")
    rendered = web_server.render_app("n0nce")
    assert rendered.count('<button id="brand-mark" class="mark"') == 1


def test_tutorial_offer_waits_until_the_gate_is_dismissed():
    tour = _read("tour.js")
    assert "gate.isOpen()" in tour and "document.addEventListener(gate.DONE" in tour
    assert 'DONE = "synox:splash-done"' in _read("splash.js")


def test_previews_and_smoke_tests_skip_the_gate():
    with open(os.path.join(ROOT, "scripts", "make_ui_preview.py"), encoding="utf-8") as f:
        assert "window.SYNOX_NO_SPLASH = true;" in f.read()
    with open(os.path.join(ROOT, "scripts", "ui_tour_smoke.py"), encoding="utf-8") as f:
        assert 'add_init_script("window.SYNOX_NO_SPLASH = true;")' in f.read()
