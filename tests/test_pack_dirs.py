# -*- coding: utf-8 -*-
"""config.json 的 packs.dirs：把別的資料夾（甚至別的 repo 裡的單一 pack）接進來。"""
import json
import os

from synox.config import SynoxConfig
from synox.packs import loader
from synox.packs.loader import discover


def _pack(folder: str, name: str) -> None:
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump({"name": name, "title": name, "summary": "x", "version": "0.0.1", "kind": "connector",
                   "auth": "none", "skill": "SKILL.md"}, f)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(f"---\nname: {name}\ndescription: x\n---\n")


def test_discover_accepts_a_single_pack_folder_and_a_folder_of_packs(tmp_path):
    single = tmp_path / "repo" / "synox-pack"
    _pack(str(single), "alpha")
    many = tmp_path / "more"
    _pack(str(many / "b"), "beta")
    _pack(str(many / "c"), "gamma")
    (many / "not-a-pack").mkdir()
    found = discover([str(single), str(many), str(tmp_path / "missing")])
    assert [os.path.basename(p) for p in found] == ["synox-pack", "b", "c"]


def test_discover_dedups_the_same_folder(tmp_path):
    single = tmp_path / "p"
    _pack(str(single), "alpha")
    assert len(discover([str(single), str(single), str(tmp_path)])) == 1


def test_config_pack_dirs_adds_relative_and_absolute_entries(tmp_path):
    raw = {"bot_token": "", "owner_id": 1, "packs": {"dirs": ["extra", str(tmp_path / "abs"), "", 42]}}
    cfg = SynoxConfig.from_dict(raw, require_token=False, root=str(tmp_path))
    dirs = cfg.pack_dirs()
    assert dirs[:len(loader.PACK_DIRS)] == tuple(loader.PACK_DIRS)
    assert dirs[len(loader.PACK_DIRS):] == (os.path.normpath(str(tmp_path / "extra")), os.path.normpath(str(tmp_path / "abs")))


def test_config_without_dirs_is_just_the_builtin_folders(tmp_path):
    cfg = SynoxConfig.from_dict({"bot_token": "", "owner_id": 1}, require_token=False, root=str(tmp_path))
    assert cfg.pack_dirs() == tuple(loader.PACK_DIRS)          # conftest 換成測試用的資料夾
