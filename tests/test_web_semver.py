"""網頁的「有新版」（工具庫、衣櫃）用的版本比較：static/semver.js，跟伺服器 packs/upgrade.semver_key 同一套 SemVer
（docs/versioning.md §1）。之前 app.html 自己比，只看 X.Y.Z 和「有沒有尾巴」：0.1.3-alpha.1 → 0.1.3-beta.1、
alpha.2 → alpha.10 都不算新版，裝好一個之後重算時「更新到 v…」就不見了。"""

import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_semver_js_and_the_shipped_ver_newer():
    node = shutil.which("node")
    if not node:
        pytest.skip("這台沒有 node：tests/js/test_semver.js 沒跑")
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP")}
    proc = subprocess.run([node, os.path.join(ROOT, "tests", "js", "test_semver.js")], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_semver_js_is_inlined_and_used():
    from synox.web import server as web_server
    html = web_server.render_app("n0nce")
    assert "SynoxSemver" in html and "{{INCLUDE:semver.js}}" not in html
    assert "function verKey(" not in html                      # 不再有自己的一套
    assert "return SynoxSemver.newer(a, b);" in html
    assert html.count("!t.blocked && verNewer(") == 2           # 這台用不了的新版：重算時也不算「有新版」
