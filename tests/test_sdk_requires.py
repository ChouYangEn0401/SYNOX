# -*- coding: utf-8 -*-
"""pack.json 的 requires.sdk：工具宣告自己照哪一版 SDK 介面寫（SYNOX_Libs docs/adr/0001）。
寫錯＝第 1 關不合；這台的 SDK_VERSION 不在範圍內＝不裝（第 1、2 關的問題清單）、不載入（incompatible）。"""
import io
import json
import os
import zipfile

import pytest

from synox.packs import admin
from synox.packs.manifest import ManifestError, parse_spec, sdk_problem, synox_problem, validate
from synox.sdk import author, init_pack

PACK_PY = "def install(app, pack):\n    pack.group.leaf('hi', lambda api, chat_id, user, args: api.send_message(chat_id, 'hi'), 'hi', default=True)\n"


def _raw(**requires):
    return {"name": "hi", "title": "👋 hi", "summary": "測試", "version": "0.1.0", "kind": "python",
            "python": {"module": "pack"}, "skill": "SKILL.md", "surfaces": ["dm"], "data": "none",
            "capabilities": [], "requires": requires}


def _pack(folder, **requires):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(_raw(**requires), f, ensure_ascii=False)
    with open(os.path.join(folder, "pack.py"), "w", encoding="utf-8") as f:
        f.write(PACK_PY)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: hi\ndescription: 測試\n---\n")
    return folder


def _zip(folder) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in os.listdir(folder):
            z.write(os.path.join(folder, name), name)
    return buf.getvalue()


def test_sdk_range_follows_semver(tmp_path):
    assert author.sdk_range("0.2.0") == ">=0.2,<0.3"
    assert author.sdk_range("0.2.7") == ">=0.2,<0.3"
    assert author.sdk_range("1.4.0") == ">=1.4,<2.0"
    assert author.SDK_REQUIRES == author.sdk_range(author.SDK_VERSION)
    folder = _pack(str(tmp_path / "hi"))
    assert sdk_problem(validate(_raw(sdk=author.SDK_REQUIRES), folder)) is None   # 這台的 SDK 一定在自己寫的範圍內


def test_parse_spec_names_the_field():
    with pytest.raises(ValueError, match="requires.sdk"):
        parse_spec("latest", "sdk")


def test_bad_sdk_spec_is_invalid_manifest(tmp_path):
    folder = _pack(str(tmp_path / "hi"))
    with pytest.raises(ManifestError, match="requires.sdk"):
        validate(_raw(sdk="newest"), folder)


def test_sdk_problem_human_message(tmp_path):
    folder = _pack(str(tmp_path / "hi"))
    m = validate(_raw(sdk=">=0.2,<0.3"), folder)
    assert sdk_problem(m, "0.2.5") is None
    too_old = sdk_problem(m, "0.1.0")
    assert "SYNOX SDK >=0.2,<0.3" in too_old and "0.1.0" in too_old and "更新 SYNOX" in too_old
    assert "作者" in sdk_problem(m, "0.3.0")                     # 這台的 SDK 比工具新：要工具的新版
    assert synox_problem(m, "0.2.0", sdk="0.3.0") == sdk_problem(m, "0.3.0")   # 載入／安裝／doctor 都走 synox_problem
    assert sdk_problem(validate(_raw(), folder), "9.9.9") is None              # 沒寫＝不限


def test_synox_problem_checked_before_sdk(tmp_path):
    folder = _pack(str(tmp_path / "hi"))
    m = validate(_raw(synox=">=99.0", sdk=">=99.0"), folder)
    assert "SYNOX >=99.0" in synox_problem(m, "0.2.0", sdk="0.2.0")


def test_install_refuses_wrong_sdk(tmp_path):
    folder = _pack(str(tmp_path / "src" / "hi"), sdk=">=99.0")
    with pytest.raises(admin.GateRefused, match="SYNOX SDK >=99.0") as e:
        admin.stage(_zip(folder), str(tmp_path / "data"))
    assert not e.value.summary["scan"]["ok"]


def test_install_accepts_current_sdk(tmp_path):
    folder = _pack(str(tmp_path / "src" / "hi"), sdk=author.SDK_REQUIRES)
    _token, summary = admin.stage(_zip(folder), str(tmp_path / "data"))
    assert summary["scan"]["ok"], summary["scan"]["problems"]


def test_wrong_sdk_is_not_loaded(make_bot, tmp_path):
    _pack(str(tmp_path / "packs" / "hi"), sdk="<0.1")
    bot = make_bot(pack_dirs=(str(tmp_path / "packs"),))
    item = bot.app.extras["synox_pack_report"].items[0]
    assert item.status == "incompatible" and "SYNOX SDK <0.1" in item.detail
    assert bot.app.registry.node("hi") is None


def test_templates_declare_sdk(tmp_path):
    init_pack(str(tmp_path / "p"), "python", "p", "P")
    with open(tmp_path / "p" / "pack.json", encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["requires"]["sdk"] == author.SDK_REQUIRES and raw["requires"]["synox"] == author.SYNOX_REQUIRES


def test_examples_declare_current_sdk():
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")
    for name in sorted(os.listdir(root)):
        with open(os.path.join(root, name, "pack.json"), encoding="utf-8") as f:
            raw = json.load(f)
        assert (raw.get("requires") or {}).get("sdk"), f"examples/{name} 沒宣告 requires.sdk"
        assert sdk_problem(validate(raw, os.path.join(root, name))) is None, name
