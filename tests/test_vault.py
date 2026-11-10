import os
import sys

import pytest

from synox.vault import Vault, VaultError, keyring


def test_round_trip_and_ciphertext(tmp_path):
    v = Vault(os.urandom(32), str(tmp_path))
    v.save_json("money", {"entries": [{"category": "午餐", "amount": 120}]})
    assert v.load_json("money") == {"entries": [{"category": "午餐", "amount": 120}]}
    raw = (tmp_path / "money.json.enc").read_bytes()
    assert "午餐".encode("utf-8") not in raw and b"amount" not in raw
    assert raw.startswith(b'{"synox_vault": 1, "kdf": "scrypt"')


def test_missing_returns_default(tmp_path):
    assert Vault(os.urandom(32), str(tmp_path)).load_json("nope", {"x": 1}) == {"x": 1}


def test_tamper_detected(tmp_path):
    v = Vault(os.urandom(32), str(tmp_path))
    v.save_json("notes", {"items": ["a"]})
    path = tmp_path / "notes.json.enc"
    head, token = path.read_bytes().split(b"\n", 1)
    token = bytearray(token)
    token[40] = ord("A") if token[40] != ord("A") else ord("B")
    path.write_bytes(head + b"\n" + bytes(token))
    with pytest.raises(VaultError):
        v.load_json("notes")


def test_header_tamper_detected(tmp_path):
    v = Vault(os.urandom(32), str(tmp_path))
    v.save_json("notes", {"items": ["a"]})
    path = tmp_path / "notes.json.enc"
    blob = path.read_bytes().replace(b'"salt": "', b'"salt": "AAAA', 1)
    path.write_bytes(blob)
    with pytest.raises(VaultError):
        v.load_json("notes")


def test_wrong_key(tmp_path):
    Vault(os.urandom(32), str(tmp_path)).save_json("money", {"a": 1})
    with pytest.raises(VaultError) as e:
        Vault(os.urandom(32), str(tmp_path)).load_json("money")
    assert "金鑰不對" in str(e.value)


def test_garbage_file(tmp_path):
    (tmp_path / "x.json.enc").write_bytes(b"not a vault file")
    with pytest.raises(VaultError):
        Vault(os.urandom(32), str(tmp_path)).load_json("x")


def test_bad_names(tmp_path):
    v = Vault(os.urandom(32), str(tmp_path))
    for name in ("../x", "a/b", ".hidden", ""):
        with pytest.raises(ValueError):
            v.path(name)


def test_secrets(tmp_path):
    v = Vault(os.urandom(32), str(tmp_path))
    v.set_secret("llm_api_key", "sk-test")
    assert v.secret("llm_api_key") == "sk-test"
    assert b"sk-test" not in (tmp_path / "secrets.json.enc").read_bytes()


def test_keyring_file_mode(tmp_path):
    key = keyring.load_or_create(str(tmp_path), "file")
    assert len(key) == 32
    assert keyring.load_or_create(str(tmp_path), "file") == key
    assert keyring.key_mode(keyring.key_path(str(tmp_path))) == "file"


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_keyring_dpapi(tmp_path):
    key = keyring.load_or_create(str(tmp_path), "dpapi")
    text = (tmp_path / ".synox.key").read_text(encoding="ascii")
    assert text.startswith("SYNOXKEY1 dpapi ")
    import base64
    assert base64.b64decode(text.split()[2]) != key          # 存的是包過的，不是金鑰本身
    assert keyring.load_or_create(str(tmp_path), "dpapi") == key
    assert keyring.dpapi_unprotect(keyring.dpapi_protect(b"hello")) == b"hello"


def test_keyring_never_regenerates_over_existing_data(tmp_path):
    key = keyring.load_or_create(str(tmp_path), "file")
    Vault(key, str(tmp_path)).save_json("money", {"a": 1})
    os.remove(keyring.key_path(str(tmp_path)))
    with pytest.raises(keyring.KeyringError):
        keyring.load_or_create(str(tmp_path), "file")
