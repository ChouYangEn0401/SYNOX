"""發佈前的版本一致檢查 scripts/check_version_consistency.py（規則：docs/versioning.md §2、§5）。
小 repo 都在 tmp_path；tag 用參數給，不跑 git（最後一個測試才對這個 repo 跑真的 `git tag`，唯讀）。"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import check_version_consistency as cvc  # noqa: E402

ISS = """#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
[Setup]
AppVersion={#AppVersion}
AppVerName=SYNOX {#AppVersion}
"""


def _repo(tmp_path, version="0.2.2-alpha.1", init=None, top="## 0.2.2-alpha.1（未發佈）", iss=ISS, docs="", badge=None):
    (tmp_path / "src" / "synox").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "setup" / "installer").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        f'[build-system]\nrequires = ["setuptools>=64"]\n\n[project]\nname = "synox"\nversion = "{version}"\n',
        encoding="utf-8")
    (tmp_path / "src" / "synox" / "__init__.py").write_text(f'__version__ = "{init or version}"\n', encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## 未發佈（branch feat/x）\n\n- x\n\n{top}\n\n- y\n\n## 0.2.1-beta.2（2026-11-18）\n\n- z\n",
        encoding="utf-8")
    if iss is not None:
        (tmp_path / "setup" / "installer" / "synox.iss").write_text(iss, encoding="utf-8")
    (tmp_path / "docs" / "versioning.md").write_text(docs or f"目前版本：`{version}`\n", encoding="utf-8")
    if badge:
        (tmp_path / "docs" / "landing").mkdir()
        (tmp_path / "docs" / "landing" / "page.html").write_text(f'<span class="ver"><b>{badge}</b></span>',
                                                                 encoding="utf-8")
    return str(tmp_path)


TAGS = ["v0.2.1-alpha.1", "v0.2.1-beta.1", "v0.2.1-beta.2"]


def test_dev_tree_is_fine_with_reminders(tmp_path):
    ok, bad, warn = cvc.check(_repo(tmp_path), tags=TAGS)
    assert bad == [], bad
    assert any("比最新的 tag v0.2.1-beta.2 新" in o for o in ok)
    assert any("還沒有日期" in w for w in warn)


def test_release_gate_needs_the_date_and_the_matching_tag(tmp_path):
    root = _repo(tmp_path, top="## 0.2.2-alpha.1（2026-11-25）")
    ok, bad, warn = cvc.check(root, tag="v0.2.2-alpha.1", tags=TAGS)
    assert bad == [], bad
    ok, bad, warn = cvc.check(root, tag="v0.2.2-alpha.2", tags=TAGS)
    assert any("對不上" in b for b in bad)
    ok, bad, warn = cvc.check(_repo(tmp_path / "b"), tag="v0.2.2-alpha.1", tags=TAGS)
    assert any("還沒有日期" in b for b in bad)


@pytest.mark.parametrize("version,why", [
    ("0.2.1-alpha.2", "沒有比最新的 tag"),     # alpha 排在已發的 beta 前面：錯版
    ("0.2.1-beta.1", "已經發過了"),             # 重用版本號
    ("0.2.0", "沒有比最新的 tag"),
])
def test_version_must_sort_after_every_tag(tmp_path, version, why):
    root = _repo(tmp_path, version=version, top=f"## {version}（未發佈）")
    ok, bad, warn = cvc.check(root, tags=TAGS)
    assert any(why in b for b in bad), bad


def test_a_checkout_of_a_released_tag_is_fine(tmp_path):
    root = _repo(tmp_path, version="0.2.1-beta.2", top="## 0.2.1-beta.2（2026-11-18）")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## 0.2.1-beta.2（2026-11-18）\n\n- z\n", encoding="utf-8")
    ok, bad, warn = cvc.check(root, tags=TAGS, head_tags=["v0.2.1-beta.2"])
    assert bad == [], bad


def test_numbers_and_previews_sort_by_semver_not_text(tmp_path):
    root = _repo(tmp_path, version="0.2.10", top="## 0.2.10（未發佈）")
    ok, bad, warn = cvc.check(root, tags=["v0.2.9", "v0.2.9-beta.11", "v0.2.10-rc.1"])
    assert bad == [], bad


def test_mismatches_are_errors(tmp_path):
    ok, bad, warn = cvc.check(_repo(tmp_path, init="0.2.2-alpha.2"), tags=TAGS)
    assert any("版本不一致" in b for b in bad)
    ok, bad, warn = cvc.check(_repo(tmp_path / "b", top="## 0.2.1-beta.3（未發佈）"), tags=TAGS)
    assert any("CHANGELOG.md 最上面的版本是 0.2.1-beta.3" in b for b in bad)
    ok, bad, warn = cvc.check(_repo(tmp_path / "c", iss=ISS.replace('"0.0.0"', '"0.2.1"')), tags=TAGS)
    assert any("寫死了版本" in b for b in bad)
    ok, bad, warn = cvc.check(_repo(tmp_path / "d", iss=ISS + "AppVersion=0.2.1\n"), tags=TAGS)
    assert any("寫死了版本" in b for b in bad)
    ok, bad, warn = cvc.check(_repo(tmp_path / "e", docs="目前版本：`0.2.1-beta.1`\n"), tags=TAGS)
    assert any("docs/versioning.md:1" in b for b in bad)
    ok, bad, warn = cvc.check(_repo(tmp_path / "f", version="0.2.2-alpha.01", top="## 0.2.2-alpha.01（未發佈）"),
                              tags=TAGS)
    assert any("不是 SemVer" in b for b in bad)
    ok, bad, warn = cvc.check(_repo(tmp_path / "g"), tags=TAGS + ["v0.2.1-beta"])
    assert bad == [], bad                                       # 「v0.2.1-beta」也是 SemVer（預覽版只有一段）
    ok, bad, warn = cvc.check(_repo(tmp_path / "h"), tags=TAGS + ["v0.2"])
    assert any("tag v0.2 不是" in b for b in bad)


def test_landing_badge_and_missing_tags_are_only_reminders(tmp_path):
    ok, bad, warn = cvc.check(_repo(tmp_path, badge="0.2.1-beta.1"), tags=[])
    assert bad == []
    assert any("page.html" in w for w in warn) and any("沒有任何 v* tag" in w for w in warn)
    ok, bad, warn = cvc.check(_repo(tmp_path / "b"), use_git=False)
    assert bad == [] and any("沒有比 git tag" in w for w in warn)


def test_cli_exit_codes(tmp_path, capsys):
    assert cvc.main(["--root", _repo(tmp_path), "--no-git"]) == 0
    assert cvc.main(["--root", _repo(tmp_path / "b", init="9.9.9"), "--no-git"]) == 1
    assert cvc.main(["--root", str(tmp_path / "nothing")]) == 2


def test_semver_key_matches_the_pack_upgrader():
    from synox.packs.upgrade import semver_key
    for v in ["0.2.1-beta.2", "0.2.2-alpha.10", "1.0.0+b", "1.0.0-alpha.beta", "1.0.0-alpha.01", "x"]:
        assert cvc.semver_key(v) == semver_key(v), v


def test_this_repo():
    """這個 repo 現在：版本一致、CHANGELOG 最上面是這一版、比每個本機 tag 新（git tag 唯讀）。"""
    ok, bad, warn = cvc.check(ROOT)
    assert bad == [], bad


def test_released_version_on_a_later_merge_commit_is_fine_when_the_code_did_not_change(tmp_path):
    """dev/main after a release merge: the tag is an ancestor, only merges and docs came after (no src change)."""
    root = _repo(tmp_path, version="0.2.1-beta.2", top="## 0.2.1-beta.2（2026-11-18）")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## 0.2.1-beta.2（2026-11-18）\n\n- z\n", encoding="utf-8")
    ok, bad, warn = cvc.check(root, tags=TAGS, head_tags=[], unchanged_since=["v0.2.1-beta.2"])
    assert bad == [], bad


def test_released_version_with_changed_code_after_the_tag_is_still_refused(tmp_path):
    """Same version, but src/ changed after the tag: that is reuse of a released number."""
    root = _repo(tmp_path, version="0.2.1-beta.2", top="## 0.2.1-beta.2（2026-11-18）")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## 0.2.1-beta.2（2026-11-18）\n\n- z\n", encoding="utf-8")
    ok, bad, warn = cvc.check(root, tags=TAGS, head_tags=[], unchanged_since=[])
    assert any("已經發過了" in b for b in bad), bad
