# -*- coding: utf-8 -*-
"""scripts/clean_room_check.py 的零件（不實際跑整套：那個由人手動跑，見 docs/handoff/clean-machine-test.md）
＋scripts/vendor_sdk.py 找 SDK 的順序。不開子程序、不連網。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import clean_room_check as crc  # noqa: E402
import vendor_sdk  # noqa: E402


def test_scan_finds_local_paths_and_unmarked_sibling_guesses(tmp_path):
    user_path = "C:" + "\\" + "Users" + "\\" + "alice9" + "\\" + "proj"          # 拆開寫，這個檔本身才不會被掃到
    guess = "os.path.dirname" + "(ROOT)"                                          # 同上
    (tmp_path / "a.py").write_text(f'X = r"{user_path}"\nY = {guess}\nZ = {guess}  # {crc.SIBLING_OK}\n',
                                   encoding="utf-8")
    (tmp_path / "b.md").write_text("see ../" + "SYNOX for details\n", encoding="utf-8")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "index.json").write_text(f'"{user_path}"', encoding="utf-8")       # 附的工具不掃
    hits = crc.scan_copy(str(tmp_path))
    assert ("a.py", 1) in [(r, n) for r, n, _ in hits]
    assert ("a.py", 2) in [(r, n) for r, n, _ in hits] and ("a.py", 3) not in [(r, n) for r, n, _ in hits]
    assert not any(r.startswith("tools/") or r == "b.md" for r, _, _ in hits)


def test_this_repo_ships_no_local_paths_or_sibling_guesses():
    """git 追蹤的、會發出去的檔案（跟 make_zip 同一份）都要乾淨。"""
    assert crc.scan_files(crc.make_zip.release_files()) == []


def test_scrubbed_env_forgets_this_computer(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNOX_HOME", "x")
    monkeypatch.setenv("SYNOX_LIBS", "y")
    monkeypatch.setenv("PYTHONPATH", "z")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    env = crc.scrubbed_env(str(tmp_path / "copy"), str(tmp_path / "home"))
    assert not any(k.upper().startswith("SYNOX_") for k in env)
    assert "ANTHROPIC_API_KEY" not in env
    assert env["PYTHONPATH"].startswith(str(tmp_path / "copy"))
    assert env["HOME"] == str(tmp_path / "home")
    if os.name == "nt":
        assert env["USERPROFILE"] == str(tmp_path / "home") and "Python" not in env["PATH"]


def test_leak_check_ignores_the_reused_interpreter():
    venv = os.path.join(ROOT, ".venv")
    exe = os.path.join(venv, "Scripts", "python.exe")
    assert crc.leaked(f"• Python：3.11（{exe}）", [ROOT], exe) == []
    assert crc.leaked(f"• 資料夾：{ROOT}", [ROOT], exe) == [ROOT]


def test_vendor_sdk_location_is_configurable(tmp_path):
    assert vendor_sdk.default_sdk({"ISDTELEKIT_SDK": str(tmp_path)}) == str(tmp_path)
    assert vendor_sdk.default_sdk({}) == vendor_sdk.SIBLING_SDK
    assert vendor_sdk.main(["--sdk", str(tmp_path / "nope")]) == 1
