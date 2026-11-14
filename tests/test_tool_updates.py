"""工具（pack）的更新：`synox tools check`／`synox tools update`、網頁「有 N 個工具可以更新」＋「全部更新」、
每週檢查的工具通知。外觀包（kind=theme）也算。

- 只有指令／按鈕／打開的每週檢查才連網；網址照樣寫死在 packs/catalog.py（假的網路 FakeWeb，不連網、不開埠）。
- 更新＝跟安裝同一條路：下載（大小、sha256 對清單）→ 第 1、2 關 → 報告 → --yes／網頁按確認 → 第 3 關。從來不自己裝。
"""

import json
import os
import urllib.error

import pytest

from synox.packs import admin, catalog, lock
from synox.update import check as upd

from test_pack_library import FakeWeb, _entry, _web
from test_security import _write_pack, _zip_dir
from test_theme import _zip as _theme_zip
from test_update import github
from test_upgrade import TOOL_PY, _cli_raw
from test_web import Client, ui_of

pytestmark = pytest.mark.usefixtures("no_sockets")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tool_blob(tmp_path, version, tag=None):
    src = _write_pack(str(tmp_path / "src" / (tag or version)), _cli_raw(version), {"tool.py": TOOL_PY})
    return _zip_dir(src)


def _theme_blob(version):
    return _theme_zip(patch=lambda raw: raw.update(version=version))


def _setup(tmp_path):
    """裝好 tool 0.1.0（cli）和外觀包 sample-lantern 1.0.0；config.json 指到這裡的 data/。"""
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    for blob in (_tool_blob(tmp_path, "0.1.0"), _theme_blob("1.0.0")):
        token, _s = admin.stage(blob, data)
        admin.install_staged(token, data, packs, approved_by=1, via="test")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": 42, "data_dir": data}), encoding="utf-8")
    return data, packs, str(cfg)


def _library(tmp_path, tool="0.2.0", theme="1.1.0", extra=()):
    tblob, hblob = _tool_blob(tmp_path, tool, "lib-" + tool), _theme_blob(theme)
    entries = [_entry("tool", tool, tblob),
               _entry("sample-lantern", theme, hblob, kind="theme", title="提燈", capabilities=[])] + list(extra)
    return _web(entries, {f"tool-{tool}.synoxpack": tblob, f"sample-lantern-{theme}.synoxpack": hblob})


def _ns(cfg, packs, cmd, names=(), **kw):
    from synox import __main__ as cli
    return cli.argparse.Namespace(config=cfg, tools_cmd=cmd, names=list(names), all=kw.get("all", False),
                                  library="", yes=kw.get("yes", False), trust_publisher=None, packs_dir=packs)


# ── 清單（純函式）────────────────────────────────────────────────────

def test_updates_lists_installed_tools_and_themes_that_are_newer(tmp_path):
    web = _library(tmp_path, extra=[_entry("money", "0.3.0", b"x" * 10)])
    lib = catalog.fetch_library(opener=web)
    ups = catalog.updates(lib, {"tool": "0.1.0", "sample-lantern": "1.0.0", "money": "0.3.0", "gone": "1.0.0"})
    assert [(u["name"], u["kind"], u["installed"], u["version"]) for u in ups] == [
        ("sample-lantern", "theme", "1.0.0", "1.1.0"), ("tool", "tool", "0.1.0", "0.2.0")]
    assert catalog.updates(lib, {}) == []                                      # 沒裝的不算「更新」
    assert catalog.updates(lib, {"tool": "0.3.0"}) == []                      # 裝著的比較新也不算
    assert upd.tools_newer_count({"tool": "0.1.0", "sample-lantern": "1.0.0"}, opener=web) == 2   # 外觀包也算


# ── 命令列 ──────────────────────────────────────────────────────────

def test_cli_tools_check_lists_newer_and_never_installs(tmp_path, capsys):
    from synox import __main__ as cli
    data, packs, cfg = _setup(tmp_path)
    web = _library(tmp_path)
    assert cli.cmd_tools(_ns(cfg, packs, "check"), opener=web) == 10
    out = capsys.readouterr().out
    assert "有 2 個工具可以更新" in out and "tool（工具：打招呼） 0.1.0 → 0.2.0" in out
    assert "sample-lantern（外觀包：提燈） 1.0.0 → 1.1.0" in out and "tools update --all" in out
    assert not any(u.endswith(".synoxpack") for u in web.calls)              # 只看清單，不下載
    assert admin.list_staged(data) == [] and lock.entry(data, "tool")["version"] == "0.1.0"
    assert cli.cmd_tools(_ns(cfg, packs, "check"), opener=_library(tmp_path, "0.1.0", "1.0.0")) == 0
    assert "都是最新版" in capsys.readouterr().out
    assert cli.cmd_tools(_ns(cfg, packs, "check"), opener=FakeWeb(fail=urllib.error.URLError("x"))) == 1
    assert "連不到工具庫" in capsys.readouterr().out


def test_cli_tools_update_without_yes_only_stages_and_shows_the_report(tmp_path, capsys):
    from synox import __main__ as cli
    data, packs, cfg = _setup(tmp_path)
    rc = cli.cmd_tools(_ns(cfg, packs, "update", ["tool"]), opener=_library(tmp_path), is_up=lambda port: False)
    out = capsys.readouterr().out
    assert rc == 1 and "這是升級" in out and "還沒裝" in out
    assert "python -m synox tools update tool --yes" in out                  # 怎麼在終端機核准
    assert [s["name"] for s in admin.list_staged(data)] == ["tool"]           # 只有暫存（等你核准）
    assert lock.entry(data, "tool")["version"] == "0.1.0"


def test_cli_tools_update_all_yes_goes_through_the_same_report_and_lock(tmp_path, capsys):
    from synox import __main__ as cli
    data, packs, cfg = _setup(tmp_path)
    web = _library(tmp_path)
    assert cli.cmd_tools(_ns(cfg, packs, "update", all=True, yes=True), opener=web, is_up=lambda port: False) == 0
    out = capsys.readouterr().out
    assert out.count("這是升級") == 2 and out.count("升級好了") == 2 and "1/2" in out and "2/2" in out
    assert lock.entry(data, "tool")["version"] == "0.2.0"
    assert lock.entry(data, "sample-lantern")["version"] == "1.1.0"          # 外觀包也一起
    assert cli.cmd_tools(_ns(cfg, packs, "update", all=True, yes=True), opener=web) == 0
    assert "沒有要更新的" in capsys.readouterr().out


def test_cli_tools_update_names_and_refusals(tmp_path, capsys):
    from synox import __main__ as cli
    data, packs, cfg = _setup(tmp_path)
    assert cli.cmd_tools(_ns(cfg, packs, "update"), opener=_library(tmp_path)) == 2   # 沒給名字、沒 --all
    assert "--all" in capsys.readouterr().out
    rc = cli.cmd_tools(_ns(cfg, packs, "update", ["nope"]), opener=_library(tmp_path))
    assert rc == 2 and "沒有裝 nope" in capsys.readouterr().out
    rc = cli.cmd_tools(_ns(cfg, packs, "update", ["tool"]), opener=_library(tmp_path, "0.1.0"))
    assert rc == 0 and "已經是最新版" in capsys.readouterr().out
    # 清單寫 tool 0.2.0，檔案裡卻是 0.3.0：不留暫存、不裝
    wrong = _tool_blob(tmp_path, "0.3.0", "wrong")
    web = _web([_entry("tool", "0.2.0", wrong)], {"tool-0.2.0.synoxpack": wrong})
    rc = cli.cmd_tools(_ns(cfg, packs, "update", ["tool"], yes=True), opener=web, is_up=lambda port: False)
    assert rc == 2 and catalog.TEXT["not_listed"] in capsys.readouterr().out
    assert admin.list_staged(data) == [] and lock.entry(data, "tool")["version"] == "0.1.0"


def test_cli_tools_update_opens_the_web_report_once(tmp_path, capsys):
    from synox import __main__ as cli
    data, packs, cfg = _setup(tmp_path)
    opened = []
    rc = cli.cmd_tools(_ns(cfg, packs, "update", all=True), opener=_library(tmp_path), is_up=lambda port: True,
                       open_url=opened.append)
    assert rc == 0 and len(opened) == 1 and "#packs" in opened[0]             # 兩個都在「等你核准」，網頁只開一次
    assert sorted(s["name"] for s in admin.list_staged(data)) == ["sample-lantern", "tool"]
    assert lock.entry(data, "tool")["version"] == "0.1.0"                    # 還沒核准：沒換


def test_cli_parser_knows_tools_check_and_update():
    from synox import __main__ as cli
    for sub in ("check", "update"):
        with pytest.raises(SystemExit) as e:
            cli.main(["tools", sub, "--help"])
        assert e.value.code == 0


# ── 網頁 ────────────────────────────────────────────────────────────

def test_web_library_lists_updates_including_themes(make_bot, owner, tmp_path):
    from synox.packs import loader
    user_packs = tmp_path / "userpacks"
    user_packs.mkdir()
    bot = make_bot(pack_dirs=(str(user_packs),) + loader.PACK_DIRS)
    c = Client(ui_of(bot))
    c.login(owner)
    status, _h, body = c.raw("POST", "/api/packs/upload", _theme_blob("1.0.0"))
    assert c.post("/api/packs/install", {"token": json.loads(body)["token"]})[0] == 200
    ui_of(bot).catalog_opener = _library(tmp_path)
    status, d = c.post("/api/packs/library")
    assert status == 200
    assert [(u["name"], u["kind"], u["installed"], u["version"]) for u in d["updates"]] == [
        ("sample-lantern", "theme", "1.0.0", "1.1.0")]
    status, summary = c.post("/api/packs/library/install", {"name": "sample-lantern"})
    assert status == 200 and summary["upgrade"] and summary["kind"] == "theme"   # 同一份報告，還要人按確認


def test_web_page_has_update_all_banner_that_queues_through_the_report():
    html = open(os.path.join(ROOT, "src", "synox", "web", "static", "app.html"), encoding="utf-8").read()
    lib = html.split('<div id="set-library"', 1)[1].split('<div id="set-skills"', 1)[0]
    assert 'id="lib-updates"' in lib and 'id="lib-update-all"' in lib and "全部更新" in lib
    js = html.split("// ── 工具庫（官方）")[1].split("// ── 工具庫 end")[0]
    assert "有 {n} 個工具可以更新" in js
    queue = js.split("function libQueueNext", 1)[1].split("\n  }\n", 1)[0]
    assert "libInstall(" in queue and "/api/packs/install" not in js        # 一個一個走同一份報告；不自己按確認
    assert '"synox:install-step"' in js and 'd.step !== "done" && d.step !== "idle"' in js
    assert "libHint(r.tools_newer)" in html                                   # 「檢查更新」看到的數目也提示


# ── 每週檢查：工具也通知（同一組版本一次）────────────────────────────

def test_weekly_tick_notifies_tool_updates_once_per_set(tmp_path):
    raw, sent, now = {"updates": {"check": "weekly"}}, [], [1_000_000.0]
    ups = [[{"name": "money", "title": "記帳", "kind": "tool", "installed": "0.2.0", "version": "0.3.0"},
            {"name": "sample-lantern", "title": "提燈", "kind": "theme", "installed": "1.0.0", "version": "1.1.0"}]]
    gh = github("0.0.1")                                                     # 本體沒有新版
    tick = lambda: upd.weekly_tick(str(tmp_path), raw, sent.append, installed="0.2.0", opener=gh,
                                   clock=lambda: now[0], tools=lambda: ups[0])
    assert "2 個工具有新版（通知了擁有者）" in tick() and len(sent) == 1
    assert "有 2 個工具可以更新" in sent[0] and "外觀 sample-lantern 1.0.0 → 1.1.0" in sent[0]
    assert "tools update --all" in sent[0] and "核准" in sent[0]
    assert upd.load_state(str(tmp_path))["result"]["tools_newer"] == 2        # 網頁「檢查更新」那格也看得到
    now[0] += upd.WEEK
    assert "已經通知過" in tick() and len(sent) == 1                           # 同一組：不再通知
    ups[0] = ups[0][:1] + [dict(ups[0][1], version="1.2.0")]
    now[0] += upd.WEEK
    assert "通知了擁有者" in tick() and len(sent) == 2                         # 換了一組版本：再通知一次
    ups[0] = []
    now[0] += upd.WEEK
    assert tick() == "沒有新版" and len(sent) == 2


def test_weekly_tick_tools_are_off_when_weekly_is_off_and_failures_are_quiet(tmp_path):
    sent = []
    called = []
    assert upd.weekly_tick(str(tmp_path), {}, sent.append, opener=github("9.0.0"),
                           tools=lambda: called.append(1)) == "沒有打開每週檢查"
    assert called == [] and sent == []
    raw = {"updates": {"check": "weekly"}}
    said = upd.weekly_tick(str(tmp_path), raw, sent.append, installed="0.2.0", opener=github("9.0.0"),
                           tools=lambda: 1 / 0)
    assert "通知了" in said and len(sent) == 1 and "可以更新" not in sent[0]   # 工具庫壞了不影響本體的通知


def test_self_update_notice_and_tool_notice_are_separate(tmp_path):
    raw, sent = {"updates": {"check": "weekly"}}, []
    ups = [{"name": "money", "title": "記帳", "kind": "tool", "installed": "0.2.0", "version": "0.3.0"}]
    upd.weekly_tick(str(tmp_path), raw, sent.append, installed="0.2.0", opener=github("9.0.0"), tools=lambda: ups)
    assert len(sent) == 2 and "0.2.0 → 9.0.0" in sent[0] and "可以更新" not in sent[0]
    assert "money 0.2.0 → 0.3.0" in sent[1]
