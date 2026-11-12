# -*- coding: utf-8 -*-
"""pack.json 的 stage（穩定度）：只收 test／alpha／beta／stable，沒寫＝alpha；/help、網頁工具頁的 API、
安裝報告、doctor 都顯示「符號＋字」的標籤（不只靠顏色）。全部在暫存資料夾，不連網、不開埠。"""
import json
import os

import pytest

from conftest import OWNER_ID

from synox.packs import admin, loader
from synox.packs.manifest import (DEFAULT_STAGE, STAGES, ManifestError, read, stage_label, stage_problem,
                                  stage_text, validate)

from test_web import Client, ui_of

RUN_PY = r'''
from isdtelekit.core.registry import READ

def install(app, pack):
    def run(api, chat_id, user, args):
        api.send_message(chat_id, "跑了 " + pack.name)
    pack.group.leaf("run", run, "跑一下", effect=READ, default=True)
'''


def _pack(base, name, **over):
    folder = os.path.join(str(base), name)
    os.makedirs(folder, exist_ok=True)
    raw = {"name": name, "title": "🧰 " + name, "summary": "測試", "version": "0.1.0", "kind": "python",
           "group": name, "python": {"module": "pack"}, "skill": "SKILL.md", "publisher": "test", **over}
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
    with open(os.path.join(folder, "pack.py"), "w", encoding="utf-8") as f:
        f.write(RUN_PY)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(f"---\nname: {name}\ndescription: 測試\n---\n")
    return folder


def test_four_stages_and_default(tmp_path):
    assert STAGES == ("test", "alpha", "beta", "stable") and DEFAULT_STAGE == "alpha"
    for stage in STAGES:
        m = read(_pack(tmp_path, f"p{stage}", stage=stage), strict=True)
        assert (m.stage, m.stage_declared) == (stage, True)
    m = read(_pack(tmp_path, "nostage"), strict=True)
    assert (m.stage, m.stage_declared) == ("alpha", False)        # 沒寫＝alpha


@pytest.mark.parametrize("bad", ["gold", "Alpha", "", " beta", 1, None, ["alpha"]])
def test_install_refuses_unknown_stage(tmp_path, bad):
    folder = _pack(tmp_path, "bad", stage=bad)
    with pytest.raises(ManifestError, match="stage 只能是"):
        read(folder, strict=True)
    m = read(folder)                                                # 載入時寬鬆：當作 alpha（比較保守）
    assert (m.stage, m.stage_declared) == ("alpha", False)
    assert stage_problem(bad)


def test_labels_are_symbol_plus_word():
    assert stage_label("alpha") == "🧪 alpha"
    assert stage_label("stable", long=True) == "⭐ stable（穩定版）"
    assert stage_label("nope") == "🧪 alpha"                       # 不認得的當 alpha
    for stage in STAGES:
        icon, word = stage_label(stage).split(" ")
        assert icon and word == stage and stage_text(stage)


def test_help_page_title_shows_stage(make_bot, owner, tmp_path):
    _pack(tmp_path / "packs", "beta1", stage="beta")
    bot = make_bot(pack_dirs=loader.PACK_DIRS + (str(tmp_path / "packs"),))
    bot.say(owner, "/help all")
    text = bot.last(owner)
    assert "💰 記帳（🧪 alpha）" in text                             # 測試用的 money 沒寫 stage＝alpha
    assert "🧰 beta1（🚧 beta）" in text
    bot.say(owner, "/help beta1")
    assert "🚧 beta" in bot.last(owner)


def test_tools_api_returns_stage(make_bot, owner, tmp_path):
    _pack(tmp_path / "packs", "stable1", stage="stable")
    bot = make_bot(pack_dirs=loader.PACK_DIRS + (str(tmp_path / "packs"),))
    c = Client(ui_of(bot))
    c.login(owner)
    status, tools = c.get("/api/tools")
    assert status == 200
    rows = {p["name"]: p for p in tools["packs"]}
    assert (rows["stable1"]["stage"], rows["stable1"]["stage_label"]) == ("stable", "⭐ stable")
    assert rows["money"]["stage"] == "alpha" and rows["money"]["stage_label"] == "🧪 alpha"
    assert rows["money"]["stage_text"]


def test_install_report_shows_stage(tmp_path):
    folder = _pack(tmp_path, "t1", stage="test")
    m, report, hashes, problems = admin.run_gates(folder)
    summary = admin.summary_of(m, report, hashes, problems)
    assert summary["stage"] == "test" and summary["stage_label"] == "🔧 test"
    assert any(w.startswith("穩定度 🔧 test（測試中）") for w in summary["warnings"])
    assert "穩定度：🔧 test（測試中）" in admin.format_summary(summary)
    plain = admin.run_gates(_pack(tmp_path, "t2"))
    text = admin.format_summary(admin.summary_of(*plain))
    assert "穩定度：🧪 alpha（早期版）（pack.json 沒寫 stage，當作 alpha）" in text
    stable = admin.run_gates(_pack(tmp_path, "t3", stage="stable"))
    assert not any(w.startswith("穩定度") for w in admin.summary_of(*stable)["warnings"])   # stable 不另外提醒


def test_staged_upload_keeps_stage(tmp_path):
    from synox.sdk import zip_pack
    out = zip_pack(_pack(tmp_path / "src", "z1", stage="beta"), str(tmp_path / "dist"))
    with open(out, "rb") as f:
        _token, summary = admin.stage(f.read(), str(tmp_path / "data"))
    assert summary["stage"] == "beta" and summary["stage_label"] == "🚧 beta"


def test_doctor_lists_stage(tmp_path, monkeypatch):
    from synox import doctor
    packs = tmp_path / "packs"
    _pack(packs, "d1", stage="beta")
    monkeypatch.setattr(loader, "PACK_DIRS", (str(packs),))
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": OWNER_ID, "data_dir": str(tmp_path / "data"), "vault": {"mode": "file"}}),
                   encoding="utf-8")
    lines = []
    doctor.run(offline=True, config_path=str(cfg), out=lines.append)
    assert any("d1 0.1.0 🚧 beta（python" in line for line in lines), lines


def test_validate_dict_directly(tmp_path):
    folder = _pack(tmp_path, "v1")
    with open(os.path.join(folder, "pack.json"), encoding="utf-8") as f:
        raw = json.load(f)
    assert validate({**raw, "stage": "beta"}, folder, strict=True).stage == "beta"
