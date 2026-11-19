# -*- coding: utf-8 -*-
"""發版小幫手 scripts/release.py（規則：docs/versioning.md）。全部在 tmp_path 的小 repo 上跑，不改這個 repo 的版本、不跑 git。"""
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import installer_ci  # noqa: E402
import release  # noqa: E402

V = release.Version.parse

CHANGELOG = """# Changelog

## 未發佈（工具庫的卡片）

### 新增
- 卡片顯示「有新版」。
  第二行是細節。

```
## 這不是標題（在程式碼區塊裡）
```

## 未發佈（修一個小錯）

### 修正
- 修好「下一步」被擠掉。

## 0.2.0

舊的那一版。

## 0.1.0 — 2026-11-09

第一版。
"""


def _repo(tmp_path, version="0.2.0", sdk=("0.2.2", "0.2.2"), changelog=CHANGELOG, badge=None):
    (tmp_path / "src" / "synox" / "sdk").mkdir(parents=True)
    (tmp_path / "sdk").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        f'[build-system]\nrequires = ["setuptools>=64"]\n\n[project]\nname = "synox"\nversion = "{version}"\n'
        'dependencies = ["requests>=2.28"]\n', encoding="utf-8")
    (tmp_path / "src" / "synox" / "__init__.py").write_text(f'"""SYNOX"""\n\n__version__ = "{version}"\n', encoding="utf-8")
    (tmp_path / "src" / "synox" / "sdk" / "author.py").write_text(f'SDK_VERSION = "{sdk[0]}"   # 合約\n', encoding="utf-8")
    (tmp_path / "sdk" / "synox_sdk.py").write_text(f'SDK_VERSION = "{sdk[1]}"   # 合約\n', encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    if badge is not None:
        (tmp_path / "docs" / "landing").mkdir(parents=True)
        (tmp_path / "docs" / "landing" / "page.html").write_text(
            f'<span class="ver" title="x"><i class="dot"></i><b>{badge}</b>alpha</span>', encoding="utf-8")
    return str(tmp_path)


# ---- 版本號的規則 ------------------------------------------------------------------------------

@pytest.mark.parametrize("current,kind,expected", [
    ("0.2.0", "patch", "0.2.1"),
    ("0.2.9", "patch", "0.2.10"),
    ("0.2.3", "minor", "0.3.0"),
    ("0.2.0", "alpha", "0.2.1-alpha.1"),
    ("0.2.1-alpha.1", "alpha", "0.2.1-alpha.2"),
    ("0.2.1-alpha.2", "beta", "0.2.1-beta.1"),
    ("0.2.0", "beta", "0.2.1-beta.1"),
    ("0.2.1-beta.1", "beta", "0.2.1-beta.2"),
    ("0.2.1-beta.2", "final", "0.2.1"),
    ("0.2.1-alpha.3", "final", "0.2.1"),
])
def test_next_version(current, kind, expected):
    assert str(release.next_version(V(current), kind)) == expected


def test_next_minor_preview():
    assert str(release.next_version(V("0.2.4"), "alpha", next_minor=True)) == "0.3.0-alpha.1"
    assert str(release.next_version(V("0.2.4"), "beta", next_minor=True)) == "0.3.0-beta.1"
    with pytest.raises(release.ReleaseError):
        release.next_version(V("0.2.4"), "patch", next_minor=True)


@pytest.mark.parametrize("current,kind", [
    ("0.2.1-beta.1", "alpha"),       # beta 不能退回 alpha
    ("0.2.1-beta.1", "patch"),       # 預覽版要先 final
    ("0.2.1-alpha.1", "minor"),
    ("0.2.1", "final"),              # 已經是正式版
])
def test_refused_bumps(current, kind):
    with pytest.raises(release.ReleaseError):
        release.next_version(V(current), kind)


@pytest.mark.parametrize("bad", ["0.2", "v0.2.1", "0.2.1-rc.1", "0.2.1-beta", "0.2.1-beta.0", "01.2.3", "0.2.1a1", ""])
def test_version_format(bad):
    with pytest.raises(release.ReleaseError):
        V(bad)


def test_preview_versions_sort_like_the_pack_upgrader():
    """alpha < beta < 正式版：跟工具升級用的 semver 比較（packs/upgrade.py）一致。"""
    from synox.packs.upgrade import semver_key
    order = ["0.2.0", "0.2.1-alpha.1", "0.2.1-alpha.2", "0.2.1-beta.1", "0.2.1", "0.3.0-alpha.1"]
    assert sorted(order, key=semver_key) == order


def test_tag_rules_agree_with_the_installer_build():
    assert release.check_tag("0.2.1", "v0.2.1") is None
    assert release.check_tag("0.2.1-beta.1", "v0.2.1-beta.1") is None
    assert "對不上" in release.check_tag("0.2.1", "v0.2.2")
    assert "格式" in release.check_tag("0.2.1", "0.2.1")
    assert "格式" in release.check_tag("0.2.1-rc.1", "v0.2.1-rc.1")
    installer_ci.check_tag("0.2.1-beta.1", "v0.2.1-beta.1")            # 打 tag 觸發的 exe 建置也接受預覽版


# ---- bump --------------------------------------------------------------------------------------

def test_bump_rewrites_every_version_and_gathers_the_changelog(tmp_path):
    root = _repo(tmp_path)
    new, diff = release.bump(root, "patch", date="2026-11-20")
    assert str(new) == "0.2.1"
    assert '+version = "0.2.1"' in diff and '+__version__ = "0.2.1"' in diff and "+## 0.2.1（2026-11-20）" in diff
    assert release.current_version(root) == V("0.2.1")
    log = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    head = log.split("## 0.2.0")[0]
    assert "未發佈" not in head
    assert head.index("## 0.2.1（2026-11-20）") < head.index("### 工具庫的卡片") < head.index("#### 新增")
    assert "### 修一個小錯" in head and "#### 修正" in head
    assert "## 這不是標題（在程式碼區塊裡）" in head                       # 程式碼區塊不動
    assert "  第二行是細節。" in head
    assert log.count("## 0.2.0\n") == 1 and "## 0.1.0 — 2026-11-09" in log   # 舊的不動
    assert 'requires = ["setuptools>=64"]' in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")


def test_bump_dry_run_changes_nothing(tmp_path):
    root = _repo(tmp_path)
    before = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    new, diff = release.bump(root, "alpha", date="2026-11-20", dry_run=True)
    assert str(new) == "0.2.1-alpha.1" and "+## 0.2.1-alpha.1（2026-11-20）" in diff
    assert release.current_version(root) == V("0.2.0")
    assert (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8") == before


def test_bump_with_nothing_pending_writes_a_placeholder_that_check_refuses(tmp_path):
    root = _repo(tmp_path, changelog="# Changelog\n\n## 0.2.0（2026-11-13）\n\n- 舊的。\n")
    release.bump(root, "patch", date="2026-11-20")
    log = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## 0.2.1（2026-11-20）\n\n- " + release.PLACEHOLDER in log
    ok, bad, warn = release.check(root, tag="v0.2.1")
    assert any("還沒寫" in b for b in bad)
    ok, bad, warn = release.check(root)
    assert not bad and any("還沒寫" in w for w in warn)


def test_final_mentions_its_previews(tmp_path):
    root = _repo(tmp_path)
    release.bump(root, "alpha", date="2026-11-14")
    with open(os.path.join(root, "CHANGELOG.md"), "r+", encoding="utf-8") as f:
        text = f.read().replace("# Changelog\n\n", "# Changelog\n\n## 未發佈（beta 回報的）\n\n- 修 beta 的回報。\n\n", 1)
        f.seek(0), f.write(text), f.truncate()
    release.bump(root, "beta", date="2026-11-16")
    release.bump(root, "final", date="2026-11-20")
    log = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert log.index("## 0.2.1（2026-11-20）") < log.index("## 0.2.1-beta.1（2026-11-16）") < log.index("## 0.2.1-alpha.1（2026-11-14）")
    assert "包含 0.2.1-alpha.1、0.2.1-beta.1 的改動" in log
    assert release.current_version(root) == V("0.2.1")


def test_bump_refuses_a_section_that_already_exists(tmp_path):
    root = _repo(tmp_path, changelog="# Changelog\n\n## 0.2.1（2026-11-01）\n\n- x\n\n## 0.2.0\n")
    with pytest.raises(release.ReleaseError):
        release.bump(root, "patch")
    assert release.current_version(root) == V("0.2.0")


def test_current_version_refuses_mismatch(tmp_path):
    root = _repo(tmp_path)
    (tmp_path / "src" / "synox" / "__init__.py").write_text('__version__ = "0.2.1"\n', encoding="utf-8")
    with pytest.raises(release.ReleaseError, match="不一致"):
        release.current_version(root)
    ok, bad, warn = release.check(root)
    assert any("不一致" in b for b in bad)


# ---- check -------------------------------------------------------------------------------------

def test_check_on_a_dev_tree_only_reminds(tmp_path):
    root = _repo(tmp_path)
    ok, bad, warn = release.check(root)
    assert bad == []
    assert any("沒有日期" in w for w in warn) and any("2 節「未發佈」" in w for w in warn)


def test_check_with_a_tag_is_the_release_gate(tmp_path):
    root = _repo(tmp_path)
    ok, bad, warn = release.check(root, tag="v0.2.0")
    assert any("沒有日期" in b for b in bad) and any("未發佈" in b for b in bad)
    release.bump(root, "patch", date="2026-11-20")
    ok, bad, warn = release.check(root, tag="v0.2.1")
    assert bad == [] and any("0.2.1（2026-11-20）" in o for o in ok)
    ok, bad, warn = release.check(root, tag="v0.2.2")
    assert any("對不上" in b for b in bad)


def test_check_sdk_copy_and_landing_badge(tmp_path):
    root = _repo(tmp_path, sdk=("0.2.3", "0.2.2"), badge="0.1.0")
    ok, bad, warn = release.check(root)
    assert any("SDK 版本不一致" in b and "build_synox_sdk" in b for b in bad)
    assert any("page.html" in w and "0.1.0" in w for w in warn)


def test_check_on_this_repo_has_no_problems():
    """這個 repo 現在的狀態：版本一致、SDK 單檔版跟正本一樣、CHANGELOG 有這一版（日期與「未發佈」只是提醒）。"""
    ok, bad, warn = release.check(ROOT)
    assert bad == [], bad


# ---- notes -------------------------------------------------------------------------------------

def test_notes_stable(tmp_path):
    root = _repo(tmp_path)
    release.bump(root, "patch", date="2026-11-20")
    text = release.notes(root)
    assert text.startswith("## SYNOX 0.2.1（2026-11-20）")
    for heading in ("### 這版改了什麼", "### 要不要更新", "### 怎麼更新"):
        assert heading in text
    assert "**正式版**" in text and "建議更新" in text
    assert "- 卡片顯示「有新版」。" in text and "第二行" not in text and "**工具庫的卡片**" in text
    assert "SYNOX-0.2.1.zip" in text and "git checkout v0.2.1" in text and "Setup.bat" in text
    assert "config.json" in text and "安裝程式還沒正式發佈" in text
    assert release.RELEASES_URL in text
    assert "SYNOX-Setup-0.2.1.exe" in release.notes(root, exe=True)


def test_notes_for_previews_say_who_should_install(tmp_path):
    root = _repo(tmp_path)
    release.bump(root, "beta", date="2026-11-20")
    text = release.notes(root)
    assert "**測試版（beta）**" in text and "請等正式版 0.2.1" in text
    root2 = _repo(tmp_path / "b")
    release.bump(root2, "alpha", date="2026-11-20")
    assert "一般人請不要裝" in release.notes(root2)


def test_notes_needs_a_section(tmp_path):
    root = _repo(tmp_path)
    with pytest.raises(release.ReleaseError, match="沒有"):
        release.notes(root, version="0.9.0")


# ---- CLI ---------------------------------------------------------------------------------------

def test_cli_exit_codes(tmp_path, capsys):
    root = _repo(tmp_path)
    assert release.main(["--root", root, "show"]) == 0
    assert capsys.readouterr().out.strip() == "0.2.0"
    assert release.main(["--root", root, "check"]) == 0
    assert release.main(["--root", root, "check", "--tag", "v0.2.0"]) == 1
    assert release.main(["--root", root, "bump", "final"]) == 2                 # 0.2.0 已經是正式版
    assert release.main(["--root", root, "bump", "patch", "--date", "2026-11-20", "--dry-run"]) == 0
    out = capsys.readouterr()
    assert "+## 0.2.1（2026-11-20）" in out.out and "dry-run" in out.err
    assert release.current_version(root) == V("0.2.0")
    assert release.main(["--root", root, "bump", "patch", "--date", "20261120"]) == 2


def test_rules_doc_names_the_same_labels_and_commands():
    with open(os.path.join(ROOT, "docs", "versioning.md"), encoding="utf-8") as f:
        doc = f.read()
    for word in ("alpha", "beta", "scripts/release.py", "bump", "check --tag", "notes", "requires.synox", "requires.sdk"):
        assert word in doc, word
    assert re.search(r"v\d+\.\d+\.\d+-beta\.\d+", doc)


# ---- 升級矩陣：bump 出來的號碼一定排在現在的後面（docs/versioning.md §3） ------------------------------

@pytest.mark.parametrize("current,kind,nxt,expected", [
    ("0.2.1-beta.2", "alpha", "patch", "0.2.2-alpha.1"),   # 發過 beta 還要回內部測試＝下一號的 alpha（0.2.1-beta.2 < 0.2.2-alpha.1）
    ("0.2.1-beta.2", "alpha", "minor", "0.3.0-alpha.1"),
    ("0.2.1-beta.2", "beta", "patch", "0.2.2-beta.1"),
    ("0.2.1-alpha.3", "alpha", "patch", "0.2.2-alpha.1"),
    ("0.2.1-beta.2", "beta", "", "0.2.1-beta.3"),
    ("0.2.1-beta.2", "final", "", "0.2.1"),
    ("0.2.2-alpha.1", "alpha", "", "0.2.2-alpha.2"),
    ("0.2.2-alpha.2", "beta", "", "0.2.2-beta.1"),
    ("0.2.2", "alpha", "", "0.2.3-alpha.1"),
    ("0.2.2", "alpha", "patch", "0.2.3-alpha.1"),
    ("0.2.2", "beta", "", "0.2.3-beta.1"),
    ("0.2.2", "patch", "", "0.2.3"),
    ("0.2.9", "patch", "", "0.2.10"),
])
def test_next_version_always_sorts_after(current, kind, nxt, expected):
    from synox.packs.upgrade import semver_key
    new = release.next_version(V(current), kind, next_minor=nxt == "minor", next_patch=nxt == "patch")
    assert str(new) == expected
    assert semver_key(expected) > semver_key(current)


def test_alpha_after_beta_needs_next_patch_and_says_so():
    with pytest.raises(release.ReleaseError, match=r"--next patch.*0\.2\.2-alpha\.1"):
        release.next_version(V("0.2.1-beta.2"), "alpha")
    with pytest.raises(release.ReleaseError):
        release.next_version(V("0.2.1-beta.2"), "final", next_patch=True)      # --next 只配 alpha／beta
    with pytest.raises(release.ReleaseError):
        release.next_version(V("0.2.1"), "alpha", next_minor=True, next_patch=True)


PLANNED_LOG = """# Changelog

## 未發佈（branch feat/late：發版前最後合進來的）

### 修正
- 晚到的修正。

## 0.2.2-alpha.1（未發佈）

**版本號**：下一版是 0.2.2-alpha.1。

### branch feat/early：早就合進來的
- 早到的功能。

## 0.2.1-beta.2（2026-11-18）

- 舊的。
"""


def test_dev_carries_the_planned_version_and_bump_keep_dates_it(tmp_path):
    """dev 已經是下一版的號碼（`## X（未發佈）`）：發版那天 `bump keep` 號碼不動、寫上日期、把後來的「未發佈」收進去。"""
    root = _repo(tmp_path, version="0.2.2-alpha.1", changelog=PLANNED_LOG)
    ok, bad, warn = release.check(root)
    assert bad == [] and any("還標著「未發佈」" in w for w in warn)
    ok, bad, warn = release.check(root, tag="v0.2.2-alpha.1")
    assert any("還標著「未發佈」" in b for b in bad)
    new, _diff = release.bump(root, "keep", date="2026-11-25")
    assert str(new) == "0.2.2-alpha.1" and release.current_version(root) == V("0.2.2-alpha.1")
    log = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "未發佈" not in log
    assert log.count("## 0.2.2-alpha.1") == 1
    order = ["## 0.2.2-alpha.1（2026-11-25）", "### branch feat/late", "#### 修正", "**版本號**",
             "### branch feat/early", "## 0.2.1-beta.2（2026-11-18）"]
    pos = [log.index(x) for x in order]
    assert pos == sorted(pos)
    ok, bad, warn = release.check(root, tag="v0.2.2-alpha.1")
    assert bad == [], bad


def test_bump_from_a_planned_version_renames_it(tmp_path):
    """擁有者改主意（還沒發的 0.2.2-alpha.1 直接發成 beta）：那一節改名，不留一個沒發過的 alpha。"""
    root = _repo(tmp_path, version="0.2.2-alpha.1", changelog=PLANNED_LOG)
    new, _diff = release.bump(root, "beta", date="2026-11-25")
    assert str(new) == "0.2.2-beta.1"
    log = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## 0.2.2-alpha.1" not in log and "## 0.2.2-beta.1（2026-11-25）" in log
    assert "早到的功能" in log and "晚到的修正" in log


def test_bump_planned_moves_dev_to_the_next_version(tmp_path):
    """發完正式版後在 dev 上：`bump alpha --planned` 改號碼、開 `## X（未發佈）`（不寫日期）。"""
    root = _repo(tmp_path, version="0.2.2", changelog="# Changelog\n\n## 0.2.2（2026-11-30）\n\n- 正式版。\n")
    new, _diff = release.bump(root, "alpha", planned=True)
    assert str(new) == "0.2.3-alpha.1"
    log = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert log.index("## 0.2.3-alpha.1（未發佈）") < log.index("## 0.2.2（2026-11-30）")
    assert release.main(["--root", root, "bump", "keep", "--date", "2026-12-05"]) == 0
    assert "## 0.2.3-alpha.1（2026-12-05）" in (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")


def test_keep_refuses_a_version_that_was_already_released(tmp_path):
    root = _repo(tmp_path, version="0.2.1", changelog="# Changelog\n\n## 0.2.1（2026-11-20）\n\n- x\n")
    with pytest.raises(release.ReleaseError, match="已經有"):
        release.bump(root, "keep")


def test_this_repo_changelog_top_is_the_project_version():
    """CHANGELOG 最上面的版本就是 pyproject 的版本（scripts/check_version_consistency.py 也查）。"""
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        lines = f.read().splitlines(keepends=True)
    first = next(release._released(ln) for ln in lines if release._released(ln))
    assert first[0] == str(release.current_version(ROOT))


def test_demote_puts_the_branch_headings_right_below_the_section():
    """分支寫 `#### 新增` 或 `### 新增` 都一樣變成 `#### 新增`（在 `### 分支標題` 下面一層），不會跳到 `#####`。"""
    block = ["## 未發佈（branch a）\n", "\n", "#### 新增\n", "- x\n", "##### 細節\n",
             "## 未發佈（branch b）\n", "### 修正\n", "- y\n",
             "## 未發佈\n", "### 文件\n", "- z\n",
             "## 未發佈（branch c）\n", "- 沒有小標題\n"]
    out = release._demote(block)
    assert [ln for ln in out if ln.startswith("#")] == [
        "### branch a\n", "#### 新增\n", "##### 細節\n", "### branch b\n", "#### 修正\n", "### 文件\n", "### branch c\n"]
