"""更新檢查同時看「最新正式版」與「最新測試版」、更新通道（docs/adr/0045、docs/versioning.md「更新通道」）。

- 每次檢查問兩件事：releases/latest（正式版）＋ releases 清單裡 SemVer 最大的預覽版（不看 GitHub 的時間順序）。
- 卡片／`synox update --check` 一定列兩行；「有新版」照通道：stable（預設）只看正式版，preview 取兩者較大的。
- config.json `updates.channel`：選填，缺鍵＝stable（不用遷移）；`--include-prerelease`＝這一次當 preview。
- Update.bat -IncludePrerelease：check 與 prepare 用同一個通道，驗證（SHA256SUMS.txt、簽章）跟正式版同一條。
全部用假的 GitHub，不連網。
"""

import json
import os
import re

import pytest

from synox import __version__
from synox.update import check as upd
from synox.update import prepare, signing

from test_update import DL, FakeGitHub, _ps, make_zip, release_json, synox_folder
from test_web import Client

pytestmark = pytest.mark.usefixtures("no_sockets")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUIET = dict(say=lambda *_: None)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(upd.TEST_API_ENV, raising=False)
    monkeypatch.delenv(signing.TEST_KEY_ENV, raising=False)


def listing(*versions, draft=(), flag=None):
    """GitHub releases 清單：照給的順序（＝假裝的時間順序）。flag：{版本: prerelease 旗標}（預設看有沒有尾巴）。"""
    items = []
    for v in versions:
        item = json.loads(release_json(v, prerelease=(flag or {}).get(v, "-" in v)))
        item["draft"] = v in draft
        items.append(item)
    return json.dumps(items).encode()


def gh(stable=None, previews=(), *, latest_blob=None, list_blob=None, **kw):
    files = {}
    if latest_blob is not None:
        files[upd.API_URL] = latest_blob
    elif stable:
        files[upd.API_URL] = release_json(stable)
    if list_blob is not None:
        files[upd.API_LIST_URL] = list_blob
    elif previews or stable:
        files[upd.API_LIST_URL] = listing(*(list(previews) + ([stable] if stable else [])), **kw)
    return FakeGitHub(files)


def text(r):
    return "\n".join(r.lines())


# ── 四種情況：只有預覽版、只有正式版、兩者都有、兩者都沒有 ────────────────

def test_only_previews_shows_both_lines_and_no_error():
    """擁有者看到的情況：GitHub 上只有 0.2.2-alpha.1。舊程式：❌「還沒有正式版」、看不到測試版。"""
    r = upd.check("0.2.1", opener=gh(previews=["0.2.2-alpha.1"]))
    assert r.status == "none" and not r.lines()[0].startswith("❌")
    t = text(r)
    assert "最新正式版：還沒有正式版" in t
    assert "最新測試版：0.2.2-alpha.1（比你裝的新）" in t
    assert "測試版的號碼比同號的正式版小" in t
    assert "也提醒我有測試版" in t                                         # stable 通道：提示可以打開
    r = upd.check("0.2.1", opener=gh(previews=["0.2.2-alpha.1"]), include_prerelease=True)
    assert (r.status, r.latest, r.prerelease, r.channel) == ("newer", "0.2.2-alpha.1", True, "preview")
    assert "也提醒我有測試版" not in text(r)


def test_latest_pointing_at_an_alpha_counts_as_no_stable_release():
    """0.2.2-alpha.1 在 GitHub 上被標成 Latest（非 pre-release）：不是正式版，也不是「看不懂」。"""
    latest = release_json("0.2.2-alpha.1", prerelease=False)
    r = upd.check("0.2.2-alpha.1", opener=gh(latest_blob=latest,
                                              list_blob=listing("0.2.2-alpha.1", flag={"0.2.2-alpha.1": False})))
    assert r.status == "none" and r.stable == {"state": "none"}
    assert "最新測試版：0.2.2-alpha.1（跟你裝的一樣）" in text(r)


def test_only_stable_release():
    r = upd.check("0.2.2", opener=gh("0.2.2"))
    assert r.status == "current" and r.lines()[0].startswith("你是最新版")
    assert "最新正式版：0.2.2（跟你裝的一樣）" in text(r) and "最新測試版：沒有測試版" in text(r)
    r = upd.check("0.2.1", opener=gh("0.2.2"), include_prerelease=True)
    assert (r.status, r.latest, r.prerelease) == ("newer", "0.2.2", False)


def test_both_stable_and_preview():
    g = gh("0.2.2", ["0.2.3-beta.1", "0.2.2-beta.1"])
    r = upd.check("0.2.2", opener=g)
    assert r.status == "current"                                            # stable：測試版不算「有新版」
    assert "最新正式版：0.2.2（跟你裝的一樣）" in text(r) and "最新測試版：0.2.3-beta.1（比你裝的新）" in text(r)
    r = upd.check("0.2.2", opener=g, include_prerelease=True)
    assert (r.status, r.latest) == ("newer", "0.2.3-beta.1")
    # 正式版比測試版大（0.2.2 > 0.2.2-beta.1）：preview 通道也是挑正式版
    r = upd.check("0.2.1", opener=gh("0.2.2", ["0.2.2-beta.1"]), include_prerelease=True)
    assert (r.latest, r.prerelease) == ("0.2.2", False)
    assert "最新測試版：0.2.2-beta.1（比你裝的新）" in text(r)
    r = upd.check("0.2.2", opener=gh("0.2.2", ["0.2.2-beta.1"]))
    assert "最新測試版：0.2.2-beta.1（比你裝的舊）" in text(r)


def test_neither_stable_nor_preview():
    for channel in (False, True):
        r = upd.check("0.2.1", opener=FakeGitHub({}), include_prerelease=channel)
        assert r.status == "none" and not r.lines()[0].startswith("❌")
        assert "最新正式版：還沒有正式版" in text(r) and "最新測試版：沒有測試版" in text(r)
    assert upd.check("0.2.1", opener=FakeGitHub({upd.API_LIST_URL: b"[]"})).preview == {"state": "none"}


# ── 排序：SemVer，不看 GitHub 的時間順序 ──────────────────────────────────

def test_preview_is_picked_by_semver_not_by_github_order():
    # GitHub 的順序（新發的在前）：alpha.2 比 alpha.10 晚發（例如補發），草稿不算
    g = gh(previews=["0.2.2-alpha.2", "0.2.2-alpha.10", "0.2.2-alpha.9", "0.2.3-alpha.1"], draft=("0.2.3-alpha.1",))
    r = upd.check("0.2.1", opener=g)
    assert r.preview["version"] == "0.2.2-alpha.10"
    assert upd.compare("0.2.2-alpha.2", "0.2.2-alpha.10") == "newer"
    assert upd.compare("0.2.2-alpha.1", "0.2.2") == "newer" and upd.compare("0.2.2", "0.2.2-alpha.1") == "ahead"
    assert upd.compare("0.2.2-alpha.1", "0.2.2-beta.1") == "newer"


def test_installed_alpha_sees_the_same_numbered_stable_as_newer():
    r = upd.check("0.2.2-alpha.1", opener=gh("0.2.2", ["0.2.2-alpha.1"]))
    assert (r.status, r.latest) == ("newer", "0.2.2")
    assert "最新測試版：0.2.2-alpha.1（跟你裝的一樣）" in text(r)


# ── 回應格式不對：不壞，那一行顯示「無法判斷」 ──────────────────────────

@pytest.mark.parametrize("list_blob", [
    b"not json", b'{"message": "rate limited"}', json.dumps([{"name": "no tag"}, {"tag_name": "v1.2"},
                                                             {"tag_name": "vbanana", "prerelease": True}]).encode()])
def test_malformed_preview_list_never_breaks_the_check(list_blob):
    r = upd.check("0.2.1", opener=gh(latest_blob=release_json("0.2.2"), list_blob=list_blob))
    assert (r.status, r.latest) == ("newer", "0.2.2")                       # 正式版那一邊照常
    line = next(ln for ln in r.lines() if ln.startswith("最新測試版"))
    if list_blob.startswith(b"["):
        assert line == "最新測試版：沒有測試版"                              # 看不懂的項目跳過
    else:
        assert line.startswith("最新測試版：無法判斷（")


@pytest.mark.parametrize("latest_blob", [b"<html>", b'{"tag_name": 12}', b'{"name": "x"}', b"[1, 2]"])
def test_malformed_latest_shows_unknown_and_error(latest_blob):
    r = upd.check("0.2.1", opener=gh(latest_blob=latest_blob, list_blob=listing("0.2.2-beta.1")))
    assert r.status == "error" and r.lines()[0].startswith("❌")
    assert any(ln.startswith("最新正式版：無法判斷（") for ln in r.lines())
    assert "最新測試版：0.2.2-beta.1（比你裝的新）" in text(r)
    # preview 通道：正式版看不懂，還是可以照測試版判斷
    r = upd.check("0.2.1", opener=gh(latest_blob=latest_blob, list_blob=listing("0.2.2-beta.1")),
                  include_prerelease=True)
    assert (r.status, r.latest) == ("newer", "0.2.2-beta.1")


def test_offline_marks_both_lines_unknown():
    r = upd.check("0.2.1", opener=FakeGitHub(fail=OSError("down")))
    assert r.status == "error"
    assert "最新正式版：無法判斷（連不到 GitHub）" in text(r) and "最新測試版：無法判斷（連不到 GitHub）" in text(r)


def test_installed_version_not_semver_is_unknown():
    r = upd.check("dev-build", opener=gh("0.2.2", ["0.2.3-beta.1"]))
    assert r.status == "error" and "比不出新舊" in r.message
    assert "最新正式版：無法判斷（比不出新舊）" in text(r)


# ── 通道設定（config.json updates.channel）───────────────────────────────

def test_channel_setting_defaults_to_stable_and_needs_no_migration(tmp_path):
    from synox.datastore import core
    assert upd.channel(None) == upd.channel({}) == "stable"
    assert upd.channel({"updates": {"check": "weekly"}}) == "stable"           # 舊的 config：缺鍵
    assert upd.channel({"updates": {"channel": "nightly"}}) == "stable"        # 寫錯
    assert upd.channel({"updates": "preview"}) == "stable"
    assert upd.channel({"updates": {"channel": "preview"}}) == "preview"
    cfg = upd.set_channel({"owner_id": 1, "updates": {"check": "weekly"}}, True)
    assert cfg["updates"] == {"check": "weekly", "channel": "preview"}
    assert upd.set_channel(cfg, False)["updates"]["channel"] == "stable"
    # 資料版本框架（ADR 0044）：新增選填鍵不用遷移步驟；舊檔照常升到目前版本、不會多出這個鍵
    old = tmp_path / "config.json"
    old.write_text(json.dumps({"owner_id": 1, "updates": {"check": "weekly"}}), encoding="utf-8")
    core.upgrade_config(str(old))
    after = json.loads(old.read_text(encoding="utf-8"))
    assert after["schema_version"] == core.CONFIG.current and upd.channel(after) == "stable"
    new = tmp_path / "new.json"
    new.write_text(json.dumps({"schema_version": core.CONFIG.current, "owner_id": 1,
                               "updates": {"channel": "preview"}}), encoding="utf-8")
    assert core.upgrade_config(str(new)).action == "current" and upd.wants_preview(json.loads(new.read_text("utf-8")))
    assert "updates" not in json.load(open(os.path.join(ROOT, "config.example.json"), encoding="utf-8"))


def test_weekly_tick_follows_the_channel(tmp_path):
    g, sent = gh("0.2.2", ["0.2.3-beta.1"]), []
    raw = {"updates": {"check": "weekly"}}
    assert upd.weekly_tick(str(tmp_path / "a"), raw, sent.append, installed="0.2.2", opener=g) == "沒有新版"
    assert sent == []                                                       # stable：測試版不通知
    raw = {"updates": {"check": "weekly", "channel": "preview"}}
    said = upd.weekly_tick(str(tmp_path / "b"), raw, sent.append, installed="0.2.2", opener=g)
    assert "0.2.3-beta.1" in said and len(sent) == 1 and "0.2.2 → 0.2.3-beta.1" in sent[0]


# ── 命令列：--include-prerelease 與設定一致 ────────────────────────────────

def _ns(cli, cfg, **kw):
    base = dict(config=str(cfg), check=True, weekly=None, prepare=False, allow_unsigned=False, rollback=False,
                include_prerelease=False, from_zip=None, channel=None)
    base.update(kw)
    return cli.argparse.Namespace(**base)


def test_cli_flag_and_setting_agree(tmp_path, capsys, monkeypatch):
    from synox import __main__ as cli
    monkeypatch.setattr(upd, "tools_newer_count", lambda installed, opener=None: 0)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": 1, "data_dir": str(tmp_path / "data")}), encoding="utf-8")
    g = gh("0.0.1", ["99.0.0-beta.1"])
    assert cli.cmd_update(_ns(cli, cfg), opener=g) == 0                     # 預設不變：只看正式版
    out = capsys.readouterr().out
    assert "最新正式版：0.0.1（比你裝的舊）" in out and "最新測試版：99.0.0-beta.1（比你裝的新）" in out
    assert cli.cmd_update(_ns(cli, cfg, include_prerelease=True), opener=g) == 10
    flag_out = capsys.readouterr().out
    assert upd.load_state(str(tmp_path / "data"))["result"]["status"] != "newer"   # 只是這一次：不存
    assert cli.cmd_update(_ns(cli, cfg, check=False, channel="preview")) == 0
    assert json.loads(cfg.read_text(encoding="utf-8"))["updates"]["channel"] == "preview"
    capsys.readouterr()
    assert cli.cmd_update(_ns(cli, cfg), opener=g) == 10                    # 設定 preview ＝ 加 flag
    setting_out = capsys.readouterr().out
    assert setting_out == flag_out
    assert upd.load_state(str(tmp_path / "data"))["result"]["latest"] == "99.0.0-beta.1"   # 設定的：存（網頁看得到）
    assert cli.cmd_update(_ns(cli, cfg, check=False, channel="stable")) == 0
    assert upd.channel(json.loads(cfg.read_text(encoding="utf-8"))) == "stable"
    with pytest.raises(SystemExit):
        cli.main(["update", "--help"])
    assert "--channel" in capsys.readouterr().out


# ── 網頁卡片 ─────────────────────────────────────────────────────────────

def test_web_card_shows_two_lines_and_channel_switch(make_bot, tmp_path, owner):
    bot = make_bot(raw={"mode": "server"})
    (tmp_path / "config.json").write_text(json.dumps({"owner_id": owner}), encoding="utf-8")
    ui = bot.app.extras["synox_web"]
    ui.update_opener = gh(previews=["99.0.0-alpha.1"])
    ui.catalog_opener = FakeGitHub(fail=OSError())
    c = Client(ui)
    c.login(owner)
    status, d = c.get("/api/settings/update")
    assert status == 200 and d["channel"] == "stable"
    d = c.post("/api/settings/update/check", {})[1]
    lines = d["result"]["lines"]
    assert "最新正式版：還沒有正式版" in lines and "最新測試版：99.0.0-alpha.1（比你裝的新）" in lines
    assert d["result"]["status"] == "none" and d["notice"] is None          # stable：沒有「有新版」
    d = c.post("/api/settings/update/channel", {"preview": True})[1]
    assert d["channel"] == "preview"
    assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))["updates"]["channel"] == "preview"
    d = c.post("/api/settings/update/check", {})[1]
    assert d["result"]["status"] == "newer" and d["notice"]["latest"] == "99.0.0-alpha.1"
    d = c.post("/api/settings/update/channel", {"preview": False})[1]
    assert d["channel"] == "stable" and d["notice"] is None                 # 改回只收正式版：測試版的橫幅不再出現


def test_web_page_has_the_preview_switch():
    html = open(os.path.join(ROOT, "src", "synox", "web", "static", "app.html"), encoding="utf-8").read()
    card = html.split('id="set-update"', 1)[1].split('id="upd-check"', 1)[0]
    assert 'id="upd-preview" type="checkbox">' in card and "也提醒我有測試版" in card     # 預設沒勾（值從伺服器來）
    assert "正式版和最新的測試版" in card and "/api/settings/update/channel" in html


# ── prepare 與 Update.bat：測試版一樣要驗 SHA256SUMS.txt／簽章 ────────────

def served_preview(stable="0.2.1", preview="0.2.2-beta.1", *, sums=True):
    blob = make_zip(preview)
    import hashlib
    name = f"SYNOX-{preview}.zip"
    assets = [(name, blob, True)]
    if sums:
        assets.append((signing.SUMS_ASSET, f"{hashlib.sha256(blob).hexdigest()}  {name}\n".encode(), False))
    items = [json.loads(release_json(preview, prerelease=True, assets=assets)), json.loads(release_json(stable))]
    files = {upd.API_URL: release_json(stable), upd.API_LIST_URL: json.dumps(items).encode()}
    for n, b, _d in assets:
        files[DL + f"v{preview}/{n}"] = b
    return FakeGitHub(files)


def test_prepare_preview_only_when_asked_and_verified_the_same_way(tmp_path):
    root = synox_folder(tmp_path)
    with pytest.raises(prepare.AlreadyCurrent):                             # stable：0.2.1 已經是最新的正式版
        prepare.prepare(root, installed="0.2.1", opener=served_preview(), allow_unsigned=True, **QUIET)
    with pytest.raises(upd.UpdateError, match="AllowUnsigned"):             # 沒簽章：一樣要明確同意
        prepare.prepare(root, installed="0.2.1", opener=served_preview(), include_prerelease=True, **QUIET)
    with pytest.raises(upd.UpdateError, match="SHA256SUMS"):                # 沒有 SHA256SUMS.txt：一樣不更新
        prepare.prepare(root, installed="0.2.1", opener=served_preview(sums=False), include_prerelease=True,
                        allow_unsigned=True, **QUIET)
    said = []
    ready = prepare.prepare(root, installed="0.2.1", opener=served_preview(), include_prerelease=True,
                            allow_unsigned=True, say=said.append)
    assert ready["version"] == "0.2.2-beta.1" and any("測試版" in s for s in said)
    with pytest.raises(prepare.AlreadyCurrent):                             # 不降級：裝著的比較新
        prepare.prepare(root, installed="0.2.2", opener=served_preview(), include_prerelease=True,
                        allow_unsigned=True, **QUIET)


def test_prepare_with_no_stable_release_is_nothing_to_do(tmp_path):
    with pytest.raises(prepare.AlreadyCurrent, match="IncludePrerelease"):
        prepare.prepare(synox_folder(tmp_path), installed="0.2.1", opener=FakeGitHub({}), **QUIET)


def test_cli_prepare_uses_the_channel(tmp_path, capsys):
    from synox import __main__ as cli
    root = synox_folder(tmp_path)
    cfg = os.path.join(root, "config.json")
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump({"owner_id": 1, "updates": {"channel": "preview"}}, f)
    ns = _ns(cli, cfg, check=False, prepare=True, allow_unsigned=True)
    assert cli.cmd_update(ns, opener=served_preview()) == 0
    assert json.load(open(os.path.join(root, "data", "update", "ready.json"), encoding="utf-8"))["version"] == \
        "0.2.2-beta.1"


def test_update_ps1_include_prerelease_goes_to_check_and_prepare():
    text = _ps("update.ps1")
    body = text.split("\nfunction Invoke-Update", 1)[1].split("\nfunction ", 1)[0]
    assert "if ($IncludePrerelease) { $check += '--include-prerelease' }" in body
    assert "if ($IncludePrerelease) { $prep += '--include-prerelease' }" in body
    assert body.index("$check += '--include-prerelease'") < body.index("& $VenvPy @check") < body.index("'--prepare'")
    # 版本比較只在 Python（SemVer）；這支只在換完檔確認「裝著的＝要裝的」
    assert not re.search(r"\[version\]|-gt\s+\$|-lt\s+\$", text)
    bat = open(os.path.join(ROOT, "Update.bat"), "rb").read().decode("ascii")
    assert "-IncludePrerelease" in bat
