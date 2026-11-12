# -*- coding: utf-8 -*-
"""圖文教學（docs/tutorials/<名字>/index.html；synox/tutorials.py）：找檔、網頁路由、精靈按鈕、打包、HTML 自足。"""

import os
import re
import sys

import pytest

from synox import tutorials

from test_web import ui_of

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TELEGRAM_HTML = os.path.join(ROOT, "docs", "tutorials", "telegram", "index.html")


def test_path_of_finds_telegram_and_refuses_bad_names():
    assert tutorials.path_of("telegram") == TELEGRAM_HTML
    assert "telegram" in tutorials.names()
    for bad in ("", "Telegram", "../telegram", "telegram/..", "no-such-tutorial", "a" * 40, "tele gram"):
        assert tutorials.path_of(bad) is None, bad
    assert tutorials.read("no-such-tutorial") is None
    assert tutorials.read("telegram").startswith(b"<!doctype html>")


def test_path_of_other_folder(tmp_path):
    folder = tmp_path / "tutorials"
    (folder / "discord").mkdir(parents=True)
    assert tutorials.path_of("discord", str(folder)) is None                 # 資料夾在、沒有 index.html
    (folder / "discord" / "index.html").write_text("<p>hi</p>", encoding="utf-8")
    assert tutorials.path_of("discord", str(folder)) == str(folder / "discord" / "index.html")
    assert tutorials.names(str(folder)) == ["discord"]
    assert tutorials.names(str(tmp_path / "nowhere")) == []


def test_open_local_uses_a_file_url(tmp_path):
    opened = []
    assert tutorials.open_local("telegram", opener=opened.append) is True
    (url,) = opened
    assert url.startswith("file:") and url.endswith("/docs/tutorials/telegram/index.html")
    assert tutorials.open_local("no-such-tutorial", opener=opened.append) is False
    assert len(opened) == 1


def test_web_serves_tutorial_without_login(make_bot):
    ui = ui_of(make_bot())
    for path in ("/tutorials/telegram/", "/tutorials/telegram"):
        status, headers, body = ui.handle("GET", path, {"Host": "127.0.0.1:8830"})
        assert status == 200, path
        h = dict(headers)
        assert h["Content-Type"].startswith("text/html")
        assert "script-src" not in h["Content-Security-Policy"] and "default-src 'none'" in h["Content-Security-Policy"]
        assert h["X-Frame-Options"] == "DENY"
        assert "@BotFather".encode() in body and "示意圖".encode() in body
    for bad in ("/tutorials/no-such-tutorial/", "/tutorials/Telegram/", "/tutorials/../config.json", "/tutorials/"):
        status, _h, _b = ui.handle("GET", bad, {"Host": "127.0.0.1:8830"})
        assert status == 404, bad
    status, _h, _b = ui.handle("POST", "/tutorials/telegram/", {"Host": "127.0.0.1:8830"}, b"")
    assert status == 404


def test_app_page_links_to_the_telegram_tutorial(make_bot):
    ui = ui_of(make_bot())
    _status, _headers, body = ui.app_page()
    assert b'href="/tutorials/telegram/"' in body


def test_html_is_self_contained_and_honest():
    with open(TELEGRAM_HTML, encoding="utf-8") as f:
        html = f.read()
    assert "<script" not in html.lower()                                    # 網頁那條路的 CSP 不放行程式
    assert not re.search(r'<(link|img|script|iframe)\b[^>]*\b(src|href)="(https?:)?//', html)   # 沒有外部資源
    assert re.search(r"<title>[^<]{2,40}</title>", html)
    assert "示意圖" in html and "@BotFather" in html and "/newbot" in html
    for cmd in ("/token", "/revoke", "/setprivacy", "/setname", "/setuserpic", "/mybots"):
        assert cmd in html, cmd
    assert "prefers-color-scheme: dark" in html and '[data-theme="dark"]' in html
    assert not re.search(r"(?<![0-9A-Za-z])\d{8,10}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])", html)   # 沒有像真的 token


def test_release_ships_the_tutorial():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import make_zip
    shipped = {rel for _src, rel in make_zip.release_files()}
    assert "docs/tutorials/telegram/index.html" in shipped and "docs/tutorials/README.md" in shipped


def test_wizard_token_page_has_a_tutorial_button(tmp_path, monkeypatch):
    tk = pytest.importorskip("tkinter")
    from synox.wizard import pages
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no display: {e}")
    root.withdraw()
    opened = []
    monkeypatch.setattr(pages.tutorials, "open_local", lambda name, **kw: opened.append(name))
    try:
        wiz = pages.Wizard(root, config_path=str(tmp_path / "config.json"), lang="zh-TW")
        wiz.page_token()
        buttons = {w.cget("text"): w for w in wiz.body.winfo_children() if w.winfo_class() == "TButton"}
        assert "看圖文教學" in buttons and buttons["看圖文教學"].winfo_manager() == "pack"
        buttons["看圖文教學"].invoke()
        assert opened == ["telegram"]
        monkeypatch.setattr(pages.tutorials, "path_of", lambda name, *a: None)   # 沒有這份教學：按鈕收起來
        wiz.page_token()
        buttons = {w.cget("text"): w for w in wiz.body.winfo_children() if w.winfo_class() == "TButton"}
        assert buttons["看圖文教學"].winfo_manager() == ""
    finally:
        root.destroy()
