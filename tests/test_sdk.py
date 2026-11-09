"""synox.sdk（信封、init／check／zip）、.synoxpack 檔案關聯（只驗字串、不寫真的登錄檔）、cli pack 的面板 route。"""

import io
import json
import os
import zipfile

import pytest

from synox import sdk
from synox.packs import admin, lock
from synox.wizard import shortcuts

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_envelopes():
    out = io.StringIO()
    assert sdk.reply_ok({"n": 1}, "好了", out=out) == 0
    assert sdk.reply_error("not_found", "找不到", out=out) == 1
    assert sdk.reply_confirm("要刪 3 筆", "t1", out=out) == 0
    ok, err, confirm = [json.loads(line) for line in out.getvalue().splitlines()]
    assert ok == {"ok": True, "message": "好了", "data": {"n": 1}}
    assert err == {"ok": False, "error": "找不到", "code": "not_found"}
    assert confirm["needs_confirm"] and confirm["confirm_token"] == "t1" and "要刪 3 筆" in confirm["message"]
    from isdtelekit.jobs.cli import CliReply
    assert not CliReply(1, err).ok and CliReply(1, err).error == "找不到"        # SYNOX 那邊讀得懂


@pytest.mark.parametrize("kind", ["cli", "python"])
def test_init_check_zip_install(tmp_path, kind):
    folder = tmp_path / f"demo-{kind}"
    written = sdk.init_pack(str(folder), kind, f"demo-{kind}", "示範")
    assert {"pack.json", "SKILL.md", "README.md", "panel.html"} <= set(written)
    assert ("tool.py" if kind == "cli" else "pack.py") in written
    assert sdk.init_pack(str(folder), kind, f"demo-{kind}", "示範") == []          # 不蓋已經有的檔
    check = sdk.Pack.load(str(folder))
    assert check.ok, check.problems
    path = sdk.zip_pack(str(folder), str(tmp_path / "dist"))
    assert os.path.basename(path) == f"demo-{kind}-0.1.0.synoxpack"
    with zipfile.ZipFile(path) as z:
        manifest = json.loads(z.read("pack.json"))
    assert set(manifest["integrity"]["sha256"]) == set(written) - {"pack.json"}
    token, summary = admin.stage(open(path, "rb").read(), str(tmp_path / "data"))
    assert summary["integrity"] and summary["scan"]["ok"]
    assert admin.install_staged(token, str(tmp_path / "data"), str(tmp_path / "packs"), approved_by=1) == f"demo-{kind}"
    assert lock.entry(str(tmp_path / "data"), f"demo-{kind}")


def test_zip_refuses_bad_pack(tmp_path):
    import shutil
    shutil.copytree(os.path.join(ROOT, "tests", "fixtures", "evil_pack"), tmp_path / "evil")
    with pytest.raises(ValueError):
        sdk.zip_pack(str(tmp_path / "evil"), str(tmp_path / "dist"))


def test_sdk_cli(tmp_path, capsys):
    assert sdk.main(["init", str(tmp_path / "x"), "--name", "x", "--kind", "cli"]) == 0
    assert sdk.main(["check", str(tmp_path / "x")]) == 0
    assert sdk.main(["zip", str(tmp_path / "x"), "--out", str(tmp_path / "d")]) == 0
    assert "x-0.1.0.synoxpack" in capsys.readouterr().out


def test_cli_pack_panel_route(make_bot, owner, tmp_path):
    folder = tmp_path / "packs" / "demo"
    sdk.init_pack(str(folder), "cli", "demo", "示範")
    bot = make_bot(pack_dirs=(str(tmp_path / "packs"),))
    pack = next(p for p in bot.app.extras["synox_packs"] if p.name == "demo")
    assert set(pack.web_routes) == {"summary"}
    from isdtelekit.users.models import User
    from isdtelekit.users.roles import BasicRoles
    data = pack.web_routes["summary"](User(owner, "me", BasicRoles.ADMIN))   # 真的跑 tool.py（子程序）
    assert data["ok"] and data["data"] == {"count": 0}


def test_cli_web_route_must_be_read_command(tmp_path):
    from synox.packs.manifest import ManifestError, read
    folder = tmp_path / "demo"
    sdk.init_pack(str(folder), "cli", "demo", "示範")
    raw = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    raw["web"]["routes"] = {"summary": "echo"}                                # echo 有必填欄位
    (folder / "pack.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ManifestError) as e:
        read(str(folder))
    assert "web.api" in str(e.value)


def test_synoxpack_registry_keys():
    keys = shortcuts.synoxpack_keys(r"C:\Apps\SYNOX")
    assert ("Software\\Classes\\.synoxpack", "", "SYNOX.Pack") in keys
    assert ("Software\\Classes\\SYNOX.Pack\\shell\\open\\command", "",
            '"C:\\Apps\\SYNOX\\Install-Pack.bat" "%1"') in keys
    assert all(k.startswith("Software\\Classes\\") for k, _n, _v in keys)          # 只有 HKCU 的 Classes
    written = []
    shortcuts.register_synoxpack(r"C:\Apps\SYNOX", writer=lambda *a: written.append(a))
    assert written == keys


def test_install_pack_bat_is_ascii_crlf():
    raw = open(os.path.join(ROOT, "Install-Pack.bat"), "rb").read()
    raw.decode("ascii")
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    text = raw.decode("ascii")
    assert '-m synox install "%~1"' in text and ".venv\\Scripts\\python.exe" in text


def test_pack_zip_script(tmp_path):
    import subprocess
    import sys
    sdk.init_pack(str(tmp_path / "p"), "cli", "p", "P")
    out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "pack_zip.py"), str(tmp_path / "p"),
                          "--out", str(tmp_path / "dist")], capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stdout + out.stderr
    assert os.path.isfile(tmp_path / "dist" / "p-0.1.0.synoxpack")
