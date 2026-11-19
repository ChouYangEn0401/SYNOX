"""版本號規則（docs/versioning.md）的升級矩陣：SYNOX 本體與工具每一個比版本的地方，都要照 SemVer 2.0.0 排。

比版本的地方（Python）：
- 工具升級／工具庫「有新版」：`packs/upgrade.semver_key`、`compare_versions`、`packs/catalog._newer`／`updates`
- SYNOX 檢查更新、Update.bat、-FromZip：`update/check.compare`（也是用 semver_key）
- 發版小幫手 `scripts/release.py` 的 next_version：tests/test_release_script.py
- 工具庫清單的 requires：tests/test_pack_library.py
網頁那份（`static/semver.js`）在 tests/test_web_semver.py。
"""

import os

import pytest

from synox.packs import catalog
from synox.packs.upgrade import DOWNGRADE, INVALID, SAME, UPGRADE, compare_versions, semver_key
from synox.update import check as upd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# SYNOX 實際走過、接下來要走的路：每一步都要被當成「升級」
SYNOX_PATH = ["0.2.0", "0.2.1-alpha.1", "0.2.1-beta.1", "0.2.1-beta.2", "0.2.2-alpha.1", "0.2.2-alpha.2",
              "0.2.2-beta.1", "0.2.2-rc.1", "0.2.2", "0.2.3-alpha.1", "0.2.3", "0.3.0-alpha.1", "0.3.0"]
TOOL_PATH = ["0.1.2", "0.1.3-alpha.1", "0.1.3-alpha.2", "0.1.3-alpha.10", "0.1.3-beta.1", "0.1.3", "0.1.4",
             "0.1.10", "1.0.9", "1.0.10"]
# SemVer 2.0.0 §11 的例子（照規格由舊到新）
SPEC_ORDER = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11",
              "1.0.0-rc.1", "1.0.0"]


@pytest.mark.parametrize("order", [SYNOX_PATH, TOOL_PATH, SPEC_ORDER])
def test_semver_order(order):
    keys = [semver_key(v) for v in order]
    assert None not in keys
    assert keys == sorted(keys) and len(set(keys)) == len(keys)


def _pairs(order):
    return [(order[i], order[j]) for i in range(len(order)) for j in range(i + 1, len(order))]


@pytest.mark.parametrize("old,new", _pairs(SYNOX_PATH))
def test_synox_update_check_every_step_is_newer(old, new):
    """alpha→alpha、alpha→beta、beta→beta、beta→下一版的 alpha、beta→正式版、正式版→下一個 alpha／beta／正式版。"""
    assert upd.compare(old, new) == "newer"
    assert upd.compare(new, old) == "ahead"                        # 反過來＝裝的比較新：不降級


@pytest.mark.parametrize("old,new", _pairs(TOOL_PATH))
def test_tool_upgrade_every_step(old, new):
    assert compare_versions(old, new)[0] == UPGRADE
    assert compare_versions(new, old)[0] == DOWNGRADE              # 降級要明確選
    assert catalog._newer(new, old) and not catalog._newer(old, new)


@pytest.mark.parametrize("a,b", [("1.0.0+build.1", "1.0.0+build.2"), ("1.0.0", "1.0.0+20261119"),
                                 ("0.2.2-alpha.1+sha.abc", "0.2.2-alpha.1")])
def test_build_metadata_is_ignored(a, b):
    assert semver_key(a) == semver_key(b)
    assert compare_versions(a, b)[0] == SAME
    assert upd.compare(a, b) == "current"


def test_numbers_compare_as_numbers_not_text():
    assert semver_key("1.0.10") > semver_key("1.0.9")
    assert semver_key("0.10.0") > semver_key("0.9.9")
    assert semver_key("0.2.2-alpha.10") > semver_key("0.2.2-alpha.2")
    assert semver_key("0.2.2-beta.11") > semver_key("0.2.2-beta.2")


@pytest.mark.parametrize("bad", ["1.0", "v1.0.0", "01.0.0", "1.0.0-", "1.0.0-alpha..1", "1.0.0-alpha.01", "1.0.0-01",
                                 "1.0.0+", ""])
def test_not_semver(bad):
    """SemVer 不收的（含預覽版數字段前面補 0）比不出新舊：工具升級回 invalid、不會亂猜。"""
    assert semver_key(bad) is None
    assert compare_versions("1.0.0", bad)[0] == INVALID


def test_stable_to_an_older_preview_is_a_downgrade():
    """正式版 → 舊的 beta：預設不換（檢查更新說「裝的比較新」；工具要明確選降級）。"""
    assert upd.compare("0.2.2", "0.2.2-beta.1") == "ahead"
    assert upd.compare("0.2.2", "0.2.1-beta.2") == "ahead"
    assert compare_versions("0.1.3", "0.1.3-alpha.1")[0] == DOWNGRADE
