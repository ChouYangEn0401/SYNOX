"""ADR 0028：工具的簽章（pack.sig.json）與 SYNOX 自己畫的標章——official／author／none／invalid、
zip 的重複與大小寫相撞、壓縮炸彈、鎖記簽章、升級的紅字、看起來像官方的字。鑰匙一律在測試裡現產（不進 repo）。"""

import base64
import io
import json
import os
import re
import struct
import zipfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from synox import sdk
from synox.packs import admin, lock, signing, upgrade
from synox.packs.manifest import ManifestError, read

from test_security import _write_pack, _zip_dir

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL_PY = "import json, sys\nprint(json.dumps({'ok': True}))\n"


def _raw(version="0.1.0", **over):
    raw = {"name": "tool", "title": "Tool", "summary": "s", "version": version, "kind": "cli",
           "cli": {"argv": ["{python}", "./tool.py"], "commands": [{"name": "list", "effect": "READ", "argv": ["list"]}]}}
    raw.update(over)
    return raw


def _pack_zip(tmp_path, tag="v1", version="0.1.0", key=None, **over) -> str:
    """寫一個 cli pack → synox-sdk zip → （有 key 就）sign。回 .synoxpack 的路徑。"""
    src = _write_pack(str(tmp_path / "src" / tag), _raw(version, **over), {"tool.py": TOOL_PY})
    path = sdk.zip_pack(src, str(tmp_path / "dist" / tag))
    if key is not None:
        signing.sign_zip(path, key)
    return path


def _pub(key) -> str:
    return signing.public_key_b64(key)


def _stage(path, tmp_path):
    with open(path, "rb") as f:
        return admin.stage(f.read(), str(tmp_path / "data"))


def _rewrite(path, change):
    """改 zip 裡的檔：change({名字: 位元組}) 就地改。"""
    with zipfile.ZipFile(path) as z:
        files = {i.filename: z.read(i) for i in z.infolist()}
    change(files)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, blob in files.items():
            z.writestr(name, blob)


def _staged_dirs(tmp_path):
    root = admin.staging_root(str(tmp_path / "data"))
    return os.listdir(root) if os.path.isdir(root) else []


# ── 四種狀態 ───────────────────────────────────────────────────────────

def test_unsigned_is_none_and_official_keys_are_shipped(tmp_path):
    token, summary = _stage(_pack_zip(tmp_path), tmp_path)
    sig = summary["signature"]
    assert token and sig["status"] == "none" and sig["label"] == "⚠️ 不是官方"
    assert not sig["no_official_keys"] and "還沒有官方鑰匙" not in sig["text"]      # 官方鑰匙已經隨這一版發出
    assert summary["safety_notice"] == signing.SAFETY_NOTICE
    text = admin.format_summary(summary).splitlines()
    assert text[0].startswith("⚠️ 不是官方") and text[-1] == signing.SAFETY_NOTICE
    assert set(sig) == {"status", "label", "key_id", "public_key", "text", "lookalike", "no_official_keys"}


def test_author_and_official(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    path = _pack_zip(tmp_path, key=key)
    _token, summary = _stage(path, tmp_path)
    sig = summary["signature"]
    assert sig["status"] == "author" and sig["label"] == "✍️ 作者簽章" and sig["public_key"] == _pub(key)
    assert sig["key_id"] == signing.key_id(base64.b64decode(_pub(key))) and len(sig["key_id"]) == 16
    assert "不是官方" in sig["text"]
    monkeypatch.setattr(signing, "OFFICIAL_PACK_PUBLIC_KEYS", ("broken", _pub(key)))
    _token, summary = _stage(path, tmp_path)
    assert summary["signature"]["status"] == "official" and summary["signature"]["label"] == "✅ 官方"
    assert not summary["signature"]["no_official_keys"]
    assert admin.format_summary(summary).splitlines()[0].startswith("✅ 官方")
    # 官方鑰匙有了，但這個檔是別把鑰匙簽的 → 作者簽章
    other = _pack_zip(tmp_path, tag="other", key=Ed25519PrivateKey.generate())
    assert _stage(other, tmp_path)[1]["signature"]["status"] == "author"


def test_signed_zip_round_trip_and_lock(tmp_path):
    key = Ed25519PrivateKey.generate()
    path = _pack_zip(tmp_path, key=key)
    with zipfile.ZipFile(path) as z:
        doc = json.loads(z.read("pack.sig.json"))
    assert set(doc) == {"version", "algorithm", "key_id", "public_key", "files", "signature"}
    assert doc["version"] == 1 and doc["algorithm"] == "ed25519" and "pack.sig.json" not in doc["files"]
    assert set(doc["files"]) == {"pack.json", "SKILL.md", "tool.py"}
    assert signing.verify_zip(path).status == "author"
    signing.sign_zip(path, key)                                     # 再簽一次：換掉舊的簽章檔，不會多一份
    with zipfile.ZipFile(path) as z:
        assert [n for n in z.namelist() if n.endswith("pack.sig.json")] == ["pack.sig.json"]
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _s = _stage(path, tmp_path)
    admin.install_staged(token, data, packs, approved_by=1)
    record = lock.entry(data, "tool")
    assert record["signature"] == {"status": "author", "key_id": doc["key_id"], "public_key": _pub(key)}
    assert "pack.sig.json" in record["files"]                       # 鎖也守著簽章檔
    assert lock.signature_of(record)["status"] == "author"
    assert lock.signature_of({}) == {"status": "none"} and lock.signature_of(None) == {"status": "none"}
    assert lock.signature_of({"signature": {"status": "official-ish"}}) == {"status": "none"}


def test_unsigned_lock_record_is_none(tmp_path):
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _s = _stage(_pack_zip(tmp_path), tmp_path)
    admin.install_staged(token, data, packs, approved_by=1)
    assert lock.entry(data, "tool")["signature"] == {"status": "none"}


def test_signed_zip_with_top_folder(tmp_path):
    """pack 在 zip 裡唯一的資料夾底下：簽章檔放在同一層（不然 SYNOX 找不到 pack.json）。"""
    key = Ed25519PrivateKey.generate()
    path = _pack_zip(tmp_path)
    _rewrite(path, lambda files: [files.update({"tool/" + n: files.pop(n)}) for n in list(files)])
    signing.sign_zip(path, key)
    with zipfile.ZipFile(path) as z:
        assert "tool/pack.sig.json" in z.namelist()
    assert _stage(path, tmp_path)[1]["signature"]["status"] == "author"


# ── 被改過 → 拒，沒有確認鈕 ─────────────────────────────────────────────

def _sig_doc(files):
    return json.loads(files["pack.sig.json"])


def _set_sig(files, doc):
    files["pack.sig.json"] = json.dumps(doc).encode()


TAMPER = {
    "byte": lambda f: f.update({"tool.py": f["tool.py"] + b"#"}),
    "added": lambda f: f.update({"sitecustomize.py": b"x = 1\n"}),
    "removed": lambda f: f.pop("tool.py"),
    "list": lambda f: _set_sig(f, {**_sig_doc(f), "files": {**_sig_doc(f)["files"], "tool.py": "0" * 64}}),
    "bad_base64": lambda f: _set_sig(f, {**_sig_doc(f), "signature": "not base64!!"}),
    "short_sig": lambda f: _set_sig(f, {**_sig_doc(f), "signature": base64.b64encode(b"x" * 10).decode()}),
    "version": lambda f: _set_sig(f, {**_sig_doc(f), "version": 2}),
    "algorithm": lambda f: _set_sig(f, {**_sig_doc(f), "algorithm": "rsa"}),
    "key_id": lambda f: _set_sig(f, {**_sig_doc(f), "key_id": "0" * 16}),
    "extra_key": lambda f: _set_sig(f, {**_sig_doc(f), "note": "hi"}),
    "not_json": lambda f: f.update({"pack.sig.json": b"{not json"}),
}


@pytest.mark.parametrize("how", sorted(TAMPER))
def test_tampered_is_refused_without_token(tmp_path, how):
    path = _pack_zip(tmp_path, key=Ed25519PrivateKey.generate())
    _rewrite(path, TAMPER[how])
    with pytest.raises(admin.GateRefused) as e:
        _stage(path, tmp_path)
    assert str(e.value) == signing.INVALID_MESSAGE
    summary = e.value.summary
    assert summary["token"] == "" and summary["signature"]["status"] == "invalid"
    assert summary["signature"]["label"] == "⛔ 被改過"
    assert signing.INVALID_MESSAGE in summary["scan"]["problems"] and not summary["scan"]["ok"]
    assert _staged_dirs(tmp_path) == []                              # 暫存清掉了
    assert signing.verify_zip(path).status == "invalid"


def test_removed_file_is_invalid(tmp_path):
    path = _pack_zip(tmp_path, key=Ed25519PrivateKey.generate())
    _rewrite(path, lambda f: f.pop("tool.py"))
    result = signing.verify_zip(path)
    assert result.status == "invalid" and "少了 tool.py" in result.reason


def test_signature_file_swapped_to_own_key_is_author_not_official(tmp_path, monkeypatch):
    """改了檔、拿自己的鑰匙重簽：驗得過，但不再是官方（標章變了）。"""
    official = Ed25519PrivateKey.generate()
    monkeypatch.setattr(signing, "OFFICIAL_PACK_PUBLIC_KEYS", (_pub(official),))
    path = _pack_zip(tmp_path, key=official)
    assert signing.verify_zip(path).status == "official"
    _rewrite(path, TAMPER["byte"])
    assert signing.verify_zip(path).status == "invalid"
    signing.sign_zip(path, Ed25519PrivateKey.generate())
    assert signing.verify_zip(path).status == "author"


def _break_staged_signature(folder):
    """暫存裡的 pack.sig.json 被換掉（簽章亂掉；integrity 不管它）。"""
    path = os.path.join(folder, "pack.sig.json")
    doc = json.load(open(path, encoding="utf-8"))
    doc["signature"] = base64.b64encode(b"\0" * 64).decode()
    json.dump(doc, open(path, "w", encoding="utf-8"))


def test_install_reverifies_signature(tmp_path):
    """防禦深度：stage 之後暫存裡的簽章檔被換掉 → 檔案對不上，不裝。"""
    path = _pack_zip(tmp_path, key=Ed25519PrivateKey.generate())
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _s = _stage(path, tmp_path)
    folder = os.path.join(admin.staging_root(data), token, "pack")
    _break_staged_signature(folder)
    meta_path = os.path.join(admin.staging_root(data), token, admin.STAGED_META)
    meta = json.load(open(meta_path, encoding="utf-8"))
    meta["hashes"] = lock.hash_files(folder)                         # 連報告記的雜湊也一起改（最壞的情況）
    json.dump(meta, open(meta_path, "w", encoding="utf-8"))
    with pytest.raises(admin.GateRefused) as e:
        admin.install_staged(token, data, packs, approved_by=1)
    assert str(e.value) == signing.INVALID_MESSAGE
    assert lock.entry(data, "tool") is None and not os.path.exists(os.path.join(packs, "tool"))


def test_approve_installed_refuses_invalid(tmp_path):
    path = _pack_zip(tmp_path, key=Ed25519PrivateKey.generate())
    folder = tmp_path / "packs" / "tool"
    with zipfile.ZipFile(path) as z:
        z.extractall(folder)
    (folder / "tool.py").write_text(TOOL_PY + "#", encoding="utf-8")
    _m, _r, problems = admin.approve_installed(str(folder), str(tmp_path / "data"))
    assert problems[0] == signing.INVALID_MESSAGE and lock.entry(str(tmp_path / "data"), "tool") is None


def test_integrity_ignores_signature_file(tmp_path):
    """先 zip（寫 integrity）再 sign：pack.sig.json 不在 integrity 裡，第 2 關不該說「多了 pack.sig.json」。"""
    path = _pack_zip(tmp_path, key=Ed25519PrivateKey.generate())
    _token, summary = _stage(path, tmp_path)
    assert summary["integrity"] and summary["scan"]["ok"], summary["scan"]["problems"]


# ── zip 本身 ───────────────────────────────────────────────────────────

def _zip(entries) -> bytes:
    buf = io.BytesIO()
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")                              # zipfile 對重複名字會警告
        with zipfile.ZipFile(buf, "w") as z:
            for name, blob in entries:
                z.writestr(name, blob)
    return buf.getvalue()


def _base_entries():
    raw = json.dumps(_raw()).encode()
    return [("pack.json", raw), ("SKILL.md", b"---\nname: tool\ndescription: d\n---\n"), ("tool.py", TOOL_PY.encode())]


def test_duplicate_entry_refused(tmp_path):
    blob = _zip(_base_entries() + [("tool.py", b"import os\n")])
    with pytest.raises(admin.PackAdminError) as e:
        admin.stage(blob, str(tmp_path / "data"))
    assert "出現兩次" in str(e.value) and _staged_dirs(tmp_path) == []


def test_case_collision_refused(tmp_path):
    blob = _zip(_base_entries() + [("a.py", b"x=1\n"), ("A.py", b"x=2\n")])
    with pytest.raises(admin.PackAdminError) as e:
        admin.stage(blob, str(tmp_path / "data"))
    assert "大小寫" in str(e.value)


def _lie_about_size(blob: bytes, name: str, size: int) -> bytes:
    """把 zip 裡 name 宣告的解開大小改小（本機檔頭與中央目錄都改）。"""
    data = bytearray(blob)
    enc = name.encode()
    for sig, off_size, off_name_len, head in ((b"PK\x03\x04", 22, 26, 30), (b"PK\x01\x02", 24, 28, 46)):
        start = 0
        while True:
            i = data.find(sig, start)
            if i < 0:
                break
            n = struct.unpack_from("<H", data, i + off_name_len)[0]
            if bytes(data[i + head:i + head + n]) == enc:
                struct.pack_into("<I", data, i + off_size, size)
            start = i + 4
    return bytes(data)


def test_zip_bomb_entry_refused(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, blob in _base_entries():
            z.writestr(name, blob)
        z.writestr("big.txt", b"a" * 200000)
    blob = _lie_about_size(buf.getvalue(), "big.txt", 10)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        assert z.getinfo("big.txt").file_size == 10
    with pytest.raises(admin.PackAdminError) as e:
        admin.stage(blob, str(tmp_path / "data"))
    assert type(e.value) is admin.PackAdminError and ("壓縮炸彈" in str(e.value) or "壞掉" in str(e.value))
    assert _staged_dirs(tmp_path) == []


def test_copy_member_counts_real_bytes(tmp_path):
    """_copy_member 自己數解出來的位元組：比宣告的大就停（不靠 zipfile 的行為）。"""
    class Fake:
        def __init__(self):
            self.chunks = [b"a" * 50, b"a" * 50]

        def open(self, info):
            fake = self

            class Src:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def read(self, n):
                    return fake.chunks.pop(0) if fake.chunks else b""
            return Src()

    info = zipfile.ZipInfo("x.txt")
    info.file_size = 60
    with pytest.raises(admin.PackAdminError):
        admin._copy_member(Fake(), info, ["x.txt"], lambda b: None, [10 ** 6])
    info.file_size = 1000
    with pytest.raises(admin.PackAdminError):
        admin._copy_member(Fake(), info, ["x.txt"], lambda b: None, [80])


# ── 看起來像官方 ───────────────────────────────────────────────────────

@pytest.mark.parametrize("over,needle", [
    ({"title": "官方記帳"}, "標題裡有「官方」"),
    ({"title": "官​方記帳"}, "標題裡有「官方」"),                  # 零寬字元切開也算
    ({"summary": "ＳＹＮＯＸ 小幫手"}, "說明裡有「SYNOX」"),            # 全形
    ({"publisher": "Official Team"}, "發行者裡有「official」"),
    ({"title": "✅ 記帳"}, "標題裡有「✅」"),
])
def test_lookalike_flags(tmp_path, over, needle):
    m = read(_write_pack(str(tmp_path / "p"), _raw(**over), {"tool.py": TOOL_PY}))
    lines = signing.lookalike_problems(m)
    assert any(line.startswith(needle) and line.endswith("但這個工具不是官方的") for line in lines), lines


def test_lookalike_in_report_red_and_skill_description(tmp_path, monkeypatch):
    src = _write_pack(str(tmp_path / "src"), _raw(name="synox-helper"), {"tool.py": TOOL_PY})
    with open(os.path.join(src, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: x\ndescription: 官方出品\n---\n")
    path = sdk.zip_pack(src, str(tmp_path / "dist"))
    _t, summary = _stage(path, tmp_path)
    look = summary["signature"]["lookalike"]
    assert "名字裡有「SYNOX」，但這個工具不是官方的" in look
    assert "SKILL.md 的說明裡有「官方」，但這個工具不是官方的" in look
    lines = admin.format_summary(summary).splitlines()
    assert lines[0].startswith("⚠️ 不是官方") and lines[1] == "🔴 " + look[0]
    # 官方的就不標
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(signing, "OFFICIAL_PACK_PUBLIC_KEYS", (_pub(key),))
    signing.sign_zip(path, key)
    assert _stage(path, tmp_path)[1]["signature"]["lookalike"] == []


def test_plain_pack_has_no_lookalike(tmp_path):
    folder = tmp_path / "p"
    sdk.init_pack(str(folder), "cli", "notes", "記事")
    assert signing.lookalike_problems(read(str(folder))) == []        # 範本自己不能被標紅


# ── 第 1 關：看不見的字元 ──────────────────────────────────────────────

@pytest.mark.parametrize("key,value", [("title", "a‮b"), ("summary", "x​y"), ("publisher", "p﻿"),
                                       ("title", "two\nlines")])
def test_manifest_strict_refuses_invisible(tmp_path, key, value):
    folder = _write_pack(str(tmp_path / "p"), _raw(**{key: value}), {"tool.py": TOOL_PY})
    with pytest.raises(ManifestError) as e:
        read(folder, strict=True)
    assert key in str(e.value) and ("看不見的字元" in str(e.value) or "換行" in str(e.value))
    assert read(folder).name == "tool"                                # 載入時（舊的工具）照舊


# ── 升級的紅字（ADR 0028 §3.1） ─────────────────────────────────────────

def _upgrade_changes(tmp_path, v1_key, v2_key, monkeypatch=None, official=()):
    if monkeypatch is not None:
        monkeypatch.setattr(signing, "OFFICIAL_PACK_PUBLIC_KEYS", tuple(official))
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _s = _stage(_pack_zip(tmp_path, "v1", "0.1.0", key=v1_key), tmp_path)
    admin.install_staged(token, data, packs, approved_by=1)
    token, _s = _stage(_pack_zip(tmp_path, "v2", "0.2.0", key=v2_key), tmp_path)
    report = upgrade.staged_upgrade(token, data, packs)
    return token, data, packs, [c for c in report["changes"] if c["kind"] == "signature"]


def test_upgrade_official_to_none_is_red(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    token, data, packs, changes = _upgrade_changes(tmp_path, key, None, monkeypatch, [_pub(key)])
    assert changes == [{"kind": "signature", "text": "以前是官方的，這一版不是官方", "alert": True}]
    result = upgrade.upgrade_staged(token, data, packs, approved_by=1)    # 紅字只是警告，可以升
    assert result["to"] == "0.2.0" and lock.entry(data, "tool")["signature"] == {"status": "none"}
    assert "🔴 以前是官方的，這一版不是官方" in upgrade.format_upgrade(result["report"])


def test_upgrade_author_key_change_is_red(tmp_path):
    _t, _d, _p, changes = _upgrade_changes(tmp_path, Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate())
    assert changes == [{"kind": "signature", "text": "簽章的鑰匙跟第一次裝的不一樣（可能換人做了，或有人冒名）",
                        "alert": True}]


def test_upgrade_same_author_key_and_none_to_signed(tmp_path):
    key = Ed25519PrivateKey.generate()
    _t, _d, _p, changes = _upgrade_changes(tmp_path, key, key)
    assert changes and not changes[0]["alert"]
    _t, _d, _p, changes = _upgrade_changes(tmp_path / "b", None, key)
    assert changes == [{"kind": "signature", "text": "這一版有簽章了", "alert": False}]
    _t, _d, _p, changes = _upgrade_changes(tmp_path / "c", key, None)
    assert changes[0]["alert"] and changes[0]["text"] == "以前有作者簽章，這一版沒有"
    _t, _d, _p, changes = _upgrade_changes(tmp_path / "d", None, None)
    assert changes == []


def test_upgrade_refuses_invalid(tmp_path):
    key = Ed25519PrivateKey.generate()
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _s = _stage(_pack_zip(tmp_path, "v1", "0.1.0", key=key), tmp_path)
    admin.install_staged(token, data, packs, approved_by=1)
    token, _s = _stage(_pack_zip(tmp_path, "v2", "0.2.0", key=key), tmp_path)
    folder = os.path.join(admin.staging_root(data), token, "pack")
    _break_staged_signature(folder)
    meta_path = os.path.join(admin.staging_root(data), token, admin.STAGED_META)
    meta = json.load(open(meta_path, encoding="utf-8"))
    meta["hashes"] = lock.hash_files(folder)
    json.dump(meta, open(meta_path, "w", encoding="utf-8"))
    with pytest.raises(admin.GateRefused):
        upgrade.upgrade_staged(token, data, packs, approved_by=1)
    assert lock.entry(data, "tool")["version"] == "0.1.0"


# ── 鑰匙的規矩 ─────────────────────────────────────────────────────────

def test_no_official_key_shipped_and_no_env_backdoor(monkeypatch):
    assert tuple(signing.OFFICIAL_PACK_PUBLIC_KEYS) == (             # 擁有者的工具鑰匙：現用＋備用（docs/signing.md §3）
        "d1wxFvSuyJZmUgrXn59aV55O0hLNvbzPT5dhi1CLmgI=", "NaolxxaDOQz0sGKMJsVBRMZ7IGLfk5WdInAGzgK/hAk=")
    before = signing.official_raw_keys()
    monkeypatch.setenv("SYNOX_UPDATE_TEST_PUBKEY", _pub(Ed25519PrivateKey.generate()))
    assert signing.official_raw_keys() == before                     # 沒有任何環境變數能加官方鑰匙


def test_no_private_key_anywhere_in_repo():
    pattern = re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----\s+[A-Za-z0-9+/]{40}")
    skip = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__", ".pytest_cache", "data"}
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            path = os.path.join(base, f)
            try:
                if os.path.getsize(path) > 2 * 1024 * 1024:
                    continue
                blob = open(path, "rb").read()
            except OSError:
                continue
            assert not pattern.search(blob), path


def test_private_key_refused_inside_repo(tmp_path):
    with pytest.raises(signing.SigningError):
        signing.load_private_key(os.path.join(ROOT, "x.pem"))
    assert signing.key_path_problem(os.path.join(ROOT, "x.pem"))
    assert signing.key_path_problem(str(tmp_path / "k.pem")) == ""
