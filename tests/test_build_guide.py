# -*- coding: utf-8 -*-
"""一步一步安裝教學頁（docs/guide/index.html）的「選讀：SYNOX 網頁導覽」讀的是內建新手教學的步驟檔
（src/synox/tour/tours/basics.json；scripts/build_guide.py 放進頁面）：同一份字、兩個出口。不連網、不開瀏覽器。"""
import json
import os
import re
import sys

from synox.config import ROOT
from synox.tour import anchors

sys.path.insert(0, os.path.join(ROOT, "scripts"))
import build_guide  # noqa: E402

GUIDE = os.path.join(ROOT, "docs", "guide", "index.html")


def _html():
    with open(GUIDE, encoding="utf-8") as f:
        return f.read()


def test_guide_is_in_sync_with_the_tutorial():
    assert build_guide.main(["--check"]) == 0, "跑 python scripts/build_guide.py（再 scripts/page_stamp.py）"


def test_embedded_steps_are_data_and_cannot_break_out():
    html = _html()
    block = build_guide.BLOCK_RE.search(html).group(2)
    assert "</" not in block and "<!--" not in block
    data = json.loads(block)
    assert data["id"] == "basics" and data["steps"]
    ids = [s["id"] for s in data["steps"]]
    assert "ask-help" in ids and "catalog" in ids                    # 擁有者看到的那一份（含裝工具的步驟）


def test_every_anchor_in_the_tutorial_has_a_place_on_the_guide_mock():
    html = _html()
    mock = html[html.index('"web-tour": function'):html.index('"tg-help": function')]
    data = json.loads(build_guide.BLOCK_RE.search(html).group(2))
    used = {a for s in data["steps"] for a in s["anchors"]}
    drawn = set(re.findall(r'data-hl="([a-z.]+)"', mock))
    drawn |= {f"nav.{n}" for n in ("chat", "tools", "settings")}
    drawn |= {f"settings.tab.{t}" for t in ("ai", "channels", "packs", "system", "appearance", "commands", "help")}
    assert used <= drawn, used - drawn
    assert used <= set(anchors.ANCHORS)


def test_help_step_describes_the_new_help():
    html = _html()
    step = html[html.index('{ id: "help"'):html.index('{ id: "done"')]
    assert "每個工具一顆按鈕" in step and "/help all" in step and "下一頁" not in step
    assert 'jump: { to: "web-welcome"' in step


# ---- 版本與下載連結（scripts/release.py 的 download_info → #release-info）、步驟資料的靜態檢查 ---------------

def _release_block(html):
    return json.loads(build_guide.RELEASE_RE.search(html).group(2))


def test_download_names_and_links_are_built_from_the_version():
    """檔名與網址都是從版本算出來的（發佈頁上的檔名＝scripts/release.py 的 asset_names），不寫死、不用 releases/latest。"""
    import release
    html = _html()
    info = _release_block(html)
    v = info["version"]
    release.Version.parse(v)                                          # 是合法的版本號
    assert (info["zip"], info["exe"]) == release.asset_names(v) == (f"SYNOX-{v}.zip", f"SYNOX-Setup-{v}.exe")
    assert info["tag"] == "v" + v and info["prerelease"] is ("-" in v)
    base = "https://github.com/ChouYangEn0401/SYNOX/releases"
    assert info["zip_url"] == f"{base}/download/v{v}/SYNOX-{v}.zip"
    assert info["exe_url"] == f"{base}/download/v{v}/SYNOX-Setup-{v}.exe"
    assert info["page_url"] == f"{base}/tag/v{v}" and info["releases_url"] == base
    assert "releases/latest" not in html                               # Latest 不一定是最新的測試版
    steps = _steps_source(html) + html[html.index("var MOCKS = {"):]
    assert not re.search(r"SYNOX-(?:Setup-)?\d", steps), "檔名寫死在步驟裡了：用 REL.zip／REL.exe"
    assert not re.search(r"\d+\.\d+\.\d+-(?:alpha|beta)\.\d+", steps), "版本號寫死在步驟裡了：用 REL.version"


def test_release_info_follows_the_version_files(tmp_path):
    """build_guide 放進頁面的那一段＝release.download_info（讀 pyproject.toml 與 __init__.py）；release.py 的檢查讀得到。"""
    import release
    (tmp_path / "src" / "synox").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "synox"\nversion = "1.4.0-beta.2"\n', encoding="utf-8")
    (tmp_path / "src" / "synox" / "__init__.py").write_text('__version__ = "1.4.0-beta.2"\n', encoding="utf-8")
    data = json.loads(build_guide.release_json(str(tmp_path)))
    assert list(data)[0] == "version" and data["zip"] == "SYNOX-1.4.0-beta.2.zip"
    assert data["zip_url"].endswith("/releases/download/v1.4.0-beta.2/SYNOX-1.4.0-beta.2.zip")
    html = build_guide.build(_html(), build_guide.steps_json(), build_guide.release_json(str(tmp_path)))
    assert build_guide.shown_version(html) == "1.4.0-beta.2"
    guide_rx = dict((rel, rx) for rel, rx, _how in release.BUILT_PAGES)["docs/guide/index.html"]
    assert guide_rx.search(html).group(1) == "1.4.0-beta.2"


def test_stale_release_notices_are_gone():
    html = _html()
    for old in ("還沒發佈", "SYNOX-main", "archive/refs/heads/main.zip", "Download ZIP"):
        assert old not in html, old


def _steps_source(html):
    """PATHS 與 STEPS 陣列的原始文字（不執行 JavaScript，只用字串找）。"""
    return html[html.index("var PATHS = {"):html.index("/* ── 選讀：SYNOX 網頁導覽")]


def test_step_data_points_at_things_that_exist():
    """每一步的示意畫面都有、id 不重複、jump／back／next／home／岔路指得到（"@from"＝從哪來回哪去，要有 home）。"""
    html = _html()
    src = _steps_source(html)
    ids = re.findall(r'^    \{ id: "([a-z0-9-]+)"', src, re.M)       # 一行開頭的才是步驟（targets 裡的 id 是要標的東西）
    assert len(ids) == len(set(ids)) and {"ai", "ai-claude", "ai-install", "ai-own", "ai-none", "finish"} <= set(ids)
    tour = ["web-" + s["id"] for s in json.loads(build_guide.BLOCK_RE.search(html).group(2))["steps"]]
    known = set(ids) | set(tour)
    mocks = re.findall(r'^    "([a-z0-9-]+)": function', html, re.M)
    assert len(mocks) == len(set(mocks)), "同名的示意畫面會互相蓋掉"
    used = set(re.findall(r'mock: "([a-z0-9-]+)"', src))
    assert used <= set(mocks), used - set(mocks)
    for key in ("to", "back", "next", "home", "from"):
        for ref in re.findall(rf'\b{key}: "([a-z0-9@-]+)"', src):
            assert ref == "@from" or ref in known, f"{key}: {ref}"
    paths = dict(re.findall(r'"([a-z-]+)":\s+\{ label: "[^"]+", from: "([a-z-]+)"', src))
    on_path = set(re.findall(r'\bpath: "([a-z-]+)"', src))
    assert on_path == set(paths), on_path ^ set(paths)                # 每條岔路都有步驟、每個步驟的岔路都登記了
    for step in re.findall(r'\{ id: "[a-z0-9-]+", branch: true,[^\n]*', src):
        if '"@from"' in step:
            assert "home: " in step, step


def test_ai_step_is_a_three_way_fork_that_rejoins_the_main_line():
    src = _steps_source(_html())
    fork = src[src.index('{ id: "ai", chapter'):src.index('{ id: "ai-claude"')]
    assert re.findall(r'\{ path: "([a-z-]+)"', fork) == ["claude", "own", "none"]
    assert "我有 Claude 訂閱" in fork and "我有自己的模型或 API" in fork and "先不用 AI" in fork
    for name in ("claude", "own", "own-key", "own-local", "own-llop", "none"):
        assert re.search(rf'"{name}":\s+\{{ label: "[^"]+", from: "ai(-own)?", to: "finish" \}}', src), name
    # LLOP 的指令照 LLOP 的 CLI；模型打錯、選裝套件、訂閱登入的提醒、之後怎麼更新都在
    assert "llmop client add-plain --profile home --api-link" in src and "llmop client enroll --account-url" in src
    assert "deps sync --add llop" in src and "模型名稱打錯不會讓 SYNOX 起不來" in src and "訂閱登入只給本人使用" in src
    assert "檢查更新" in src and "回到上一版" in src and "💻 電腦與備份" in src


def test_landing_source_has_no_hard_coded_version_or_download():
    """介紹頁原稿（docs/landing/page.html）的版本與下載連結是記號，scripts/make_landing.py 組頁面時才帶入。"""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import make_landing
    with open(os.path.join(ROOT, "docs", "landing", "page.html"), encoding="utf-8") as f:
        page = f.read()
    for mark in make_landing.release_text():
        assert mark in page, mark
    assert '<b>{{version}}</b>' in page and 'class="big-dl" href="{{zip-url}}"' in page
    assert "archive/refs/heads/main.zip" not in page and "releases/latest" not in page
    assert "<span>SYNOX {{version}}（{{version-label}}）</span>" in page                      # 頁尾
    assert not re.search(r"SYNOX-(?:Setup-)?\d", page), "檔名寫死在介紹頁原稿裡了"            # 工具自己的版本號不算
    with open(os.path.join(ROOT, "docs", "landing", "index.html"), encoding="utf-8") as f:
        built = f.read()
    assert "{{" not in built                                           # 組出來的頁面沒有漏掉的記號
    import release
    shown = dict((rel, rx) for rel, rx, _how in release.BUILT_PAGES)["docs/landing/index.html"].search(built).group(1)
    release.Version.parse(shown)
    assert f'class="big-dl" href="{release.RELEASES_URL}/download/v{shown}/SYNOX-{shown}.zip"' in built


def test_guide_runs_in_a_fake_browser():
    """scripts/check_guide.js：不開瀏覽器，把頁面的程式放進假的 DOM 跑（每一步的示意畫面與要標的東西、#step-… 網址、
    岔路進得去回得來）。要 Node；沒裝就略過。"""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("這台沒有 Node")
    done = subprocess.run([node, os.path.join(ROOT, "scripts", "check_guide.js"), GUIDE], capture_output=True, timeout=120)
    out = done.stdout.decode("utf-8", "replace") + done.stderr.decode("utf-8", "replace")
    assert done.returncode == 0, out
    for way in ("ai → ai-claude → ai-install → finish", "ai → ai-own → ai-key → finish", "ai → ai-own → ai-local → finish",
                "ai → ai-own → ai-llop → finish", "ai → ai-none → finish"):
        assert way in out, out
