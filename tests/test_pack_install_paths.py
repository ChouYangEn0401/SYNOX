""".synoxpack 的三種裝法：點兩下（HKCU 檔案關聯＋圖示）、拖到 Install-Pack.bat、拖進網頁（static/packdrop.js → 同一個上傳）。

- 網頁上傳的伺服器端：只有擁有者、Content-Type、大小、zip 檔頭（前面接東西的自解壓 exe／polyglot 拒）、上傳只暫存不裝。
- 檔案關聯：機碼清單、重跑不重寫、拿掉時不動別人的 .synoxpack；真的 HKCU 只寫拋棄式的子機碼，用 reg query 驗，最後刪乾淨。
- 圖示：scripts/make_pack_icon.py 畫出來的跟 repo 裡的一樣（決定性），ICO 檔頭有 16／32／48／256。
"""

import io
import json
import os
import shutil
import struct
import subprocess
import sys
import uuid
import zipfile

import pytest

from synox import __main__ as cli
from synox.packs import admin
from synox.web import server as web_server
from synox.wizard import shortcuts

from test_web import Client, _pack_zip, owner_client, ui_of  # noqa: F401  (owner_client 是 fixture)

from conftest import OTHER_ID

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── 網頁上傳（拖進網頁也走這裡）──────────────────────────────────────

def _staged_dirs(bot):
    staging = os.path.join(bot.app.config.data_dir, "web_uploads")
    return os.listdir(staging) if os.path.isdir(staging) else []


@pytest.mark.parametrize("ctype", ["application/zip", "application/x-zip-compressed", "application/octet-stream", None])
def test_upload_accepts_zip_content_type_and_only_stages(owner_client, owner, ctype):
    bot, c = owner_client
    headers = {"Content-Type": ctype} if ctype else {}
    status, _h, body = c.raw("POST", "/api/packs/upload", _pack_zip(), headers)
    summary = json.loads(body)
    assert status == 200 and summary["name"] == "hello" and summary["token"], summary
    bot.say(owner, "/hello")
    assert "hi there" not in (bot.last(owner) or "")                            # 沒按確認：沒裝


@pytest.mark.parametrize("ctype", ["text/html", "application/json", "multipart/form-data; boundary=x"])
def test_upload_rejects_other_content_types(owner_client, ctype):
    bot, c = owner_client
    status, _h, body = c.raw("POST", "/api/packs/upload", _pack_zip(), {"Content-Type": ctype})
    assert status == 415 and "synoxpack" in json.loads(body)["error"]
    assert _staged_dirs(bot) == []


def test_upload_rejects_oversize(owner_client):
    bot, c = owner_client
    status, _h, body = c.raw("POST", "/api/packs/upload", b"PK\x03\x04" + b"\0" * admin.MAX_UPLOAD)
    assert status == 413 and "5 MB" in json.loads(body)["error"]
    assert _staged_dirs(bot) == []


def test_upload_rejects_zip_with_prefix(owner_client):
    """zipfile 從檔尾找目錄：exe＋zip（自解壓）也打得開。.synoxpack 一律要從 zip 檔頭開始。"""
    bot, c = owner_client
    blob = b"MZ" + b"\0" * 200 + _pack_zip()
    assert zipfile.ZipFile(io.BytesIO(blob)).namelist()                         # 前提：zipfile 本身照樣打得開
    status, _h, body = c.raw("POST", "/api/packs/upload", blob, {"Content-Type": "application/zip"})
    assert status == 400 and "zip" in json.loads(body)["error"]
    assert _staged_dirs(bot) == []


def test_stage_file_rejects_zip_with_prefix(tmp_path):
    """`synox install`／點兩下／拖到 Install-Pack.bat 走 stage_file，同一個檢查。"""
    path = tmp_path / "x.synoxpack"
    path.write_bytes(b"#!junk\n" + _pack_zip())
    with pytest.raises(admin.PackAdminError):
        admin.stage_file(str(path), str(tmp_path / "data"))


def test_upload_member_and_logged_out_refused(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    from isdtelekit.users.roles import BasicRoles
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    m = Client(ui_of(bot))
    m.login(OTHER_ID)
    assert m.raw("POST", "/api/packs/upload", _pack_zip(), {"Content-Type": "application/zip"})[0] == 403
    anon = Client(ui_of(bot))
    assert anon.raw("POST", "/api/packs/upload", _pack_zip())[0] in (401, 403)
    assert _staged_dirs(bot) == []


def test_upload_needs_csrf(make_bot, owner):
    bot = make_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    c.csrf = "wrong"
    assert c.raw("POST", "/api/packs/upload", _pack_zip())[0] == 403
    assert _staged_dirs(bot) == []


def test_app_page_includes_packdrop():
    html = web_server.render_app("NONCE123")
    for name in ("packdrop.js", "packdrop.css"):
        text = open(os.path.join(ROOT, "src", "synox", "web", "static", name), encoding="utf-8").read()
        assert text.strip()[:60] in html, name
        assert "</script" not in text.lower() and "</style" not in text.lower()
    assert "{{INCLUDE:packdrop" not in html and 'nonce="NONCE123"' in html
    js = open(os.path.join(ROOT, "src", "synox", "web", "static", "packdrop.js"), encoding="utf-8").read()
    assert "innerHTML" not in js and "pack-upload" in js and "/api/packs/install" not in js.replace(
        "（/api/packs/upload → 看報告 → /api/packs/install）", "")                # 只交給原本的按鈕，不自己裝
    assert 'root.location.hash = "#settings"' not in js and "installHash(" in js    # 拖進來一律到安裝頁（#packs）


def test_packdrop_js_with_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("這台沒有 node：tests/js/test_packdrop.js 沒跑")
    proc = subprocess.run([node, os.path.join(ROOT, "tests", "js", "test_packdrop.js")], cwd=ROOT,
                          capture_output=True, timeout=60)
    assert proc.returncode == 0, proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")


# ── 檔案關聯（Setup.bat → python -m synox filetype register）──────────

def test_keys_have_icon_and_open_verb():
    keys = shortcuts.synoxpack_keys(ROOT)
    values = {(k, n): v for k, n, v in keys}
    icon = values[("Software\\Classes\\SYNOX.Pack\\DefaultIcon", "")]
    assert icon == os.path.join(ROOT, "src", "synox", "assets", "synoxpack.ico") + ",0"
    assert os.path.isfile(icon[:-2])
    assert values[("Software\\Classes\\SYNOX.Pack\\shell", "")] == "open"
    assert values[("Software\\Classes\\SYNOX.Pack\\shell\\open\\command", "")] == \
        '"' + os.path.join(ROOT, "Install-Pack.bat") + '" "%1"'
    assert values[("Software\\Classes\\.synoxpack\\OpenWithProgids", "SYNOX.Pack")] == ""
    assert all(k.startswith("Software\\Classes\\") for k in (k for k, _n, _v in keys))


class FakeReg:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.writes = []

    def read(self, subkey, name):
        return self.values.get((subkey, name))

    def write(self, subkey, name, value):
        self.writes.append((subkey, name))
        self.values[(subkey, name)] = value

    def delete(self, subkey):
        gone = [k for k in self.values if k[0] == subkey or k[0].startswith(subkey + "\\")]
        for k in gone:
            del self.values[k]
        return bool(gone)


def test_register_is_idempotent_and_reports_changes():
    reg = FakeReg()
    first = shortcuts.register_synoxpack(r"C:\Apps\SYNOX", writer=reg.write, reader=reg.read)
    assert all(changed for *_x, changed in first) and len(reg.writes) == len(first)
    second = shortcuts.register_synoxpack(r"C:\Apps\SYNOX", writer=reg.write, reader=reg.read)
    assert not any(changed for *_x, changed in second) and len(reg.writes) == len(first)
    moved = shortcuts.register_synoxpack(r"D:\SYNOX", writer=reg.write, reader=reg.read)   # 資料夾搬家：只改路徑那幾筆
    assert {k for k, _n, _v, changed in moved if changed} == {
        "Software\\Classes\\SYNOX.Pack\\DefaultIcon", "Software\\Classes\\SYNOX.Pack\\shell\\open\\command"}


def test_unregister_leaves_someone_elses_extension():
    reg = FakeReg({("Software\\Classes\\.synoxpack", ""): "Other.App",
                   ("Software\\Classes\\SYNOX.Pack", ""): "x"})
    removed = shortcuts.unregister_synoxpack(reader=reg.read, deleter=reg.delete)
    assert removed == ["Software\\Classes\\SYNOX.Pack"]
    assert reg.values == {("Software\\Classes\\.synoxpack", ""): "Other.App"}


def test_filetype_cli_with_fake_registry(capsys):
    reg = FakeReg()

    class Args:
        filetype_cmd = "status"
    kw = dict(root=ROOT, writer=reg.write, reader=reg.read, deleter=reg.delete)
    assert cli.cmd_filetype(Args, **kw) == 1
    Args.filetype_cmd = "register"
    assert cli.cmd_filetype(Args, **kw) == 0
    out = capsys.readouterr().out
    assert "+ HKCU\\Software\\Classes\\SYNOX.Pack\\DefaultIcon" in out and "8 written, 0 unchanged" in out
    assert cli.cmd_filetype(Args, **kw) == 0
    assert "0 written, 8 unchanged" in capsys.readouterr().out
    Args.filetype_cmd = "status"
    assert cli.cmd_filetype(Args, **kw) == 0
    Args.filetype_cmd = "unregister"
    assert cli.cmd_filetype(Args, **kw) == 0
    assert "- HKCU\\Software\\Classes\\.synoxpack" in capsys.readouterr().out and reg.values == {}


def _reg_query(key):
    return subprocess.run(["reg", "query", key, "/s"], capture_output=True, timeout=30)


@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("reg"), reason="Windows registry only")
def test_real_hkcu_round_trip_in_throwaway_key():
    """真的寫 HKCU，但只寫在 Software\\SYNOX-test-<亂數>\\Classes（不是真的 Classes，不改這台的檔案關聯）；
    reg query 看得到、unregister 之後刪乾淨，最後連拋棄式的根也刪掉。"""
    base = f"Software\\SYNOX-test-{uuid.uuid4().hex[:12]}"
    classes = base + "\\Classes"
    try:
        done = shortcuts.register_synoxpack(ROOT, classes=classes)
        assert all(changed for *_x, changed in done)
        out = _reg_query("HKCU\\" + classes)
        text = out.stdout.decode("mbcs", "replace")
        assert out.returncode == 0 and "SYNOX.Pack" in text and "synoxpack.ico,0" in text and "Install-Pack.bat" in text
        assert not any(c for *_x, c in shortcuts.register_synoxpack(ROOT, classes=classes))      # 重跑：不重寫
        status = shortcuts.synoxpack_status(ROOT, classes=classes)
        assert all(now == want for *_k, want, now in status)
        removed = shortcuts.unregister_synoxpack(classes=classes)
        assert removed == [classes + "\\.synoxpack", classes + "\\SYNOX.Pack"]
        assert _reg_query("HKCU\\" + classes + "\\SYNOX.Pack").returncode != 0
        assert _reg_query("HKCU\\" + classes + "\\.synoxpack").returncode != 0
    finally:
        subprocess.run(["reg", "delete", "HKCU\\" + base, "/f"], capture_output=True, timeout=30)
    assert _reg_query("HKCU\\" + base).returncode != 0                                         # 沒留垃圾


# ── 圖示 ───────────────────────────────────────────────────────────

def test_pack_icon_matches_generator():
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_pack_icon", os.path.join(ROOT, "scripts", "make_pack_icon.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ico, _previews = mod.build()
    with open(shortcuts.pack_icon_path(ROOT), "rb") as f:
        committed = f.read()
    assert committed == ico, "重跑 scripts/make_pack_icon.py"
    reserved, kind, count = struct.unpack("<HHH", committed[:6])
    assert (reserved, kind) == (0, 1)
    sizes = [committed[6 + 16 * i] or 256 for i in range(count)]
    assert {16, 32, 48, 256} <= set(sizes)
