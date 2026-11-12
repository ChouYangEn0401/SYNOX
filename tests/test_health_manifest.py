# -*- coding: utf-8 -*-
"""pack.json 的 health.check（src/synox/packs/manifest.py 的 health_problem）：一定要指到這個 pack 裡唯讀、不用填參數的指令；
安裝時寫錯＝拒、載入時寫錯＝當作沒寫。只用 tmp 裡的宣告，不執行任何程式。"""
import copy
from pathlib import Path

import pytest

from synox.packs.manifest import ManifestError, validate


def _raw(**over):
    raw = {"name": "demo", "title": "示範", "summary": "s", "version": "0.1.0", "kind": "cli", "skill": "SKILL.md",
           "capabilities": [], "health": {"check": "ping"},
           "cli": {"argv": ["{python}", "./tool.py"], "commands": [
               {"name": "price", "effect": "READ", "summary": "查", "argv": ["price", "--item={item}"],
                "fields": [{"name": "item", "ask": "東西", "required": True}]},
               {"name": "ping", "effect": "READ", "summary": "自我檢查", "argv": ["ping"]}]}}
    raw.update(over)
    return raw


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "SKILL.md").write_text("---\nname: demo\ndescription: 測試\n---\n", encoding="utf-8")
    return str(tmp_path)


def test_valid_check(folder):
    assert validate(_raw(), folder, strict=True).health == {"check": "ping"}
    assert validate({k: v for k, v in _raw().items() if k != "health"}, folder, strict=True).health == {}
    defaulted = _raw(health={"check": "price"})
    defaulted["cli"]["commands"][0]["fields"][0]["default"] = "apple"          # 必填但有預設值：可以
    assert validate(defaulted, folder, strict=True).health == {"check": "price"}


def _variant(edit):
    raw = copy.deepcopy(_raw())
    edit(raw)
    return raw


@pytest.mark.parametrize("raw,word", [
    (_raw(health={"check": "nope"}), "不是 cli.commands"),
    (_raw(health={"check": "price"}), "必填"),
    (_variant(lambda r: r["cli"]["commands"][1].update(effect="WRITE")), "唯讀"),
    (_variant(lambda r: r["cli"]["commands"][1].update(background=True)), "background"),
    (_variant(lambda r: r["cli"]["commands"][1].update(confirm=True)), "background"),
    (_raw(health="ping"), "health 要是"),
    (_raw(health={"check": "ping", "run": "x"}), "health 要是"),
    (_raw(health={"check": ""}), "health.check"),
])
def test_bad_check_is_refused_at_install_and_ignored_at_load(folder, raw, word):
    with pytest.raises(ManifestError) as e:
        validate(raw, folder, strict=True)
    assert word in str(e.value)
    assert validate(raw, folder, strict=False).health == {}                     # 載入時：當作沒寫，照樣載入


def test_mcp_and_python_checks(folder):
    mcp = {"name": "m", "title": "M", "summary": "s", "version": "0.1.0", "kind": "mcp", "skill": "SKILL.md",
           "capabilities": ["subprocess"], "health": {"check": "ping"},
           "mcp": {"transport": "stdio", "argv": ["{python}", "./s.py"], "tools_allow": ["ping", "add"],
                   "effects": {"ping": "READ", "add": "WRITE"}}}
    assert validate(mcp, folder, strict=True).health == {"check": "ping"}
    for check, word in (("add", "唯讀"), ("other", "tools_allow")):
        with pytest.raises(ManifestError) as e:
            validate({**mcp, "health": {"check": check}}, folder, strict=True)
        assert word in str(e.value)
    (Path(folder) / "pack.py").write_text("def install(app, pack):\n    pass\n", encoding="utf-8")
    py = {"name": "p", "title": "P", "summary": "s", "version": "0.1.0", "kind": "python", "skill": "SKILL.md",
          "health": {"check": "status"}}
    assert validate(py, folder, strict=True).health == {"check": "status"}
    with pytest.raises(ManifestError):
        validate({**py, "health": {"check": "Bad Name"}}, folder, strict=True)
