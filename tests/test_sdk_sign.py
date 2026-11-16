"""synox-sdk keygen／sign／verify（ADR 0028 §8）：整條走一次 synox.sdk.main；密語一律走環境變數（測試沒有終端機）。
init 預設不產生面板；--panel 才產生、用相對網址 api/summary（ADR 0028 §5）。"""

import json
import os
import stat
import zipfile

import pytest

from synox import sdk
from synox.packs import admin, signing


@pytest.fixture
def pack_file(tmp_path):
    sdk.init_pack(str(tmp_path / "demo"), "cli", "demo", "示範")
    return sdk.zip_pack(str(tmp_path / "demo"), str(tmp_path / "dist"))


def test_keygen_sign_verify_round_trip(tmp_path, pack_file, capsys, monkeypatch):
    monkeypatch.setenv("SYNOX_PACK_KEY_PASSWORD", "correct horse")
    key_path = str(tmp_path / "keys" / "my-pack-key.pem")
    assert sdk.main(["verify", pack_file]) == 1                     # 還沒簽
    out = capsys.readouterr().out
    assert out.startswith("⚠️ 不是官方（none）")
    assert sdk.main(["keygen", "--out", key_path]) == 0
    out = capsys.readouterr().out.splitlines()
    pub = out[0].split("public_key: ", 1)[1]
    kid = out[1].split("key_id: ", 1)[1]
    assert len(pub) == 44 and len(kid) == 16 and "下一步" in "\n".join(out)
    pem = open(key_path, "rb").read()
    assert pem.startswith(b"-----BEGIN ENCRYPTED PRIVATE KEY-----")       # 有密語保護（prepublish-check: allow：只比對 PEM 檔頭字樣）
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(key_path).st_mode) == 0o600
    assert sdk.main(["keygen", "--out", key_path]) == 2                   # 不蓋掉
    assert "已經有檔案" in capsys.readouterr().out

    signed = str(tmp_path / "signed.synoxpack")
    assert sdk.main(["sign", pack_file, "--key", key_path, "--out", signed]) == 0
    out = capsys.readouterr().out
    assert f"key_id: {kid}" in out and "✍️ 作者簽章" in out
    assert sdk.main(["verify", signed]) == 0
    out = capsys.readouterr().out
    assert out.startswith("✍️ 作者簽章（author）") and f"key_id: {kid}" in out
    with zipfile.ZipFile(signed) as z:
        assert json.loads(z.read("pack.sig.json"))["public_key"] == pub
    with zipfile.ZipFile(pack_file) as z:
        assert "pack.sig.json" not in z.namelist()                       # --out：原檔沒動

    monkeypatch.setattr(signing, "OFFICIAL_PACK_PUBLIC_KEYS", (pub,))
    assert sdk.main(["verify", signed]) == 0
    assert capsys.readouterr().out.startswith("✅ 官方（official）")

    assert sdk.main(["sign", pack_file, "--key", key_path]) == 0          # 沒有 --out：原檔覆寫
    capsys.readouterr()
    assert signing.verify_zip(pack_file).status == "official"

    # 簽過再改 → ⛔，結束碼 2
    with zipfile.ZipFile(signed) as z:
        files = {i.filename: z.read(i) for i in z.infolist()}
    files["tool.py"] += b"\n# changed\n"
    with zipfile.ZipFile(signed, "w") as z:
        for name, blob in files.items():
            z.writestr(name, blob)
    assert sdk.main(["verify", signed]) == 2
    out = capsys.readouterr().out
    assert out.startswith("⛔ 被改過（invalid）") and "改了 tool.py" in out


def test_sign_needs_right_passphrase(tmp_path, pack_file, capsys, monkeypatch):
    monkeypatch.setenv("SYNOX_PACK_KEY_PASSWORD", "one")
    key_path = str(tmp_path / "k.pem")
    assert sdk.main(["keygen", "--out", key_path]) == 0
    capsys.readouterr()
    monkeypatch.setenv("SYNOX_PACK_KEY_PASSWORD", "two")
    assert sdk.main(["sign", pack_file, "--key", key_path]) == 2
    assert "密語不對" in capsys.readouterr().out
    monkeypatch.delenv("SYNOX_PACK_KEY_PASSWORD")
    monkeypatch.delenv("SYNOX_RELEASE_KEY_PASSWORD", raising=False)
    assert sdk.main(["sign", pack_file, "--key", key_path]) == 2
    assert "密語" in capsys.readouterr().out
    monkeypatch.setenv("SYNOX_RELEASE_KEY_PASSWORD", "one")              # 另一個環境變數也收（ADR 0028 §2）
    assert sdk.main(["sign", pack_file, "--key", key_path]) == 0
    with zipfile.ZipFile(pack_file) as z:
        assert "pack.sig.json" in z.namelist()


def test_keygen_refuses_empty_passphrase_and_repo(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("SYNOX_PACK_KEY_PASSWORD", raising=False)
    assert sdk.main(["keygen", "--out", str(tmp_path / "k.pem")]) == 2
    assert "--no-passphrase" in capsys.readouterr().out and not (tmp_path / "k.pem").exists()
    assert sdk.main(["keygen", "--out", str(tmp_path / "k.pem"), "--no-passphrase"]) == 0
    assert open(tmp_path / "k.pem", "rb").read().startswith(b"-----BEGIN PRIVATE KEY-----")  # prepublish-check: allow（只比對 PEM 檔頭字樣，不是金鑰）
    capsys.readouterr()
    inside = os.path.join(signing.REPO_ROOT, "never-here.pem")
    assert sdk.main(["keygen", "--out", inside, "--no-passphrase"]) == 2
    assert not os.path.exists(inside) and "SYNOX 的資料夾" in capsys.readouterr().out
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    assert sdk.main(["keygen", "--out", str(tmp_path / "repo" / "sub" / "k.pem"), "--no-passphrase"]) == 2
    assert "git" in capsys.readouterr().out


def test_unencrypted_key_and_seed_key_sign(tmp_path, pack_file, monkeypatch, capsys):
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    monkeypatch.delenv("SYNOX_PACK_KEY_PASSWORD", raising=False)
    key = Ed25519PrivateKey.generate()
    seed = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    (tmp_path / "seed.txt").write_text(base64.b64encode(seed).decode() + "\n")
    assert sdk.main(["sign", pack_file, "--key", str(tmp_path / "seed.txt")]) == 0
    assert signing.verify_zip(pack_file).public_key == signing.public_key_b64(key)


def test_verify_bad_file_exit_2(tmp_path, capsys):
    bad = tmp_path / "x.synoxpack"
    bad.write_bytes(b"not a zip")
    assert sdk.main(["verify", str(bad)]) == 2
    assert capsys.readouterr().out.startswith("⛔ 被改過（檔案不對）")
    assert sdk.main(["verify", str(tmp_path / "missing.synoxpack")]) == 2


def test_zip_drops_stale_signature(tmp_path, pack_file, monkeypatch):
    """從簽過的 .synoxpack 解出來改了再 zip：舊的 pack.sig.json 不打包（不然一定是 ⛔）。"""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    signing.sign_zip(pack_file, Ed25519PrivateKey.generate())
    folder = tmp_path / "again"
    with zipfile.ZipFile(pack_file) as z:
        z.extractall(folder)
    raw = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    raw.pop("integrity")
    raw["version"] = "0.2.0"
    (folder / "pack.json").write_text(json.dumps(raw), encoding="utf-8")
    path = sdk.zip_pack(str(folder), str(tmp_path / "dist2"))
    with zipfile.ZipFile(path) as z:
        assert "pack.sig.json" not in z.namelist()
    assert signing.verify_zip(path).status == "none"


def test_keygen_asks_twice_on_a_terminal(tmp_path, monkeypatch, capsys):
    """終端機上（stdin 是 tty）：synox-sdk keygen 與 release.py keygen 都問兩次密語（ADR 0028 §2）。"""
    import getpass
    import sys
    sys.path.insert(0, os.path.join(signing.REPO_ROOT, "scripts"))
    import release
    monkeypatch.delenv("SYNOX_PACK_KEY_PASSWORD", raising=False)
    monkeypatch.delenv("SYNOX_RELEASE_KEY_PASSWORD", raising=False)
    monkeypatch.setattr(signing, "stdin_is_terminal", lambda: True)
    monkeypatch.setattr(release, "_stdin_is_terminal", lambda: True)
    answers = iter(["pw", "pw", "a", "b", "pw2", "pw2"])
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(answers))
    assert sdk.main(["keygen", "--out", str(tmp_path / "a.pem")]) == 0
    assert open(tmp_path / "a.pem", "rb").read().startswith(b"-----BEGIN ENCRYPTED")
    assert sdk.main(["keygen", "--out", str(tmp_path / "b.pem")]) == 2           # 兩次不一樣
    assert "不一樣" in capsys.readouterr().out and not (tmp_path / "b.pem").exists()
    release.keygen(str(tmp_path / "r.pem"))
    assert open(tmp_path / "r.pem", "rb").read().startswith(b"-----BEGIN ENCRYPTED")


# ── init：面板預設不產生 ────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["cli", "python"])
def test_init_without_panel(tmp_path, kind):
    written = sdk.init_pack(str(tmp_path / "p"), kind, "p", "P")
    assert "panel.html" not in written and not (tmp_path / "p" / "panel.html").exists()
    manifest = json.loads((tmp_path / "p" / "pack.json").read_text(encoding="utf-8"))
    assert manifest["web"] == {"api": ["GET /summary"]}
    assert "synox" not in manifest["summary"].lower()


def test_init_with_panel_uses_relative_url(tmp_path, capsys):
    assert sdk.main(["init", str(tmp_path / "p"), "--name", "p", "--kind", "cli", "--panel"]) == 0
    manifest = json.loads((tmp_path / "p" / "pack.json").read_text(encoding="utf-8"))
    assert manifest["web"] == {"panel": "panel.html", "api": ["GET /summary"]}
    html = (tmp_path / "p" / "panel.html").read_text(encoding="utf-8")
    assert 'fetch("api/summary")' in html and "/api/packs/" not in html and "credentials" not in html
    assert sdk.Pack.load(str(tmp_path / "p")).ok


def test_format_summary_signature_first_and_notice_last(tmp_path, pack_file):
    _token, summary = admin.stage(open(pack_file, "rb").read(), str(tmp_path / "data"))
    lines = admin.format_summary(summary).splitlines()
    assert lines[0].startswith(summary["signature"]["label"]) and lines[1].startswith("📦")
    assert lines[-1] == signing.SAFETY_NOTICE
