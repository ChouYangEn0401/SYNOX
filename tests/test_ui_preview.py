"""docs/ui/ 的靜態預覽跟真的介面同步（改了 app.html／server.py 的樣式要重跑 scripts/make_ui_preview.py）。

只產生字串、比對檔案：不開瀏覽器、不開埠。
"""
import importlib.util
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _script():
    spec = importlib.util.spec_from_file_location("make_ui_preview", os.path.join(ROOT, "scripts", "make_ui_preview.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read(name):
    with open(os.path.join(ROOT, "docs", "ui", name), "r", encoding="utf-8") as f:
        return f.read()


def test_preview_files_match_current_ui():
    mod = _script()
    assert _read("preview.html") == mod.app_preview(), "重跑 scripts/make_ui_preview.py"
    assert _read("preview-login.html") == mod.login_preview(), "重跑 scripts/make_ui_preview.py"


def test_preview_has_no_external_resources():
    for name in ("preview.html", "preview-login.html", "preview-error.html", "preview-phone.html"):
        html = _read(name)
        assert not re.search(r"<(script|link|img|iframe)[^>]+(src|href)=\"https?:", html), name
        assert "cdn" not in html.lower(), name


def test_app_follows_system_theme_and_has_one_token_set():
    with open(os.path.join(ROOT, "src", "synox", "web", "static", "app.html"), "r", encoding="utf-8") as f:
        html = f.read()
    assert "@media (prefers-color-scheme: dark)" in html
    style = html.split("</style>")[0]
    body = style.split("/* ── 基本")[1]                  # token 區以外不寫死顏色（只用 var(--…)）
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b", body) == [], "顏色寫進上面的 token"
