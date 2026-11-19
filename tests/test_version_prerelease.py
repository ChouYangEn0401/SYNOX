"""預覽版的版本號（0.2.1-alpha.1 這種）在 SYNOX 每個比版本的地方都要對（docs/versioning.md）。

- SYNOX 自己的新舊（檢查更新、Update.bat、-FromZip）：semver，0.2.0 < 0.2.1-alpha.1 < 0.2.1-beta.1 < 0.2.1。
- 工具的 requires.synox：照 versioning.md §6 只比 X.Y.Z、預覽版的尾巴不看（0.2.1-alpha.1 當成 0.2.1）。
"""

import json
import os
import re

import pytest

import synox
from synox.packs import manifest as M
from synox.packs.upgrade import UPGRADE, compare_versions, semver_key
from synox.update import check as upd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_installed_version_is_semver_and_matches_pyproject():
    assert semver_key(synox.__version__) is not None
    with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as f:
        m = re.search(r'^version\s*=\s*"([^"]*)"', f.read(), re.M)
    assert m and m.group(1) == synox.__version__


@pytest.mark.parametrize("old,new", [
    ("0.2.0", "0.2.1-alpha.1"), ("0.2.1-alpha.1", "0.2.1-alpha.2"), ("0.2.1-alpha.2", "0.2.1-beta.1"),
    ("0.2.1-beta.1", "0.2.1"), ("0.2.1-alpha.1", "0.2.1"), ("0.2.1-alpha.1", "0.2.2"),
])
def test_prerelease_order(old, new):
    assert semver_key(old) < semver_key(new)
    assert upd.compare(old, new) == "newer" and upd.compare(new, old) == "ahead"
    assert compare_versions(old, new)[0] == UPGRADE


def test_update_check_sees_alpha_only_when_asked():
    one = json.dumps({"tag_name": "v0.2.1-alpha.1", "prerelease": True}).encode()
    with pytest.raises(upd.UpdateError):
        upd.parse_release(one)                                   # 一般人（releases/latest）：預覽版不算
    rel = upd.parse_release(one, allow_prerelease=True)
    assert rel.version == "0.2.1-alpha.1" and rel.prerelease
    many = json.dumps([{"tag_name": "v0.2.0"}, {"tag_name": "v0.2.1-alpha.1", "prerelease": True},
                       {"tag_name": "v0.2.1-alpha.2", "prerelease": True, "draft": True}]).encode()
    assert upd.parse_release(many, allow_prerelease=True).version == "0.2.1-alpha.1"   # 草稿跳過


def _ok(spec: str, have: str) -> bool:
    return M._range_problem(spec, have, "synox") is None


def test_requires_synox_ignores_the_prerelease_tail():
    have = "0.2.1-alpha.1"
    assert _ok(">=0.2", have) and _ok(">=0.2,<0.3", have)
    assert _ok(">=0.2.1", have)                                  # 文件寫明：0.2.1 的 alpha／beta 也裝得上
    assert not _ok(">=0.3", have) and not _ok("<0.2.1", have)
    assert "0.2.1-alpha.1" in M._range_problem(">=0.3", have, "synox")
