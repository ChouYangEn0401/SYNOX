# -*- coding: utf-8 -*-
"""SYNOX 資料夾怎麼決定（config.default_root，docs/adr/0002）：不寫死任何一台電腦的路徑。"""
import os

from synox import config as synox_config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_root_from_source_layout(tmp_path):
    pkg = tmp_path / "anywhere" / "src" / "synox" / "config.py"
    root, how = synox_config.default_root(environ={}, package_file=str(pkg), cwd=str(tmp_path / "cwd"))
    assert (root, how) == (str(tmp_path / "anywhere"), "source")


def test_root_from_synox_home_is_absolute(tmp_path):
    root, how = synox_config.default_root(environ={"SYNOX_HOME": "rel\\home"}, package_file=str(tmp_path / "x.py"),
                                          cwd=str(tmp_path))
    assert how == "SYNOX_HOME" and root == os.path.abspath(os.path.join(str(tmp_path), "rel", "home"))
    blank, how = synox_config.default_root(environ={"SYNOX_HOME": "  "}, package_file=str(tmp_path / "src" / "synox"
                                                                                         / "config.py"))
    assert how == "source"


def test_root_outside_source_layout_uses_cwd(tmp_path):
    """pip install 進 site-packages（沒有 src/ 這一層）：不猜別的資料夾，用目前所在的資料夾，doctor 會說。"""
    pkg = tmp_path / "venv" / "Lib" / "site-packages" / "synox" / "config.py"
    root, how = synox_config.default_root(environ={}, package_file=str(pkg), cwd=str(tmp_path / "here"))
    assert (root, how) == (str(tmp_path / "here"), "cwd")


def test_this_checkout_is_source_layout():
    assert synox_config.ROOT_SOURCE in ("source", "SYNOX_HOME")
    if synox_config.ROOT_SOURCE == "source":
        assert os.path.normcase(synox_config.ROOT) == os.path.normcase(ROOT)
