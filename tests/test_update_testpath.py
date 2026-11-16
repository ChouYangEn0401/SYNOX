"""先測 SYNOX 自己更新（還沒有真的發佈時；docs/release-playbook.md「先測更新」）：

- `synox update --check --include-prerelease`：只有明確加才看預覽版（問 releases 清單），預設從來不看、結果不存。
- 環境變數 SYNOX_UPDATE_API（只給測試）：只從環境變數讀、只收本機的檔案／127.0.0.1，用的時候大聲說。
- `synox update --prepare --from-zip`（Update.bat -FromZip）：本機的 ZIP；旁邊的 SHA256SUMS.txt、簽章有就要對；
  沒有簽章要 --allow-unsigned；測試公鑰 SYNOX_UPDATE_TEST_PUBKEY 只在測試路徑算數。
- scripts/make_update_testkit.py：舊版 ZIP＋假的新版 ZIP＋檢查檔＋假的 releases.json＋README，不動 repo。
全部不連網、不開埠；Windows 上真的換檔（update.ps1）這裡跑不了（tests/test_update.py 有靜態檢查）。
"""

import base64
import hashlib
import json
import os
import sys
import zipfile

import pytest

from synox import __version__
from synox.update import check as upd
from synox.update import prepare, signing

from test_update import FakeGitHub, github, keypair, make_zip, release_json, synox_folder

pytestmark = pytest.mark.usefixtures("no_sockets")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUIET = dict(say=lambda *_: None)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(upd.TEST_API_ENV, raising=False)
    monkeypatch.delenv(signing.TEST_KEY_ENV, raising=False)


# ── --include-prerelease ─────────────────────────────────────────────

def _list(*versions, draft=()):
    items = [json.loads(release_json(v, prerelease="-" in v)) for v in versions]
    for item in items:
        item["draft"] = item["tag_name"][1:] in draft
    return json.dumps(items).encode()


def test_prerelease_only_with_the_explicit_flag():
    gh = FakeGitHub({upd.API_URL: release_json("0.2.0"), upd.API_LIST_URL: _list("0.3.0-beta.2", "0.2.0", "0.3.0-beta.1",
                                                                                   "0.4.0-beta.1", draft=("0.4.0-beta.1",))})
    r = upd.check("0.2.0", opener=gh)
    assert gh.calls == [upd.API_URL] and r.status == "current"                # 預設：只問 latest（只有正式版）
    r = upd.check("0.2.0", opener=gh, include_prerelease=True)
    assert gh.calls[-1] == upd.API_LIST_URL and (r.status, r.latest, r.prerelease) == ("newer", "0.3.0-beta.2", True)
    assert any("預覽版" in line and "--include-prerelease" in line for line in r.lines())   # 草稿不算
    assert upd.allowed(upd.API_LIST_URL, first=True)
    with pytest.raises(upd.UpdateError):
        upd.parse_release(_list("0.3.0-beta.1"))                              # 沒有明確要：清單裡的預覽版不算
    with pytest.raises(upd.UpdateError):
        upd.parse_release(release_json("0.3.0-beta.1", prerelease=True))


def test_cli_include_prerelease_does_not_save_the_result(tmp_path, capsys):
    from synox import __main__ as cli
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": 1, "data_dir": str(tmp_path / "data")}), encoding="utf-8")
    gh = FakeGitHub({upd.API_LIST_URL: _list("99.0.0-beta.1")})
    ns = cli.argparse.Namespace(config=str(cfg), check=True, weekly=None, prepare=False, allow_unsigned=False,
                                rollback=False, include_prerelease=True, from_zip=None)
    assert cli.cmd_update(ns, opener=gh) == 10
    assert "連預覽版一起看" in capsys.readouterr().out
    assert upd.load_state(str(tmp_path / "data")) == {}                        # 不出網頁橫幅、不影響每週通知
    with pytest.raises(SystemExit):
        cli.main(["update", "--help"])
    assert "--include-prerelease" in capsys.readouterr().out


# ── SYNOX_UPDATE_API（只給測試）──────────────────────────────────────

def test_test_api_only_accepts_local_targets():
    assert upd.is_local("file:///C:/kit/releases.json") and upd.is_local("http://127.0.0.1:8765/r.json")
    assert upd.is_local("http://localhost/r.json") and upd.is_local("http://[::1]:9/r.json")
    for bad in ("https://evil.example.com/r.json", "http://10.0.0.1/r.json", "http://127.0.0.1.evil.com/r",
                "file://evil.example.com/share/r.json", "http://user:pw@127.0.0.1/r", "ftp://127.0.0.1/r",
                "relative/releases.json", ""):
        assert not upd.local_url(bad), bad
    assert upd.local_url(os.path.abspath("x.json")).startswith("file://")


def test_test_api_is_only_read_from_the_environment():
    src = open(upd.__file__, encoding="utf-8").read()
    assert src.count("TEST_API_ENV") == 3 and 'os.environ.get(TEST_API_ENV, "")' in src      # 定義、讀、log
    for name in ("web_api.py", "__init__.py", "prepare.py"):
        assert "SYNOX_UPDATE_API\"" not in open(os.path.join(os.path.dirname(upd.__file__), name), encoding="utf-8").read()


def test_remote_test_api_is_refused_loudly(monkeypatch):
    monkeypatch.setenv(upd.TEST_API_ENV, "https://evil.example.com/releases.json")
    gh = FakeGitHub(fail=AssertionError("不該連網"))
    r = upd.check("0.2.0", opener=gh)
    assert r.status == "error" and "只能指到這台電腦" in r.message and gh.calls == []
    assert r.lines()[0].startswith("⚠️⚠️ 測試模式") and "evil.example.com" in r.lines()[0]


def _kit(tmp_path, version="0.2.1-test.1", key=None, prerelease=True):
    """假的發佈：ZIP、SHA256SUMS.txt（＋release.json／.sig）在 new/，releases.json 的附檔是 file:// 網址。"""
    new = tmp_path / "kit" / "new"
    new.mkdir(parents=True)
    name = f"SYNOX-{version}.zip"
    blob = make_zip(version)
    (new / name).write_bytes(blob)
    sha = hashlib.sha256(blob).hexdigest()
    (new / "SHA256SUMS.txt").write_text(f"{sha}  {name}\n", encoding="utf-8")
    if key is not None:
        manifest = json.dumps({"version": version, "assets": {name: {"sha256": sha, "size": len(blob)}}}).encode()
        (new / "release.json").write_bytes(manifest)
        (new / "release.json.sig").write_bytes(base64.b64encode(key.sign(manifest)) + b"\n")
    assets = [{"name": f.name, "browser_download_url": f.resolve().as_uri(), "size": f.stat().st_size}
              for f in sorted(new.iterdir())]
    rel = tmp_path / "kit" / "releases.json"
    rel.write_text(json.dumps({"tag_name": "v" + version, "name": "test", "body": "", "prerelease": prerelease,
                               "draft": False, "assets": assets}), encoding="utf-8")
    return new / name, rel


def test_test_mode_runs_the_real_check_and_prepare_against_local_files(tmp_path, monkeypatch):
    key, pub = keypair()
    zip_path, rel = _kit(tmp_path, key=key)
    monkeypatch.setenv(upd.TEST_API_ENV, str(rel))
    r = upd.check("0.2.0")
    assert (r.status, r.latest, r.test_source) == ("newer", "0.2.1-test.1", str(rel))
    assert r.lines()[0].startswith("⚠️⚠️ 測試模式") and "預覽版" not in "\n".join(r.lines())
    assert upd.notice_text(r).startswith("⚠️⚠️ 測試模式")                    # 通知最上面也說
    root = synox_folder(tmp_path)
    said = []
    with pytest.raises(upd.UpdateError, match="AllowUnsigned"):              # 測試公鑰沒設：一樣算沒簽章
        prepare.prepare(root, installed="0.2.0", say=said.append)
    assert said[0].startswith("⚠️⚠️ 測試模式")
    monkeypatch.setenv(signing.TEST_KEY_ENV, pub)
    ready = prepare.prepare(root, installed="0.2.0", **QUIET)
    assert ready["signed"] and ready["version"] == "0.2.1-test.1" and ready["test"] == str(rel)
    assert os.path.isfile(os.path.join(ready["stage"], "Setup.bat"))


def test_test_mode_assets_must_be_local_too(tmp_path, monkeypatch):
    zip_path, rel = _kit(tmp_path)
    raw = json.loads(rel.read_text(encoding="utf-8"))
    raw["assets"][0]["browser_download_url"] = "https://github.com/ChouYangEn0401/SYNOX/releases/download/v1/x.zip"
    rel.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setenv(upd.TEST_API_ENV, rel.as_uri())
    root = synox_folder(tmp_path)
    with pytest.raises(upd.UpdateError):
        prepare.prepare(root, installed="0.2.0", allow_unsigned=True, **QUIET)
    work = os.path.join(root, "data", "update")
    assert not os.path.isdir(work) or not os.listdir(work)                    # 什麼都沒留下


def test_test_key_is_ignored_by_the_real_github_update(tmp_path, monkeypatch):
    key, pub = keypair()
    from test_update import served
    monkeypatch.setenv(signing.TEST_KEY_ENV, pub)                             # 沒有 SYNOX_UPDATE_API：正式的路
    with pytest.raises(upd.UpdateError, match="AllowUnsigned"):
        prepare.prepare(synox_folder(tmp_path), installed="0.2.0", opener=served(key=key), **QUIET)
    assert not upd.check("0.1.0", opener=github(assets=[(signing.MANIFEST_ASSET, b"{}", False),
                                                         (signing.SIG_ASSET, b"x", False)])).signed


# ── --from-zip（Update.bat -FromZip）───────────────────────────────

def test_from_zip_unsigned_needs_the_flag_and_keeps_user_data(tmp_path):
    zip_path, _rel = _kit(tmp_path)
    root = synox_folder(tmp_path)
    said = []
    with pytest.raises(upd.UpdateError, match="AllowUnsigned"):
        prepare.prepare_from_zip(root, str(zip_path), installed="0.2.0", say=said.append)
    assert said[0].startswith("⚠️ 用這台電腦上的 ZIP") and "SHA256SUMS.txt 一樣" in said[1]
    work = os.path.join(root, "data", "update")
    assert not os.path.isdir(work) or not os.listdir(work)                    # 什麼都沒解開
    ready = prepare.prepare_from_zip(root, str(zip_path), installed="0.2.0", allow_unsigned=True, **QUIET)
    assert (ready["version"], ready["from"], ready["signed"]) == ("0.2.1-test.1", "0.2.0", False)
    assert ready["source"] == str(zip_path) and ready["keep"] == list(prepare.KEEP)
    assert ready["stage"].startswith(os.path.join(root, "data", "update"))
    assert json.load(open(os.path.join(root, "data", "update", "ready.json"), encoding="utf-8")) == ready


def test_from_zip_checks_sums_next_to_it(tmp_path):
    zip_path, _rel = _kit(tmp_path)
    root = synox_folder(tmp_path)
    sums = zip_path.parent / "SHA256SUMS.txt"
    sums.write_text("0" * 64 + f"  {zip_path.name}\n", encoding="utf-8")
    with pytest.raises(upd.UpdateError, match="不一樣"):
        prepare.prepare_from_zip(root, str(zip_path), installed="0.2.0", allow_unsigned=True, **QUIET)
    sums.write_text("0" * 64 + "  other.zip\n", encoding="utf-8")
    with pytest.raises(upd.UpdateError, match="沒有"):
        prepare.prepare_from_zip(root, str(zip_path), installed="0.2.0", allow_unsigned=True, **QUIET)
    sums.unlink()                                                             # 沒有檢查檔：照實說，還是要 --allow-unsigned
    said = []
    prepare.prepare_from_zip(root, str(zip_path), installed="0.2.0", allow_unsigned=True, say=said.append)
    assert any("沒有 SHA256SUMS.txt" in s for s in said)


def test_from_zip_signature_with_the_test_key(tmp_path, monkeypatch):
    key, pub = keypair()
    other, other_pub = keypair()
    zip_path, _rel = _kit(tmp_path, key=key)
    root = synox_folder(tmp_path)
    monkeypatch.setenv(signing.TEST_KEY_ENV, other_pub)
    with pytest.raises(upd.UpdateError, match="簽章對不上"):                  # 有公鑰但驗不過：加了旗子也拒絕
        prepare.prepare_from_zip(root, str(zip_path), installed="0.2.0", allow_unsigned=True, **QUIET)
    monkeypatch.setenv(signing.TEST_KEY_ENV, pub)
    said = []
    ready = prepare.prepare_from_zip(root, str(zip_path), installed="0.2.0", say=said.append)
    assert ready["signed"] and any(s.startswith("⚠️⚠️ 測試模式：也信任") for s in said)


def test_from_zip_refuses_old_same_git_and_garbage(tmp_path):
    zip_path, _rel = _kit(tmp_path)
    root = synox_folder(tmp_path)
    with pytest.raises(prepare.AlreadyCurrent):
        prepare.prepare_from_zip(root, str(zip_path), installed="0.2.1-test.1", allow_unsigned=True, **QUIET)
    with pytest.raises(prepare.AlreadyCurrent, match="Rollback"):
        prepare.prepare_from_zip(root, str(zip_path), installed="0.3.0", allow_unsigned=True, **QUIET)
    with pytest.raises(upd.UpdateError, match="找不到"):
        prepare.prepare_from_zip(root, str(tmp_path / "nope.zip"), installed="0.2.0", allow_unsigned=True, **QUIET)
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"not a zip")
    with pytest.raises(upd.UpdateError, match="版本"):
        prepare.prepare_from_zip(root, str(junk), installed="0.2.0", allow_unsigned=True, **QUIET)
    evil = tmp_path / "evil" / "SYNOX-0.2.1.zip"
    evil.parent.mkdir()
    evil.write_bytes(make_zip("0.2.1", extra={"SYNOX/../escape.txt": "x"}))
    with pytest.raises(upd.UpdateError, match="不安全"):
        prepare.prepare_from_zip(root, str(evil), installed="0.2.0", allow_unsigned=True, **QUIET)
    os.makedirs(os.path.join(root, ".git"))
    with pytest.raises(upd.UpdateError, match="git pull"):
        prepare.prepare_from_zip(root, str(zip_path), installed="0.2.0", allow_unsigned=True, **QUIET)


def test_cli_prepare_from_zip(tmp_path, capsys):
    from synox import __main__ as cli
    zip_path, _rel = _kit(tmp_path, version="99.0.0-test.1")
    root = synox_folder(tmp_path)
    cfg = os.path.join(root, "config.json")
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump({"owner_id": 1}, f)
    ns = lambda **kw: cli.argparse.Namespace(config=cfg, check=False, weekly=None, prepare=True, rollback=False,
                                             include_prerelease=False, from_zip=str(zip_path), **kw)
    assert cli.cmd_update(ns(allow_unsigned=False)) == 1
    assert "-AllowUnsigned" in capsys.readouterr().out
    assert cli.cmd_update(ns(allow_unsigned=True)) == 0
    assert "99.0.0-test.1 準備好了" in capsys.readouterr().out
    assert os.path.isfile(os.path.join(root, "data", "update", "ready.json"))


# ── scripts/make_update_testkit.py ──────────────────────────────────

def _zip_version(path):
    with zipfile.ZipFile(path) as z:
        return prepare.zip_version(path), z.namelist()


def test_testkit_builds_old_new_sums_signature_and_fake_release(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import make_update_testkit as kit
    before = {rel: open(os.path.join(ROOT, rel), "rb").read() for rel in ("src/synox/__init__.py", "pyproject.toml")}
    out = str(tmp_path / "kit")
    made = kit.build(out)
    assert {rel: open(os.path.join(ROOT, rel), "rb").read() for rel in before} == before   # repo 沒有動
    test = kit.default_test_version(__version__)
    assert made["current"] == __version__ and made["test"] == test and upd.compare(__version__, test) == "newer"
    old_v, old_names = _zip_version(made["old_zip"])
    new_v, new_names = _zip_version(made["new_zip"])
    assert (old_v, new_v) == (__version__, test) and old_names == new_names
    assert "SYNOX/Update.bat" in new_names and not any(n.startswith("SYNOX/tests/") for n in new_names)
    with zipfile.ZipFile(made["new_zip"]) as z:
        assert f'version = "{test}"' in z.read("SYNOX/pyproject.toml").decode("utf-8")
    new_dir = os.path.join(out, "new")
    sums = signing.parse_sums(open(os.path.join(new_dir, "SHA256SUMS.txt"), encoding="utf-8").read())
    assert sums == {os.path.basename(made["new_zip"]): prepare._sha256(made["new_zip"])}
    blob = open(os.path.join(new_dir, "release.json"), "rb").read()
    assert signing.verify(blob, open(os.path.join(new_dir, "release.json.sig"), "rb").read(), [made["public_key"]])
    assert not signing.verify(blob, open(os.path.join(new_dir, "release.json.sig"), "rb").read())   # 真的 SYNOX 不信它
    rel = upd.parse_release(open(os.path.join(out, "releases.json"), "rb").read(), allow_prerelease=True)
    assert rel.version == test and all(upd.is_local(a.url) for a in rel.assets)
    readme = open(made["readme"], encoding="utf-8").read()
    for words in ("Update.bat -FromZip", "-AllowUnsigned", "Update.bat -Rollback", "synox about", "SYNOX_UPDATE_API",
                  made["public_key"], "config.json"):
        assert words in readme, words
    # 這份測試包真的能走完 Python 那一半：本機 ZIP（測試公鑰）、測試模式（假的 releases.json）
    root = synox_folder(tmp_path)
    monkeypatch.setenv(signing.TEST_KEY_ENV, made["public_key"])
    assert prepare.prepare_from_zip(root, made["new_zip"], **QUIET)["signed"]
    monkeypatch.setenv(upd.TEST_API_ENV, os.path.join(out, "releases.json"))
    ready = prepare.prepare(root, **QUIET)
    assert ready["signed"] and ready["version"] == test


def test_testkit_refuses_to_write_into_the_repo_or_a_full_folder(tmp_path):
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import make_update_testkit as kit
    with pytest.raises(ValueError, match="outside"):
        kit.build(os.path.join(ROOT, "dist", "kit"))
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / "x").write_text("x")
    with pytest.raises(ValueError, match="not empty"):
        kit.build(str(tmp_path / "full"))
    with pytest.raises(ValueError, match="newer"):
        kit.build(str(tmp_path / "k2"), version="0.0.1")
    assert kit.default_test_version("0.2.0") == "0.2.1-test.1"
    assert kit.default_test_version("1.4.9-beta.2") == "1.4.10-test.1"
