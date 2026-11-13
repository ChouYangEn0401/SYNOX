"""工具服務 WP1：web.app 的宣告（第 1 關）、畫面的掃描（第 2 關）、信任層級、報告、升級紅字、工具端介面、kit 的小工具。"""

import csv
import io
import json
import os
import shutil

import pytest

from synox.packs import admin, kit, scan, tier, upgrade
from synox.packs.manifest import ManifestError, read, validate

from conftest import FIXTURE_PACKS

pytestmark = pytest.mark.usefixtures("no_sockets")
COUNTER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "app_pack", "counter")


@pytest.fixture
def pack(tmp_path):
    folder = tmp_path / "counter"
    shutil.copytree(COUNTER, folder)
    return folder


def raw_of(folder):
    return json.loads((folder / "pack.json").read_text(encoding="utf-8"))


def write(folder, raw):
    (folder / "pack.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")


def with_app(folder, **changes):
    raw = raw_of(folder)
    app = dict(raw["web"]["app"])
    for k, v in changes.items():
        if v is None:
            app.pop(k, None)
        else:
            app[k] = v
    raw["web"]["app"] = app
    return raw


def test_good_fixture_passes_gates_1_and_2_and_is_t1():
    m = read(COUNTER, strict=True)
    app = m.web["app"]
    assert app["entry"] == "app/index.html" and app["root"] == "app" and app["kit"] == 1
    assert app["actions"] == {"add": "write", "reset": "danger", "poke": "write"} and app["reads"] == ["state"]
    assert app["files"] == ["app/app.css", "app/app.js", "app/index.html"] and app["remote"] is True
    report = scan.scan(m)
    assert report.problems(m) == []
    assert not [f for f in report.findings if f.kind in ("app", "app_note")]
    assert tier.assess(m, report)["tier"] == "T1" and tier.assess(m)["tier"] == "T1"


@pytest.mark.parametrize("changes,needle", [
    ({"root": ".."}, "web.app.root"), ({"root": "/abs"}, "web.app.root"), ({"root": "."}, "web.app.root"),
    ({"root": "\\\\host\\share"}, "網路路徑"), ({"entry": "index.html"}, "web.app.entry"),
    ({"entry": "app/missing.html"}, "web.app.entry"), ({"actions": {"add": "READ"}}, "web.app.actions.add"),
    ({"kit": None}, "web.app.kit"), ({"kit": 2}, "只認得"), ({"kit": "1"}, "web.app.kit"),
    ({"idle": 5}, "idle"), ({"exports": "state_csv"}, "web.app.exports"), ({"exports": ["Bad!"]}, "exports"),
    ({"exports": ["a", "a"]}, "重複"), ({"reads": [], "actions": {}}, "至少"), ({"remote": "yes"}, "remote"),
    ({"title": "x" * 30}, "web.app.title"),
])
def test_gate1_rejects(pack, changes, needle):
    raw = with_app(pack, **changes)
    with pytest.raises(ManifestError) as e:
        validate(raw, str(pack), strict=True)
    assert needle in str(e.value)
    m = validate(raw, str(pack), strict=False) if needle != "網路路徑" else None   # 已裝的舊工具：當作沒有 app
    if m is not None:
        assert m.web["app"] is None


@pytest.mark.parametrize("name,size", [("x.py", 10), ("x.exe", 10), ("big.js", 600 * 1024)])
def test_gate1_rejects_files(pack, name, size):
    (pack / "app" / name).write_bytes(b"a" * size)
    with pytest.raises(ManifestError) as e:
        validate(raw_of(pack), str(pack), strict=True)
    assert name in str(e.value)


def test_gate1_too_many_files_and_kind_cli(pack):
    for i in range(101):
        (pack / "app" / f"f{i}.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ManifestError) as e:
        validate(raw_of(pack), str(pack), strict=True)
    assert "太多" in str(e.value)
    raw = raw_of(pack)
    raw["kind"] = "cli"
    raw["cli"] = {"argv": ["{python}", "t.py"], "commands": [{"name": "add", "argv": ["a"], "effect": "WRITE"}]}
    with pytest.raises(ManifestError) as e:
        validate(raw, str(pack), strict=True)
    assert "kind=python" in str(e.value)


def test_js_outside_app_root_is_still_opaque(pack):
    (pack / "helper.js").write_text("1", encoding="utf-8")
    m = read(str(pack), strict=True)
    assert tier.assess(m, scan.scan(m))["tier"] == "T2"


@pytest.mark.parametrize("html,detail", [
    ('<script src="/_synox/kit.js"></script><script>alert(1)</script>', "內嵌的 <script>"),
    ('<script src="/_synox/kit.js"></script><button onclick="x()">x</button>', "on… 屬性"),
    ('<base href="/"><script src="/_synox/kit.js"></script>', "<base>"),
    ('<script src="/_synox/kit.js"></script><iframe src="a.html"></iframe>', "<iframe>"),
    ('<script src="/_synox/kit.js"></script><script src="https://evil.example/x.js"></script>', "外面"),
    ('<script src="/_synox/kit.js"></script><img src="//evil.example/a.png">', "外面"),
    ('<p>no kit</p><script src="app.js"></script>', "第一個 <script>"),
    ('<script src="app.js"></script><script src="/_synox/kit.js"></script>', "第一個 <script>"),
    ('<meta http-equiv="refresh" content="0"><script src="/_synox/kit.js"></script>', "http-equiv"),
])
def test_appscan_blocks(pack, html, detail):
    (pack / "app" / "index.html").write_text(f"<!doctype html><html><body>\n{html}\n</body></html>", encoding="utf-8")
    m = read(str(pack), strict=True)
    report = scan.scan(m)
    blocked = [f for f in report.findings if f.kind == "app"]
    assert blocked and any(detail in f.detail for f in blocked)
    assert all(f.file == "app/index.html" and f.line >= 1 for f in blocked if "第一個" not in f.detail)
    assert report.problems(m)


@pytest.mark.parametrize("name,text,label", [
    ("app.js", "// see https://example.com\n", "外面的網址"), ("app.js", "var u = 'https://x.example/a';\n", "外面的網址"),
    ("app.css", "@import 'a.css';\n", "@import"), ("app.js", "eval('1')\n", "eval("),
    ("app.js", "fetch('/x')\n", "fetch("), ("app.js", "navigator.serviceWorker.register('a')\n", "serviceWorker"),
])
def test_appscan_notes_do_not_block(pack, name, text, label):
    with open(pack / "app" / name, "a", encoding="utf-8") as f:
        f.write(text)
    m = read(str(pack), strict=True)
    report = scan.scan(m)
    notes = [f for f in report.findings if f.kind == "app_note"]
    assert any(label in f.detail for f in notes) and all(f.line >= 1 for f in notes)
    assert report.problems(m) == []


def test_svg_namespace_is_not_a_note(pack):
    (pack / "app" / "i.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>', encoding="utf-8")
    m = read(str(pack), strict=True)
    assert not [f for f in scan.scan(m).findings if f.kind.startswith("app")]


def test_report_text_and_summary():
    m = read(COUNTER, strict=True)
    report = scan.scan(m)
    s = admin.summary_of(m, report, {}, [])
    assert s["app"] == {"title": "計數器", "kit": 1, "files": 3, "reads": ["state"],
                        "actions": {"add": "write", "reset": "danger", "poke": "write"}, "exports": ["state_csv"],
                        "remote": True}
    text = " ".join(s["warnings"])
    assert "不經你同意" in text and "以 SYNOX 自己的畫面為準" in text and "state_csv" in text and "手機" in text


def test_old_packs_report_unchanged():
    for name in ("money", "notes"):
        m = read(os.path.join(FIXTURE_PACKS, name), strict=False)
        assert m.web.get("app") is None
        s = admin.summary_of(m, scan.scan(m), {}, [])
        assert s["app"] is None and not any("網頁畫面" in w for w in s["warnings"])


def test_upgrade_flags(pack):
    old_raw = raw_of(pack)
    new = read(str(pack), strict=True)
    no_app_raw = dict(old_raw)
    no_app_raw["web"] = {}
    no_app = validate(no_app_raw, str(pack), strict=True)
    changes = upgrade.app_changes(no_app, new)
    assert changes[0]["kind"] == "app" and changes[0]["alert"]
    more = validate(with_app(pack, actions={"add": "DANGER", "reset": "DANGER", "poke": "WRITE", "zap": "WRITE"},
                             exports=["state_csv", "all_csv"]), str(pack), strict=True)
    kinds = {(c["kind"], c["alert"]) for c in upgrade.app_changes(new, more)}
    assert ("app_action_added", True) in kinds and ("app_export_added", True) in kinds and ("app_effect", True) in kinds
    back = {(c["kind"], c["alert"]) for c in upgrade.app_changes(more, new)}
    assert ("app_effect", False) in back and ("app_action_removed", False) in back
    local = validate(with_app(pack, remote=False), str(pack), strict=True)
    assert [c["alert"] for c in upgrade.app_changes(local, new) if c["kind"] == "app_remote"] == [True]
    assert any(c["kind"] == "app" for c in upgrade.diff_manifests(no_app, new))


def test_pack_app_registration(make_bot):
    bot = make_bot(pack_dirs=(FIXTURE_PACKS, os.path.dirname(COUNTER)))
    p = next(x for x in bot.app.extras["synox_packs"] if x.name == "counter")
    assert set(p.app_reads) == {"state"} and set(p.app_actions) == {"add", "reset", "poke"}
    assert set(p.app_exports) == {"state_csv"} and "reset" in p.app_describe
    for fn in (p.app_read, p.app_action, p.app_export):
        with pytest.raises(ValueError):
            fn("undeclared", lambda *a: None)


def test_check_values_same_as_parse_args():
    fields = (kit.Field("amount", "金額", required=True, check=kit.number), kit.Field("kind", "種類", choices=("a", "b")),
              kit.Field("memo", "備註", default="無"))
    _v, _m, typed = kit.parse_args(fields, ["abc", "kind=z"], positional=1)
    clean, missing, errors = kit.check_values(fields, {"amount": "abc", "kind": "z"})
    assert errors == typed == ["金額要是數字", "種類 只能是 a/b"]
    clean, missing, errors = kit.check_values(fields, {"kind": "a"})
    assert [f.name for f in missing] == ["amount"] and clean["memo"] == "無" and not errors
    assert kit.check_values(fields, {"amount": "1\x00"})[2] == kit.parse_args(fields, ["1\x00"])[2]
    assert kit.check_values(fields, {"zzz": "1"})[2] == ["有不認得的欄位。"]
    assert kit.check_values(fields, {"amount": "1" * 2001})[2] == ["太長了。"]


def test_csv_bytes():
    data = kit.csv_bytes(["a", "b"], [[1, -5], [None, "=1+1"], ["+x", "-5"], ["@a", "\tt"], ["\nn", 'x,"y"\nz'],
                                      [1.5, "ok"]])
    assert data.startswith("﻿".encode("utf-8"))
    text = data.decode("utf-8")[1:]
    assert "\r\n" in text and text.count("\r\n") >= 7
    rows = list(csv.reader(io.StringIO(text, newline="")))
    assert rows[1] == ["1", "-5"] and rows[2] == ["", "'=1+1"] and rows[3] == ["'+x", "'-5"]
    assert rows[4] == ["'@a", "'\tt"] and rows[5] == ["'\nn", 'x,"y"\nz'] and rows[6] == ["1.5", "ok"]


def test_app_error_and_download():
    e = kit.AppError("沒有這筆")
    assert (e.message, e.code, e.status) == ("沒有這筆", "refused", 409)
    d = kit.Download("a.csv", "text/csv; charset=utf-8", b"x")
    assert d.filename == "a.csv"
