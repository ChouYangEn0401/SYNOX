"""SYNOX 自己更新（docs/adr/0023）：檢查新版（假的 GitHub，不連網）、版本比較、每週檢查預設關、通知一次、簽章、
下載＋驗證＋解壓（prepare）、網頁 API、精靈的勾選、release.py sign、Update.bat／update.ps1 的靜態檢查。
Windows 上真的換檔（update.ps1 跑起來）在這台 Linux 沒辦法測：只檢查腳本的內容與順序。"""

import base64
import hashlib
import io
import json
import os
import re
import sys
import urllib.error
import zipfile

import pytest

from synox import __version__
from synox.update import check as upd
from synox.update import prepare, signing
from synox.wizard import logic

from test_web import Client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import release  # noqa: E402

pytestmark = pytest.mark.usefixtures("no_sockets")
DL = "https://github.com/ChouYangEn0401/SYNOX/releases/download/"


# ── 假的 GitHub ─────────────────────────────────────────────────────

def release_json(version="9.0.0", *, body="### 這版改了什麼\n\n- 修好精靈的按鈕\n- 新增檢查更新\n", name=None,
                 prerelease=False, assets=()):
    return json.dumps({"tag_name": "v" + version, "name": name or f"SYNOX {version}", "body": body,
                       "published_at": "2026-12-01T10:00:00Z", "prerelease": prerelease, "draft": False,
                       "html_url": f"https://github.com/ChouYangEn0401/SYNOX/releases/tag/v{version}",
                       "assets": [{"name": n, "browser_download_url": DL + f"v{version}/{n}", "size": len(b),
                                   **({"digest": "sha256:" + hashlib.sha256(b).hexdigest()} if dig else {})}
                                  for n, b, dig in assets]}).encode()


class FakeGitHub:
    """opener(url, timeout, limit, sink=None)：照網址回內容；記下每一次連線。"""

    def __init__(self, files=None, fail=None):
        self.files = dict(files or {})
        self.calls = []
        self.fail = fail

    def __call__(self, url, timeout, limit, sink=None):
        self.calls.append(url)
        if self.fail:
            raise self.fail
        if url not in self.files:
            return 404, None, b""
        value = self.files[url]
        if isinstance(value, tuple):                    # (status, location)
            return value[0], value[1], b""
        if sink is not None:
            sink.write(value)
            return 200, None, b""
        return 200, None, value


def github(version="9.0.0", **kw):
    return FakeGitHub({upd.API_URL: release_json(version, **kw)})


# ── 版本比較 ────────────────────────────────────────────────────────

@pytest.mark.parametrize("installed, latest, expect", [
    ("0.2.0", "0.2.1", "newer"), ("0.2.9", "0.2.10", "newer"), ("0.2.1-beta.1", "0.2.1", "newer"),
    ("0.2.1-alpha.2", "0.2.1-beta.1", "newer"), ("0.2.1", "0.2.1", "current"), ("0.3.0", "0.2.9", "ahead"),
    ("0.2.1", "0.2.1-beta.1", "ahead"), ("abc", "0.2.1", "invalid"),
])
def test_compare(installed, latest, expect):
    assert upd.compare(installed, latest) == expect


# ── 讀 GitHub 的回應 ────────────────────────────────────────────────

def test_parse_release_and_summary():
    rel = upd.parse_release(release_json("0.2.1", assets=[("SYNOX-0.2.1.zip", b"z", True)]))
    assert rel.version == "0.2.1" and rel.date == "2026-12-01" and rel.asset("SYNOX-0.2.1.zip").digest.startswith("sha256:")
    assert upd.summarize(rel.body) == "修好精靈的按鈕；新增檢查更新"
    assert upd.summarize("<!-- 維護者：x -->\n- **粗體** [連結](https://x)\n") == "粗體 連結"


@pytest.mark.parametrize("kw", [{"prerelease": True}, {"version": "0.2.1-beta.1"}])
def test_beta_is_never_offered(kw):
    version = kw.pop("version", "0.2.1")
    with pytest.raises(upd.UpdateError):
        upd.parse_release(release_json(version, **kw))


@pytest.mark.parametrize("blob", [b"not json", b"[]", b'{"tag_name": "latest"}'])
def test_parse_release_refuses_garbage(blob):
    with pytest.raises(upd.UpdateError):
        upd.parse_release(blob)


def test_check_newer_with_security_marker_and_tools_line():
    gh = github("9.0.0", name="🔒 安全更新 SYNOX 9.0.0")
    r = upd.check("0.2.0", opener=gh, tools=lambda: 3)
    assert gh.calls == [upd.API_URL]
    assert (r.status, r.latest, r.security, r.tools_newer) == ("newer", "9.0.0", True, 3)
    text = "\n".join(r.lines())
    assert "0.2.0 → 9.0.0" in text and "強烈建議更新" in text and "有 3 個工具可以更新" in text
    assert "修好精靈的按鈕" in text and "Update.bat" in text
    assert upd.check("0.2.0", opener=github(body="**強烈建議更新**：修了一個問題")).security


def test_check_current_ahead_and_signed_flag():
    assert upd.check("9.0.0", opener=github("9.0.0")).lines()[0].startswith("你是最新版")
    assert upd.check("9.1.0-beta.1", opener=github("9.0.0")).status == "ahead"
    assets = [(signing.MANIFEST_ASSET, b"{}", False), (signing.SIG_ASSET, b"x", False)]
    assert not upd.check("0.1.0", opener=github(assets=assets)).signed            # 沒有公鑰：不算有簽章
    key = base64.b64encode(b"k" * 32).decode()
    assert upd.check("0.1.0", opener=github(assets=assets), keys=[key]).signed


@pytest.mark.parametrize("gh, words", [
    (FakeGitHub(fail=urllib.error.URLError("down")), "連不到 GitHub"),
    (FakeGitHub(fail=TimeoutError()), "連不到 GitHub"),
    (FakeGitHub({}), "還沒有 SYNOX 的正式版"),
    (FakeGitHub({upd.API_URL: (302, "https://evil.example.com/x")}), "為了安全沒有跟過去"),
    (FakeGitHub({upd.API_URL: b"<html>"}), "看不懂"),
])
def test_check_failures_are_quiet(gh, words):
    r = upd.check("0.2.0", opener=gh, tools=lambda: 1 / 0)                   # 工具庫壞了也不影響
    assert r.status == "error" and words in r.message and r.tools_newer is None
    assert r.lines()[0].startswith("❌") and upd.RELEASES_PAGE in r.lines()[1]


def test_redirects_only_to_github():
    assert upd.allowed(upd.API_URL, first=True)
    assert upd.allowed(DL + "v1.0.0/SYNOX-1.0.0.zip", first=True)
    assert upd.allowed("https://release-assets.githubusercontent.com/x", first=False)
    for bad in ("http://api.github.com/repos/ChouYangEn0401/SYNOX/releases/latest",
                "https://api.github.com/repos/someone/else/releases/latest",
                "https://github.com/ChouYangEn0401/SYNOX_Libs/releases/download/v1/x",
                "https://release-assets.githubusercontent.com/x",
                "https://user:pw@github.com/ChouYangEn0401/SYNOX/releases/download/x",
                "https://github.com:8443/ChouYangEn0401/SYNOX/releases/download/x",
                "https://github.com/ChouYangEn0401/SYNOX/releases/download/../../x"):
        assert not upd.allowed(bad, first=True), bad


def test_install_kind(tmp_path):
    assert upd.install_kind(str(tmp_path)) in ("zip", "docker")
    (tmp_path / "installer-choices.json").write_text('{"source": "exe-installer"}', encoding="utf-8")
    assert upd.install_kind(str(tmp_path)) == "exe"
    (tmp_path / ".git").mkdir()
    assert upd.install_kind(str(tmp_path)) == "git"
    assert "git pull" in upd.how_line("git")


# ── 每週檢查：預設關、通知一次 ──────────────────────────────────────

def test_weekly_is_off_by_default_everywhere():
    assert upd.check_mode({}) == "manual" and upd.check_mode(None) == "manual"
    assert upd.check_mode({"updates": {"check": "daily"}}) == "manual"
    assert not logic.weekly_updates_default(None) and not logic.weekly_updates_default({})
    built = logic.build_config("", 1, {"kind": "none"})
    assert "updates" not in built and not upd.weekly_enabled(built)
    assert logic.with_weekly_updates(built, True)["updates"] == {"check": "weekly"}
    assert logic.weekly_updates_default(logic.with_weekly_updates(built, True))
    assert "updates" not in json.load(open(os.path.join(ROOT, "config.example.json"), encoding="utf-8"))


def test_weekly_tick_never_connects_when_off(tmp_path):
    gh, sent = github("9.0.0"), []
    assert upd.weekly_tick(str(tmp_path), {}, sent.append, installed="0.2.0", opener=gh) == "沒有打開每週檢查"
    assert gh.calls == [] and sent == [] and not os.listdir(tmp_path)


def test_weekly_tick_checks_once_a_week_and_notifies_once_per_version(tmp_path):
    raw, sent, now = {"updates": {"check": "weekly"}}, [], [1_000_000.0]
    gh = github("9.0.0")
    tick = lambda: upd.weekly_tick(str(tmp_path), raw, sent.append, installed="0.2.0", opener=gh, clock=lambda: now[0])
    assert "通知了" in tick() and len(sent) == 1 and "0.2.0 → 9.0.0" in sent[0]
    now[0] += 3600
    assert tick() == "這週查過了" and len(gh.calls) == 1
    now[0] += upd.WEEK
    assert "已經通知過" in tick() and len(sent) == 1 and len(gh.calls) == 2
    gh.files[upd.API_URL] = release_json("9.0.1")
    now[0] += upd.WEEK
    assert "通知了" in tick() and len(sent) == 2
    gh.fail = urllib.error.URLError("x")
    now[0] += upd.WEEK
    assert tick() == "這次沒查成（下週再試）" and len(sent) == 2


def test_runtime_registers_the_task(make_bot):
    bot = make_bot()
    rt = bot.app.extras["synox_runtime"]
    task = rt.loop.task("system.update_check")
    assert task is not None and task.interval == 6 * 3600


# ── 簽章 ────────────────────────────────────────────────────────────

def keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return key, base64.b64encode(pub).decode()


def test_signature_good_bad_missing():
    key, pub = keypair()
    other, other_pub = keypair()
    blob = b'{"version": "1.0.0", "assets": {}}'
    sig = base64.b64encode(key.sign(blob))
    assert signing.verify(blob, sig, [pub])
    assert signing.verify(blob, sig, [other_pub, pub])                       # 換鑰匙時新舊並存
    assert not signing.verify(blob + b" ", sig, [pub])                       # 內容被改
    assert not signing.verify(blob, base64.b64encode(other.sign(blob)), [pub])   # 別人的鑰匙
    assert not signing.verify(blob, sig, [])                                 # 沒有公鑰
    assert not signing.verify(blob, b"not base64!!", [pub]) and not signing.verify(blob, b"YWJj", [pub])
    assert signing.public_keys(["broken", base64.b64encode(b"short").decode(), pub]) == [base64.b64decode(pub)]


def test_no_public_key_is_shipped_yet_and_no_private_key_anywhere():
    assert signing.public_keys() == []                                       # 創始維護者還沒產生金鑰（ADR 0023 U5）
    for folder in ("src", "scripts", "setup"):
        for base, _dirs, files in os.walk(os.path.join(ROOT, folder)):
            for f in files:
                if f.endswith((".py", ".ps1", ".pem", ".key")):
                    blob = open(os.path.join(base, f), "rb").read()
                    assert not re.search(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----\s+[A-Za-z0-9+/]{40}", blob), f


# ── prepare：下載、驗證、解開 ────────────────────────────────────────

def make_zip(version, extra=None, init_version=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SYNOX/Setup.bat", "@echo off\r\n")
        z.writestr("SYNOX/Update.bat", "@echo off\r\n")
        z.writestr("SYNOX/src/synox/__init__.py", f'__version__ = "{init_version or version}"\n')
        z.writestr("SYNOX/requirements.txt", "requests>=2.28\n")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


def served(version="9.0.0", zip_blob=None, *, sums=None, manifest=None, sig=None, key=None, digest=True):
    zip_blob = zip_blob if zip_blob is not None else make_zip(version)
    name = f"SYNOX-{version}.zip"
    sha = hashlib.sha256(zip_blob).hexdigest()
    sums = sums if sums is not None else f"{sha}  {name}\n".encode()
    assets = [(name, zip_blob, digest), (signing.SUMS_ASSET, sums, False)]
    if key is not None and manifest is None:
        manifest = json.dumps({"version": version, "assets": {name: {"sha256": sha, "size": len(zip_blob)}}}).encode()
    if manifest is not None:
        sig = sig if sig is not None else base64.b64encode(key.sign(manifest)) + b"\n"
        assets += [(signing.MANIFEST_ASSET, manifest, False), (signing.SIG_ASSET, sig, False)]
    files = {upd.API_URL: release_json(version, assets=assets)}
    for n, b, _d in assets:
        files[DL + f"v{version}/{n}"] = b
    return FakeGitHub(files)


def synox_folder(tmp_path):
    root = tmp_path / "SYNOX"
    (root / "data").mkdir(parents=True)
    (root / "requirements.txt").write_text("requests>=2.28\n", encoding="utf-8")
    return str(root)


def test_unsigned_is_refused_unless_allowed(tmp_path):
    root = synox_folder(tmp_path)
    with pytest.raises(upd.UpdateError, match="AllowUnsigned"):
        prepare.prepare(root, installed="0.2.0", opener=served(), say=lambda *_: None)
    assert not os.path.exists(os.path.join(root, "data", "update"))           # 什麼都沒下載
    ready = prepare.prepare(root, installed="0.2.0", opener=served(), allow_unsigned=True, say=lambda *_: None)
    assert ready["version"] == "9.0.0" and ready["from"] == "0.2.0" and not ready["signed"]
    assert not ready["rebuild_venv"] and os.path.isfile(os.path.join(ready["stage"], "Update.bat"))
    assert json.load(open(os.path.join(root, "data", "update", "ready.json"), encoding="utf-8")) == ready


def test_signed_release_is_verified(tmp_path):
    root = synox_folder(tmp_path)
    key, pub = keypair()
    ready = prepare.prepare(root, installed="0.2.0", opener=served(key=key), keys=[pub], say=lambda *_: None)
    assert ready["signed"]


@pytest.mark.parametrize("case", ["wrong_key", "tampered_manifest", "manifest_other_zip", "manifest_version"])
def test_bad_signature_is_refused_even_with_allow_unsigned(tmp_path, case):
    root = synox_folder(tmp_path)
    key, pub = keypair()
    other, _ = keypair()
    zip_blob = make_zip("9.0.0")
    if case == "wrong_key":
        gh = served(key=other)
    elif case == "tampered_manifest":
        good = json.dumps({"version": "9.0.0", "assets": {}}).encode()
        gh = served(manifest=good + b" ", sig=base64.b64encode(key.sign(good)))
    elif case == "manifest_other_zip":
        gh = served(zip_blob=zip_blob, key=key, manifest=json.dumps(
            {"version": "9.0.0", "assets": {"SYNOX-9.0.0.zip": {"sha256": "0" * 64}}}).encode())
    else:
        gh = served(key=key, manifest=json.dumps({"version": "8.0.0", "assets": {}}).encode())
    with pytest.raises(upd.UpdateError) as e:
        prepare.prepare(root, installed="0.2.0", opener=gh, keys=[pub], allow_unsigned=True, say=lambda *_: None)
    assert "❌" in str(e.value)
    assert not os.path.exists(os.path.join(root, "data", "update"))


def test_min_from_is_respected(tmp_path):
    root = synox_folder(tmp_path)
    key, pub = keypair()
    blob = make_zip("9.0.0")
    manifest = json.dumps({"version": "9.0.0", "min_from": "1.0.0", "assets": {
        "SYNOX-9.0.0.zip": {"sha256": hashlib.sha256(blob).hexdigest()}}}).encode()
    with pytest.raises(upd.UpdateError, match="請先更新到 1.0.0"):
        prepare.prepare(root, installed="0.2.0", opener=served(zip_blob=blob, key=key, manifest=manifest),
                        keys=[pub], say=lambda *_: None)


def test_hash_mismatch_deletes_the_download(tmp_path):
    root = synox_folder(tmp_path)
    gh = served(digest=False)
    gh.files[DL + "v9.0.0/SYNOX-9.0.0.zip"] = make_zip("9.0.0") + b"x"       # 換過的 ZIP（大小也不對）
    with pytest.raises(upd.UpdateError, match="不一樣"):
        prepare.prepare(root, installed="0.2.0", opener=gh, allow_unsigned=True, say=lambda *_: None)
    assert not os.path.exists(os.path.join(root, "data", "update", "9.0.0"))
    with pytest.raises(upd.UpdateError, match="SHA256SUMS.txt 裡沒有"):
        prepare.prepare(root, installed="0.2.0", opener=served(sums=b"nothing\n"), allow_unsigned=True,
                        say=lambda *_: None)
    gh = served()
    gh.files[upd.API_URL] = gh.files[upd.API_URL].replace(b'"sha256:', b'"sha256:00')
    with pytest.raises(upd.UpdateError, match="指紋"):
        prepare.prepare(root, installed="0.2.0", opener=gh, allow_unsigned=True, say=lambda *_: None)


@pytest.mark.parametrize("extra, init", [({"SYNOX/../evil.txt": "x"}, None), ({"/abs.txt": "x"}, None),
                                         ({"other/x.txt": "x"}, None), ({}, "1.0.0")])
def test_unsafe_or_wrong_zip_is_refused(tmp_path, extra, init):
    root = synox_folder(tmp_path)
    with pytest.raises(upd.UpdateError, match="ZIP 裡面不對"):
        prepare.prepare(root, installed="0.2.0", opener=served(zip_blob=make_zip("9.0.0", extra, init)),
                        allow_unsigned=True, say=lambda *_: None)
    assert not (tmp_path / "evil.txt").exists() and not os.path.exists(os.path.join(root, "data", "update", "9.0.0"))


def test_zip_never_brings_user_data(tmp_path):
    root = synox_folder(tmp_path)
    blob = make_zip("9.0.0", {"SYNOX/config.json": "{}", "SYNOX/data/x": "x", "SYNOX/packs/p/pack.json": "{}"})
    ready = prepare.prepare(root, installed="0.2.0", opener=served(zip_blob=blob), allow_unsigned=True,
                            say=lambda *_: None)
    assert sorted(os.listdir(ready["stage"])) == ["Setup.bat", "Update.bat", "requirements.txt", "src"]


def test_not_newer_git_and_exe_do_not_download(tmp_path):
    root = synox_folder(tmp_path)
    gh = served()
    with pytest.raises(prepare.AlreadyCurrent):
        prepare.prepare(root, installed="9.0.0", opener=gh, allow_unsigned=True, say=lambda *_: None)
    with pytest.raises(prepare.AlreadyCurrent, match="Rollback"):
        prepare.prepare(root, installed="9.1.0", opener=gh, allow_unsigned=True, say=lambda *_: None)
    assert gh.calls == [upd.API_URL, upd.API_URL]
    os.mkdir(os.path.join(root, ".git"))
    with pytest.raises(upd.UpdateError, match="git pull"):
        prepare.prepare(root, installed="0.2.0", opener=gh, allow_unsigned=True, say=lambda *_: None)
    assert len(gh.calls) == 2


def test_rebuild_only_when_dependencies_change(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for d, ver in ((a, "0.2.0"), (b, "0.2.1")):
        d.mkdir()
        (d / "requirements.txt").write_text("requests>=2.28\n", encoding="utf-8")
        (d / "pyproject.toml").write_text(f'[project]\nversion = "{ver}"\ndependencies = ["requests>=2.28"]\n',
                                          encoding="utf-8")
    assert prepare.deps_fingerprint(str(a)) == prepare.deps_fingerprint(str(b))          # 只有版本號不一樣
    (b / "requirements.txt").write_text("requests>=2.28\ncryptography>=41\n", encoding="utf-8")
    assert prepare.deps_fingerprint(str(a)) != prepare.deps_fingerprint(str(b))


# ── release.py sign → prepare 驗得過 ───────────────────────────────

def test_release_sign_round_trip(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    key, pub = keypair()
    key_file = tmp_path / "key.pem"
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    dist = tmp_path / "dist"
    dist.mkdir()
    blob = make_zip("9.0.0")
    (dist / "SYNOX-9.0.0.zip").write_bytes(blob)
    out = release.sign(ROOT, str(dist), str(key_file), version="9.0.0", severity="security", summary="修安全問題")
    manifest, sig = (dist / "release.json").read_bytes(), (dist / "release.json.sig").read_bytes()
    assert signing.verify(manifest, sig, [pub]) and set(out) == {"SHA256SUMS.txt", "release.json", "release.json.sig"}
    data = json.loads(manifest)
    assert data["severity"] == "security" and data["assets"]["SYNOX-9.0.0.zip"]["sha256"] == hashlib.sha256(blob).hexdigest()
    assert signing.parse_sums((dist / "SHA256SUMS.txt").read_text())["SYNOX-9.0.0.zip"] == hashlib.sha256(blob).hexdigest()
    assert release.public_key_b64(release.load_private_key(str(key_file), ROOT)) == pub
    gh = served(zip_blob=blob, sums=(dist / "SHA256SUMS.txt").read_bytes(), manifest=manifest, sig=sig)
    ready = prepare.prepare(synox_folder(tmp_path), installed="0.2.0", opener=gh, keys=[pub], say=lambda *_: None)
    assert ready["signed"]


def test_release_key_must_stay_outside_the_repo(tmp_path, capsys):
    assert release.main(["keygen", "--out", os.path.join(ROOT, "x.pem")]) == 2
    assert not os.path.exists(os.path.join(ROOT, "x.pem"))
    assert release.main(["sign", "--key", os.path.join(ROOT, "README.md"), "--dist", str(tmp_path)]) == 2
    assert release.main(["sign", "--dist", str(tmp_path)]) == 2                # 沒給私鑰
    pub = release.keygen(str(tmp_path / "k.pem"))
    assert signing.public_keys([pub]) and oct((tmp_path / "k.pem").stat().st_mode)[-3:] in ("600", "666")
    assert release.main(["keygen", "--out", str(tmp_path / "k.pem")]) == 2   # 不蓋掉
    assert "repo" in capsys.readouterr().err


# ── 命令列 ──────────────────────────────────────────────────────────

def test_cli_check_and_weekly(tmp_path, capsys, monkeypatch):
    from synox import __main__ as cli
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": 1, "data_dir": str(tmp_path / "data")}), encoding="utf-8")
    ns = lambda **kw: cli.argparse.Namespace(config=str(cfg), check=True, weekly=None, prepare=False,
                                             allow_unsigned=False, rollback=False, **kw)
    monkeypatch.setattr(upd, "tools_newer_count", lambda installed, opener=None: 2)
    assert cli.cmd_update(ns(), opener=github("99.0.0")) == 10
    out = capsys.readouterr().out
    assert f"{__version__} → 99.0.0" in out and "有 2 個工具可以更新" in out and "--weekly on" in out
    assert upd.load_state(str(tmp_path / "data"))["result"]["latest"] == "99.0.0"
    assert cli.cmd_update(ns(), opener=github(__version__.split("-")[0])) in (0, 10)
    assert cli.cmd_update(ns(), opener=FakeGitHub(fail=OSError())) == 1
    args = ns()
    args.weekly = "on"
    assert cli.cmd_update(args) == 0
    assert json.loads(cfg.read_text(encoding="utf-8"))["updates"] == {"check": "weekly"}


def test_cli_parser_knows_update():
    from synox import __main__ as cli
    with pytest.raises(SystemExit) as e:
        cli.main(["update", "--help"])
    assert e.value.code == 0


# ── 網頁 ────────────────────────────────────────────────────────────

def test_web_update_card(make_bot, tmp_path, owner):
    from conftest import OTHER_ID
    from isdtelekit.users.roles import BasicRoles
    bot = make_bot(raw={"mode": "server"})
    (tmp_path / "config.json").write_text(json.dumps({"owner_id": owner}), encoding="utf-8")
    ui = bot.app.extras["synox_web"]
    ui.update_opener = github("99.0.0", name="🔒 安全更新")
    ui.catalog_opener = FakeGitHub(fail=OSError())                          # 工具庫連不到：本體照樣有結果
    c = Client(ui)
    c.login(owner)
    status, d = c.get("/api/settings/update")
    assert status == 200 and d["installed"] == __version__ and d["weekly"] is False and d["notice"] is None
    assert d["can_launch"] is False and d["last"] is None
    status, d = c.post("/api/settings/update/check", {})
    assert status == 200 and d["result"]["status"] == "newer" and d["result"]["security"]
    assert d["notice"] == {"latest": "99.0.0", "security": True,
                           "notes_url": "https://github.com/ChouYangEn0401/SYNOX/releases/tag/v99.0.0"}
    assert c.get("/api/settings/update")[1]["last"]["latest"] == "99.0.0"     # 存起來了（網頁重新整理還在）
    assert c.post("/api/settings/update/dismiss", {})[1]["notice"] is None
    assert c.post("/api/settings/update/weekly", {"enabled": True})[1]["weekly"] is True
    assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))["updates"]["check"] == "weekly"
    status, d = c.post("/api/settings/update/launch", {})
    assert status == 400                                                     # 這台不是 Windows／不是 ZIP 裝法
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    m = Client(ui)
    m.login(OTHER_ID)
    assert m.get("/api/settings/update")[0] == 403 and m.post("/api/settings/update/check", {})[0] == 403


def test_web_launch_opens_update_bat_detached(make_bot, tmp_path, monkeypatch, owner):
    from synox.update import web_api
    bot = make_bot()
    ui = bot.app.extras["synox_web"]
    monkeypatch.setattr(web_api.os, "name", "nt")
    (tmp_path / "Update.bat").write_text("@echo off\r\n", encoding="ascii")
    seen = []

    class User:
        tg_id = owner
    code, _h, body = web_api.launch(ui, User(), popen=lambda args, **kw: seen.append(args))
    assert code == 200 and "Update.bat" in json.loads(body)["message"]
    assert seen == [["cmd", "/c", "start", "SYNOX Update", str(tmp_path / "Update.bat")]]


def test_web_page_has_the_card_banner_and_wording():
    html = open(os.path.join(ROOT, "src", "synox", "web", "static", "app.html"), encoding="utf-8").read()
    system = html.split('data-tab="system" role="tabpanel">', 1)[1].split('<div class="tab-panel', 1)[0]
    assert 'id="set-update"' in system and "檢查更新" in system
    assert "每週幫我看一次有沒有新版（只看，不會自己裝）" in system
    assert 'id="upd-weekly" type="checkbox">' in system                           # 預設沒勾（值從伺服器來）
    assert 'id="update-banner"' in html and "/api/settings/update/dismiss" in html
    assert 'id="upd-confirm"' in system and "/api/settings/update/launch" in html


# ── Update.bat、update.ps1、bootstrap -Update（靜態檢查；Windows 才能真的跑）────────

def _ps(name):
    raw = open(os.path.join(ROOT, "setup", name), "rb").read()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""), name
    return raw.decode("utf-8-sig")


def test_update_bat_is_one_line_after_setlocal():
    raw = open(os.path.join(ROOT, "Update.bat"), "rb").read()
    text = raw.decode("ascii")
    code = [ln for ln in text.split("\r\n") if ln and not ln.lower().startswith(("rem ", "@echo"))]
    assert code[0] == "setlocal" and len(code) == 2                         # 換檔時 cmd.exe 已經讀進來的那一行
    line = code[1]
    assert line.index("clean-python-env.bat") < line.index(r'setup\update.ps1" %*') < line.index("pause")
    assert "-NoProfile -ExecutionPolicy Bypass" in line


def test_update_ps1_keeps_user_data_and_matches_python():
    text = _ps("update.ps1")
    keep = re.search(r"^\$Keep = @\(([^)]*)\)", text, re.M).group(1)
    assert tuple(re.findall(r"'([^']+)'", keep)) == prepare.KEEP
    assert {"config.json", "data", "packs", ".venv", "runtime", "_previous"} <= set(prepare.KEEP)
    assert re.search(r"^\$KeepCount = 2\r?$", text, re.M)                         # 決定 U8
    assert re.search(r"^param\(\[switch\]\$Rollback, \[switch\]\$AllowUnsigned, \[switch\]\$Yes\)", text, re.M)
    move = text.split("function Move-ProgramFiles", 1)[1].split("\nfunction ", 1)[0]
    assert "$Keep -contains $item.Name" in move and "continue" in move
    code = "\n".join(ln.split("#", 1)[0] for ln in text.splitlines())
    for name in ("config.json", "data", "packs"):                            # 從來不直接刪使用者的東西
        assert not re.search(r"Remove-Item[^\n]*\$Root\s*'%s'" % re.escape(name), code)
    assert not re.search(r"Remove-Item[^\n]*(\$Root|\$Config|\$Data)\b(?!\S)", code)


def test_update_ps1_order_check_ask_prepare_then_swap():
    text = _ps("update.ps1")
    body = text.split("function Invoke-Update", 1)[1]
    order = ["update --check", "Confirm-Step (T 'ask')", "'--prepare'", "Stop-Synox", "Move-ProgramFiles $Root $prev",
             "Move-ProgramFiles $stage $Root", "Limit-Previous", "Install-Packages", "Get-InstalledVersion",
             "Restore-Previous", "Start-Synox"]
    pos = [body.index(s) for s in order[:-1]] + [body.rindex("Start-Synox")]   # 失敗時也開回來；最後一定開
    assert pos == sorted(pos), order
    assert "$LASTEXITCODE -ne 10" in body and "$rc -eq 3" in body
    assert "--allow-unsigned" in body and "if ($AllowUnsigned)" in body       # 只有明確給了才加
    main = text.split("\n$code = 1", 1)[1]
    assert main.index("'.git'") < main.index("exe-installer") < main.index("Invoke-Update")
    assert "Invoke-Rollback" in main and "Start-Transcript" in main
    assert "Invoke-WebRequest" not in text and "Expand-Archive" not in text    # 下載、解壓都在 Python 驗過的那一條


def test_bootstrap_update_mode_only_installs_packages():
    text = _ps("bootstrap.ps1")
    assert re.search(r"^param\(.*\[switch\]\$Update\)", text, re.M)
    fn = text.split("function Update-PackagesOnly", 1)[1].split("\n}", 1)[0]
    assert "Install-Packages" in fn and "wizard" not in fn and "filetype" not in fn and "Read-Host" not in fn
    main = text.split("\ntry {", 1)[1]
    assert main.index("if ($Update) { Update-PackagesOnly; exit 0 }") < main.index("Read-SetupPlan")
    assert "-Update" in _ps("update.ps1").split("function Install-Packages", 1)[1].split("\n}", 1)[0]


def test_release_ships_the_updater_and_never_the_previous_folder():
    import make_zip
    shipped = {rel for _src, rel in make_zip.release_files()}
    assert {"Update.bat", "setup/update.ps1", "src/synox/update/prepare.py"} <= shipped
    assert make_zip.excluded("_previous/0.2.0-20261201-000000/Setup.bat")
    iss = open(os.path.join(ROOT, "setup", "installer", "synox.iss"), "rb").read().decode("ascii")
    assert 'Name: "{app}\\_previous"' in iss.split("[UninstallDelete]", 1)[1]
    assert "/_previous/" in open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
