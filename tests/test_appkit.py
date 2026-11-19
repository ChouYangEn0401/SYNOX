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


def _hex_lum(hex_color):
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def _contrast(a, b):
    la, lb = sorted((_hex_lum(a), _hex_lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _shell_tokens(css):
    """.synox-bar／.synox-mask 自己的 --synox-* 顏色：淺色一組、prefers-color-scheme: dark 裡一組。"""
    blocks = re.findall(r"\.synox-bar, \.synox-mask \{([^}]*)\}", css)
    assert len(blocks) == 2, "淺色、深色各一組"
    return [dict(re.findall(r"(--synox-[a-z-]+):\s*(#[0-9a-fA-F]{3,6})", b)) for b in blocks]


def test_shell_bar_colors_are_readable_in_light_and_dark():
    # 回歸：記帳本的 .btn.danger { color: var(--bad) } 蓋掉 kit 的白字 → 紅底紅字。頁首列改用自己的 class 與顏色
    css = _read("appkit.css")
    for tokens in _shell_tokens(css):
        for ink, bg in (("--synox-danger-ink", "--synox-danger"), ("--synox-ink", "--synox-surface"),
                        ("--synox-muted", "--synox-surface"), ("--synox-link", "--synox-surface"),
                        ("--synox-primary-ink", "--synox-primary")):
            ratio = _contrast(tokens[ink], tokens[bg])
            assert ratio >= 4.5, (ink, bg, round(ratio, 2))
    danger = re.search(r"\.synox-bar \.synox-btn\.synox-btn-danger \{([^}]*)\}", css).group(1)
    assert "color: var(--synox-danger-ink) !important" in danger
    assert "background: var(--synox-danger) !important" in danger
    js = _read("appkit.js")
    assert '"synox-btn synox-btn-danger"' in js and '"btn danger"' not in js     # 不再用工具也會用的 .btn／.danger


def test_shell_bar_survives_a_tool_stylesheet_like_money():
    """工具的樣式表排在 kit.css 後面，就算寫了 .btn.danger／.muted、或在 :root 改 --bad：頁首列的按鈕顏色都是 !important，
    也不引用工具會改的 --bad、--bg、--text 這些名字。"""
    css = _read("appkit.css")
    rules = re.findall(r"([^{}]*\.synox-(?:bar|mask)[^{}]*)\{([^}]*)\}", css)
    buttons = [(sel.strip(), body) for sel, body in rules if re.search(r"\.synox-btn\.synox-btn-\w+\s*$", sel.strip())]
    assert len(buttons) == 3, buttons                                   # ghost、danger、mask 的 primary
    for sel, body in buttons:
        for prop in ("background", "color"):
            assert re.search(r"(?:^|[;\s])" + prop + r":[^;]*!important", body), (sel, prop)
    for sel, body in rules:
        for name in ("--bad)", "--bg)", "--text)", "--surface)", "--muted)", "--accent)"):
            assert "var(" + name not in body, (sel, name)
