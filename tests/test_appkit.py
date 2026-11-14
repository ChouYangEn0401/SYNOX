"""工具服務的共用元件（appkit.js／appkit.css）：node 跑 tests/js/test_appkit.js；檔案本身的規則直接讀檔檢查。"""

import os
import re
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.usefixtures("no_sockets")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "src", "synox", "web", "static")


def _read(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as f:
        return f.read()


def test_appkit_js_with_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("這台沒有 node：tests/js/test_appkit.js 沒跑")
    proc = subprocess.run([node, os.path.join(ROOT, "tests", "js", "test_appkit.js")], cwd=ROOT,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_appkit_js_rules():
    js = _read("appkit.js")
    for word in ("setInterval", "innerHTML", "eval(", "serviceWorker", "cookie", "http://", "https://"):
        assert word.lower() not in js.lower(), word
    assert js.count("/*{{CONSOLE_URL}}*/") == 1
    assert len(js.splitlines()) <= 650


def test_appkit_css_rules():
    css = _read("appkit.css")
    assert "url(" not in css and "@import" not in css
    for token in ("--bg", "--surface", "--line", "--text", "--muted", "--accent", "--ok", "--warn", "--bad"):
        assert token in css
    assert "prefers-color-scheme" in css and len(css.splitlines()) <= 400
    for cls in (".bar", ".card", ".btn", ".primary", ".danger", ".ghost", ".field", ".badge", ".table", ".toast",
                ".modal", ".mask", ".tabs", ".meter"):
        assert re.search(re.escape(cls) + r"\b", css), cls
