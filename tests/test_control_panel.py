"""網頁「主控」頁（src/synox/web/static/control.js／control.css）。

- 純函式與 API 呼叫：tests/js/test_control.js 用假 fetch 測，這裡用 node 跑（找不到 node 就跳過）。
- 塞進 app.html 的方式（server.app_html）：一頁、同一個 nonce、沒有外部資源。
不開瀏覽器、不開埠、不連網；後端 /api/runtime/* 不在這個分支，這裡只測前端。
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


def test_control_js_with_fake_fetch():
    node = shutil.which("node")
    if not node:
        pytest.skip("這台沒有 node：tests/js/test_control.js 沒跑")
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP")}
    proc = subprocess.run([node, os.path.join(ROOT, "tests", "js", "test_control.js")], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_app_html_inlines_control_files_with_the_same_nonce():
    html = web_server.app_html("n0nce")
    assert "{{INCLUDE" not in html and "{{NONCE}}" not in html
    assert "SynoxControl" in html and ".ctl-roles" in html                  # control.js、control.css 都塞進去了
    for tag in re.findall(r"<(?:script|style)\b[^>]*>", html):
        assert 'nonce="n0nce"' in tag, tag
    assert not re.search(r"<(script|link|img|iframe)[^>]+(src|href)=", html)   # 沒有外部檔（連自己的也沒有）


def test_app_page_from_the_server_carries_the_control_page(make_bot):
    ui = make_bot().app.extras["synox_web"]
    status, headers, body = ui.handle("GET", "/", {})
    nonce = re.search(r"script-src 'nonce-([^']+)'", dict(headers)["Content-Security-Policy"]).group(1)
    html = body.decode("utf-8")
    assert status == 200 and "SynoxControl" in html and f'<script nonce="{nonce}">' in html


def test_included_files_cannot_break_out_of_their_tag():
    for name in ("control.js", "control.css"):
        text = _read(name).lower()
        assert "</script" not in text and "</style" not in text and "{{nonce}}" not in text, name


def test_include_only_takes_plain_static_file_names():
    assert web_server.INLINE_RE.fullmatch("/*{{INCLUDE:control.js}}*/")
    for bad in ("/*{{INCLUDE:../server.py}}*/", "/*{{INCLUDE:a/b.js}}*/", "/*{{INCLUDE:x.html}}*/",
                "/*{{INCLUDE:Control.JS}}*/"):
        assert not web_server.INLINE_RE.fullmatch(bad), bad


def test_control_css_only_uses_the_design_tokens():
    css = _read("control.css")
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b", css) == [], "顏色用 app.html 最上面的 token"
    assert not re.search(r"rgba?\(", css)
    assert "@media (max-width: 760px)" in css                               # 手機寬度


def test_control_js_writes_text_only():
    js = _read("control.js")
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\(|new Function", js)


def test_control_nav_is_hidden_until_the_owner_logs_in():
    html = _read("app.html")
    nav = re.search(r'<a href="#control"[^>]*>', html).group(0)
    assert 'class="hidden"' in nav and 'id="nav-control"' in nav
    assert "control.canSee(d)" in html and "control.canSee(me)" in html      # 側欄與網址 #control 都看 owner
