"""「遇到問題？」（設定頁 → 🙋 遇到問題？；src/synox/web/report.py、static/report.js）。

- 摘要只在擁有者按「幫我準備好回報內容」時產生（POST＋CSRF）；成員只拿到版本，看不到這台的設定、工具、錯誤紀錄。
- 摘要裡沒有 token、API 金鑰、存在保管箱的值、對話內容（[ROUTE]／[AGENT] 那幾種 log 行整行不收）、使用者名稱的路徑。
- SYNOX 自己不連網：開 GitHub 的是使用者自己按的連結。
"""
import json
import logging
import os
import re
import shutil
import subprocess

import pytest
from isdtelekit.users.roles import BasicRoles

from conftest import OTHER_ID
from synox import __version__
from synox.web import report

from test_web import Client, owner_client, ui_of  # noqa: F401（owner_client 是 fixture）

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TG_TOKEN = "123456789:AAH" + "x" * 32
SK_KEY = "sk-" + "A1b2C3d4" * 4
VAULT_SECRET = "my-very-own-secret-value"


@pytest.fixture(autouse=True)
def _fresh_log():
    before = logging.root.manager.disable           # 別的測試可能留下 logging.disable(…)：這裡先打開、測完還原
    logging.disable(logging.NOTSET)
    report.recent_log().clear()
    yield
    report.recent_log().clear()
    logging.disable(before)


# ── 遮罩 ─────────────────────────────────────────────────────────────

# 拆開寫：整份 repo 會被 clean-room 檢查掃「含使用者名稱的本機路徑」
WIN_HOME = "C:" + "\\Users\\" + "王小明"
WIN_HOME2 = "c:" + "/users/" + "Ann"
NIX_HOME = "/home" + "/alice"


def test_scrub_hides_tokens_secrets_paths_and_ids():
    text = (f"telegram https://api.telegram.org/bot{TG_TOKEN}/getMe failed; key {SK_KEY}; "
            f"saved {VAULT_SECRET}; file {WIN_HOME}\\SYNOX\\data\\x.json; also {WIN_HOME2}/AppData/y; "
            f"linux {NIX_HOME}/synox/z.py; mail ann@example.com; user 987654321 said hi; "
            "url http://u:pw@host.example/path?token=abc&x=1")
    out = report.scrub(text, secrets=[VAULT_SECRET], root="", home="")
    for leak in (TG_TOKEN, "AAH" + "x" * 10, SK_KEY, VAULT_SECRET, "王小明", "Ann", "alice", "ann@example.com",
                 "987654321", "token=abc", "u:pw"):
        assert leak not in out, leak
    assert out.count("%USERPROFILE%") == 3
    assert "x.json" in out and "z.py" in out                    # 檔名還在（好找問題）


def test_scrub_replaces_this_machines_home_and_synox_folder(tmp_path):
    home = str(tmp_path / "Someone Name")
    root = os.path.join(home, "Apps", "SYNOX")
    out = report.scrub(f"open {root}{os.sep}data{os.sep}a.enc and {home}{os.sep}Desktop", root=root, home=home)
    assert "Someone Name" not in out
    assert "<SYNOX 資料夾>" in out and "%USERPROFILE%" in out


# ── 最近的錯誤（記憶體裡，不寫檔）──────────────────────────────────────

def test_recent_log_keeps_warnings_only_and_never_chat_lines():
    report.install_log_buffer()
    report.install_log_buffer()                                 # 重複叫沒關係
    assert sum(isinstance(h, report.RecentLog) for h in logging.getLogger().handlers) == 1
    log = logging.getLogger("synox.test")
    log.info("[WEB] just info")
    log.warning("[ROUTE] /note 我的秘密日記")
    log.warning("[AGENT] tool args 我的對話")
    log.warning("[WEB] port %s busy", 8830)
    try:
        raise KeyError("內容不收")
    except KeyError:
        log.exception("[WEB] POST /api/x failed")
    lines = report.recent_lines()
    joined = "\n".join(lines)
    assert "just info" not in joined and "秘密" not in joined and "對話" not in joined
    assert any("port 8830 busy" in ln for ln in lines)
    failed = [ln for ln in lines if "failed" in ln][0]
    assert "KeyError" in failed and "test_web_report.py" in failed and "內容不收" not in failed


def test_recent_log_folds_repeats_and_caps_length():
    report.install_log_buffer()
    log = logging.getLogger("synox.test")
    for _ in range(5):
        log.warning("[WEB] same thing")
    log.warning("[WEB] " + "長" * 1000)
    lines = report.recent_lines()
    assert len([ln for ln in lines if "same thing" in ln]) == 1 and "5 次" in lines[0]
    assert max(len(ln) for ln in lines) <= report.LINE_MAX + 40


# ── API ──────────────────────────────────────────────────────────────

def _owner(make_bot, owner, **kw):
    bot = make_bot(**kw)
    c = Client(ui_of(bot))
    c.login(owner)
    return bot, c


def test_owner_summary_has_versions_kinds_packs_and_redacted_errors(make_bot, owner, monkeypatch):
    bot, c = _owner(make_bot, owner)
    vault = bot.app.extras["vault"]
    vault.save_json("secrets", {"llm_api_key": VAULT_SECRET})
    logging.getLogger("synox.test").error("[WEB] upstream said %s with %s at %s", VAULT_SECRET, TG_TOKEN,
                                          os.path.join(os.path.expanduser("~"), "SYNOX", "x.log"))
    status, d = c.post("/api/report", {})
    assert status == 200 and d["full"] is True
    text = d["summary"]
    assert f"SYNOX 版本：{__version__}" in text and "Python：" in text and "作業系統：" in text
    assert "AI：fake" in text and "網頁" in text
    assert "money" in text and "notes" in text                   # 裝了哪些工具（名字＋版本）
    assert "upstream said" in text                              # 最近的錯誤有收進來
    for leak in (VAULT_SECRET, TG_TOKEN, str(owner), os.path.expanduser("~")):
        assert leak not in text, leak
    assert d["issue"] == {"url": report.ISSUE_NEW, "template": report.ISSUE_TEMPLATE, "field": report.SUMMARY_FIELD,
                          "max_url": report.MAX_URL}


def test_member_gets_only_a_generic_summary(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    logging.getLogger("synox.test").error("[WEB] owner-side failure")
    m = Client(ui_of(bot))
    m.login(OTHER_ID)
    status, d = m.post("/api/report", {})
    assert status == 200 and d["full"] is False
    text = d["summary"]
    assert f"SYNOX 版本：{__version__}" in text and "伺服器版" in text
    for hidden in ("owner-side failure", "money", "notes", "AI：", "Python：", "作業系統：", str(owner), str(OTHER_ID)):
        assert hidden not in text, hidden


def test_report_api_needs_login_post_and_csrf(owner_client):
    bot, c = owner_client
    ui = ui_of(bot)
    assert ui.handle("POST", "/api/report", {}, b"{}")[0] == 401
    assert c.post("/api/report", {}, headers={"X-SYNOX-CSRF": "wrong"})[0] == 403
    assert c.post("/api/report", {}, headers={"Origin": "http://evil.example"})[0] == 403
    assert c.get("/api/report")[0] == 404                       # 只有按按鈕（POST）才產生


def test_report_makes_no_network_request(owner_client, monkeypatch):
    import socket
    import urllib.request

    def boom(*a, **k):
        raise AssertionError("「遇到問題？」不該連網")
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    _bot, c = owner_client
    assert c.post("/api/report", {})[0] == 200


# ── 網頁、GitHub 範本 ─────────────────────────────────────────────────

def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def test_help_tab_and_entry_points_exist():
    html = _read("src", "synox", "web", "static", "app.html")
    section = html.split('<section id="view-settings"')[1].split("</section>")[0]
    assert '<a href="#settings:help" data-tab="help" role="tab"' in section
    assert 'id="set-help"' in section and 'id="report-text"' in section
    assert 'href="#settings:help"' in html.split('<div id="side-foot"')[1].split("</aside>")[0]   # 側欄底下的小連結
    for link in (report.SIGNUP, report.ISSUES, report.SECURITY, report.GUIDE):
        assert f'href="{link}"' in section, link
    assert "{{INCLUDE:report.js}}" in html and "{{INCLUDE:report.css}}" in html


def test_report_js_constants_match_python_and_template():
    js = _read("src", "synox", "web", "static", "report.js")
    assert f'"{report.ISSUE_NEW}"' in js
    assert f'TEMPLATE = "{report.ISSUE_TEMPLATE}"' in js and f'FIELD = "{report.SUMMARY_FIELD}"' in js
    assert f"MAX_URL = {report.MAX_URL}" in js
    form = _read(".github", "ISSUE_TEMPLATE", report.ISSUE_TEMPLATE)
    ids = re.findall(r"^\s+id:\s*([a-z_]+)\s*$", form, re.M)
    assert report.SUMMARY_FIELD in ids and {"what", "expected", "steps"} <= set(ids)
    assert len(ids) == len(set(ids))
    assert "SECURITY.md" in form


def test_issue_config_links_security_and_guide():
    cfg = _read(".github", "ISSUE_TEMPLATE", "config.yml")
    assert report.GUIDE in cfg and "security" in cfg.lower()
    for name in ("bug_report.md", "feature_request.md"):          # 舊的範本照用
        assert _read(".github", "ISSUE_TEMPLATE", name).startswith("---\nname:")


def test_report_js_with_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("這台沒有 node：tests/js/test_report.js 沒跑")
    proc = subprocess.run([node, os.path.join(ROOT, "tests", "js", "test_report.js")], cwd=ROOT,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
