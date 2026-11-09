# -*- coding: utf-8 -*-
"""SDK P7：T2 信任（二進位與外部相依）。假的執行檔一律是「用位元組造出來的檔頭」，**絕不執行**任何東西；
不連網、不開埠（npx／git 只用 shutil.which 查路徑，找不到也照樣測）。"""
import argparse
import io
import json
import os
import zipfile

import pytest

from isdtelekit.users.roles import BasicRoles

from conftest import OTHER_ID, OWNER_ID

from synox import sandbox
from synox.packs import admin, lock, tier, upgrade
from synox.packs.manifest import read
from synox.packs.scan import opaque_files, scan

from test_sandbox import _cfg, _cli_pack

PUB = "Example Tools Ltd"
# 只有檔頭的「假執行檔」：MZ＋e_lfanew＝64＋PE 簽名。內容是零，跑也跑不起來；測試只讀它的位元組
FAKE_EXE = b"MZ" + b"\x00" * 58 + (64).to_bytes(4, "little") + b"PE\x00\x00" + b"\x00" * 64
FAKE_ELF = b"\x7fELF" + b"\x02\x01\x01" + b"\x00" * 57
TOOL_PY = "import json\nprint(json.dumps({'ok': True}))\n"


@pytest.fixture(autouse=True)
def _reset_factory():
    yield
    sandbox.set_factory(None)


def _raw(version="0.1.0", caps=("subprocess",), publisher=PUB, argv=None, **over):
    raw = {"name": "bin", "title": "Bin", "summary": "s", "version": version, "kind": "cli", "skill": "SKILL.md",
           "capabilities": list(caps), "cli": {"argv": argv or ["{python}", "./tool.py"],
                                               "commands": [{"name": "run", "effect": "READ", "argv": ["run"]}]}}
    if publisher is not None:
        raw["publisher"] = publisher
    raw.update(over)
    return raw


def _write(folder, raw, files=None):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(raw, f)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(f"---\nname: {raw['name']}\ndescription: d\n---\n")
    for rel, content in {"tool.py": TOOL_PY, **(files or {})}.items():
        path = os.path.join(folder, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content if isinstance(content, bytes) else content.encode("utf-8"))
    return folder


def _zip(folder, modes=None) -> bytes:
    """modes：{相對路徑: unix 權限}（例如 0o755），寫進 zip 的 external_attr。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for base, _dirs, files in os.walk(folder):
            for name in files:
                path = os.path.join(base, name)
                rel = os.path.relpath(path, folder).replace(os.sep, "/")
                info = zipfile.ZipInfo(rel)
                info.external_attr = ((modes or {}).get(rel, 0o644) | 0o100000) << 16
                with open(path, "rb") as f:
                    z.writestr(info, f.read())
    return buf.getvalue()


def _stage(tmp_path, tag, raw, files=None, data=None, modes=None):
    data = data or str(tmp_path / "data")
    return admin.stage(_zip(_write(str(tmp_path / "src" / tag), raw, files), modes), data)


# ── 第 2 關：掃不到內容的檔要宣告 exec ─────────────────────────────────

def test_exe_without_exec_is_refused_and_listed(tmp_path):
    with pytest.raises(admin.GateRefused) as e:
        _stage(tmp_path, "a", _raw(), {"tool.exe": FAKE_EXE})
    assert "exec" in str(e.value) and "tool.exe" in str(e.value)
    opaque = e.value.summary["scan"]["opaque"]
    assert [o["path"] for o in opaque] == ["tool.exe"]
    assert opaque[0]["size"] == len(FAKE_EXE) and len(opaque[0]["sha256"]) == 64
    text = admin.format_summary(e.value.summary)
    assert "tool.exe" in text and "掃不到內容" in text


@pytest.mark.parametrize("files,expect", [
    ({"runner": FAKE_EXE}, "runner"),                           # 沒副檔名，檔頭是 MZ／PE
    ({"notes.txt": FAKE_ELF}, "notes.txt"),                     # 副檔名騙人，檔頭是 ELF
    ({"helper.bat": "@echo off\n"}, "helper.bat"),
    ({"x.ps1": "Write-Host hi\n"}, "x.ps1"),
    ({"lib/native.so": b"\x00\x01"}, "lib/native.so"),
    ({"mod.pyd": b"\x00"}, "mod.pyd"),
    ({"old.pyc": b"\x00"}, "old.pyc"),
    ({"run": "#!/bin/sh\necho hi\n"}, "run"),                  # 沒副檔名、#! 開頭
    ({"__pycache__/ghost.cpython-311.pyc": b"\x00"}, "__pycache__/ghost.cpython-311.pyc"),   # 對不到原始碼
])
def test_opaque_detection(tmp_path, files, expect):
    folder = _write(str(tmp_path / "p"), _raw(), files)
    assert [o["path"] for o in opaque_files(folder)] == [expect]


def test_plain_files_and_matching_pycache_are_not_opaque(tmp_path):
    folder = _write(str(tmp_path / "p"), _raw(), {"README.md": "MZ is a word\n", "data.json": "{}",
                                                  "__pycache__/tool.cpython-311.pyc": b"\x00"})
    assert opaque_files(folder) == []                       # 文字剛好 MZ 開頭不算；有 tool.py 的快取不算


def test_exec_bit_from_zip_marks_extensionless_file(tmp_path):
    with pytest.raises(admin.GateRefused) as e:
        _stage(tmp_path, "a", _raw(), {"launcher": "echo hi\n"}, modes={"launcher": 0o755})
    assert [o["path"] for o in e.value.summary["scan"]["opaque"]] == ["launcher"]


def test_node_modules_is_one_entry(tmp_path):
    folder = _write(str(tmp_path / "p"), _raw(), {"node_modules/a/index.js": "x", "node_modules/b/package.json": "{}"})
    opaque = opaque_files(folder)
    assert len(opaque) == 1 and opaque[0]["path"] == "node_modules/" and "2 個檔" in opaque[0]["why"]
    assert opaque[0]["size"] == 3


def test_zip_pycache_is_not_extracted(tmp_path):
    token, summary = _stage(tmp_path, "a", _raw(publisher=None), {"__pycache__/tool.cpython-311.pyc": b"\x00"})
    folder = os.path.join(str(tmp_path / "data"), "web_uploads", token, "pack")
    assert not os.path.exists(os.path.join(folder, "__pycache__")) and summary["tier"]["tier"] == "T1"


def test_sdk_zip_leaves_out_pycache_and_still_installs(tmp_path):
    from synox.sdk import zip_pack
    src = _write(str(tmp_path / "src"), _raw(publisher=None), {"__pycache__/tool.cpython-311.pyc": b"\x00"})
    target = zip_pack(src, str(tmp_path / "dist"))
    with zipfile.ZipFile(target) as z:
        names = z.namelist()
        integrity = json.loads(z.read("pack.json"))["integrity"]["sha256"]
    assert not any("__pycache__" in n for n in names) and not any("__pycache__" in k for k in integrity)
    with open(target, "rb") as f:
        token, _s = admin.stage(f.read(), str(tmp_path / "data"))
    admin.install_staged(token, str(tmp_path / "data"), str(tmp_path / "packs"))


# ── 宣告 exec 後可裝；--trust-publisher 要一字不差 ─────────────────────

def test_declared_exec_installs_only_with_matching_publisher(tmp_path):
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, summary = _stage(tmp_path, "a", _raw(caps=("subprocess", "exec")), {"tool.exe": FAKE_EXE})
    t = summary["tier"]
    assert t["tier"] == "T2" and t["needs_publisher"] and t["runs"] == ["tool.exe"]
    text = admin.format_summary(summary)
    assert "🔴" in text and "這個 pack 會執行：tool.exe（掃不到內容）" in text and "--trust-publisher" in text
    assert "T2 不是沙盒保證，只是讓你知道你在信任誰" in text
    with pytest.raises(admin.PackAdminError) as e:
        admin.install_staged(token, data, packs, approved_by=OWNER_ID, via="test")              # 沒輸入
    assert PUB in str(e.value)
    for wrong in ("yes", "example tools ltd", "Example Tools"):
        with pytest.raises(admin.PackAdminError):
            admin.install_staged(token, data, packs, approved_by=OWNER_ID, via="test", trust_publisher=wrong)
    assert not os.path.exists(os.path.join(packs, "bin"))
    admin.install_staged(token, data, packs, approved_by=OWNER_ID, via="test", trust_publisher=f"  {PUB} ")
    rec = lock.entry(data, "bin")
    assert rec["tier"] == "T2" and rec["trusted_publisher"] == PUB and rec["trusted_at"]
    assert rec["t2"]["runs"] == ["tool.exe"] and rec["t2"]["opaque"][0]["path"] == "tool.exe"
    assert rec["hash_scope"] == "all" and "tool.exe" in rec["files"]


def test_t2_without_publisher_cannot_install(tmp_path):
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, summary = _stage(tmp_path, "a", _raw(caps=("subprocess", "exec"), publisher=None), {"tool.exe": FAKE_EXE})
    assert "沒寫 publisher" in admin.format_summary(summary)
    with pytest.raises(admin.PackAdminError) as e:
        admin.install_staged(token, data, packs, trust_publisher="anything")
    assert "publisher" in str(e.value)


def test_t1_needs_no_publisher(tmp_path):
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, summary = _stage(tmp_path, "a", _raw(publisher=None))
    assert summary["tier"]["tier"] == "T1" and not summary["tier"]["needs_publisher"]
    admin.install_staged(token, data, packs)
    assert lock.entry(data, "bin")["tier"] == "T1" and "trusted_publisher" not in lock.entry(data, "bin")


def test_cli_install_requires_trust_publisher(tmp_path, capsys):
    from synox import __main__ as cli
    blob = tmp_path / "bin.synoxpack"
    blob.write_bytes(_zip(_write(str(tmp_path / "src"), _raw(caps=("subprocess", "exec")), {"tool.exe": FAKE_EXE})))
    packs = tmp_path / "packs"
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": OWNER_ID, "data_dir": str(tmp_path / "data")}), encoding="utf-8")
    args = argparse.Namespace(config=str(cfg), file=str(blob), yes=True, packs_dir=str(packs), trust_publisher=None)
    assert cli.cmd_install(args) == 2
    out = capsys.readouterr().out
    assert "會執行：tool.exe" in out and "--trust-publisher" in out and not (packs / "bin").exists()
    args.trust_publisher = "nope"
    assert cli.cmd_install(args) == 2 and "不一樣" in capsys.readouterr().out
    args.trust_publisher = PUB
    assert cli.cmd_install(args) == 0 and (packs / "bin" / "tool.exe").is_file()
    assert lock.entry(str(tmp_path / "data"), "bin")["trusted_publisher"] == PUB


def test_parser_has_trust_publisher():
    from synox import __main__ as cli
    with pytest.raises(SystemExit):
        cli.main(["install", "x.synoxpack", "--trust-publisher"])   # 要給值


# ── 外部程式、runtime auto 的套件 ──────────────────────────────────────

def test_external_program_is_t2_and_not_hashed(tmp_path):
    folder = _write(str(tmp_path / "p"), _raw(argv=["npx", "-y", "some-mcp-tool"]))
    m = read(folder, strict=True)
    report = scan(m)
    assert [e["program"] for e in report.external] == ["npx"] and report.external[0]["note"] == "未鎖定執行環境"
    assert report.external[0]["resolved"]                       # 這台找不到也有一句話
    assert any(f.kind == "external" for f in report.findings) and not report.problems(m)
    info = tier.assess(m, report)
    assert info["tier"] == "T2" and info["runs"] == ["npx"]
    assert "npx" not in "".join(lock.hash_files(folder))
    assert any("未鎖定執行環境" in line for line in tier.warning_lines(info))


def test_python_dash_m_external_module(tmp_path):
    inside = read(_write(str(tmp_path / "a"), _raw(argv=["{python}", "-m", "tool"])), strict=True)
    assert scan(inside).external == []                          # tool.py 就在 pack 裡
    outside = read(_write(str(tmp_path / "b"), _raw(argv=["{python}", "-m", "json.tool"])), strict=True)
    ext = scan(outside).external
    assert [e["program"] for e in ext] == ["-m json.tool"] and "json" in ext[0]["resolved"]


def test_runtime_auto_packages_listed(tmp_path):
    raw = _raw(runtime={"python": "auto", "python_posix": "auto"},
               requires={"pip": ["requests==2.32.3", "idna==3.7"]})
    m = read(_write(str(tmp_path / "p"), raw), strict=True)
    info = tier.assess(m)
    assert info["tier"] == "T2" and [p["name"] for p in info["packages"]] == ["requests", "idna"]
    assert any(line.startswith("會安裝 2 個套件（來自 runtime auto）：requests 2.32.3、idna 3.7")
               for line in tier.warning_lines(info))
    node = _raw(runtime={"node": "auto"}, argv=["{node}", "./x.js"])
    lock_json = json.dumps({"lockfileVersion": 3, "packages": {"": {}, "node_modules/left-pad": {"version": "1.3.0"}}})
    m2 = read(_write(str(tmp_path / "n"), node, {"x.js": "1", "package.json": "{}", "package-lock.json": lock_json}),
              strict=True)
    assert tier.assess(m2)["packages"] == [{"name": "left-pad", "version": "1.3.0", "source": "npm"}]


# ── packs.lock：涵蓋每一個檔；竄改不載入 ───────────────────────────────

def test_lock_covers_every_file_and_tamper_detected(tmp_path):
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _s = _stage(tmp_path, "a", _raw(caps=("subprocess", "exec")),
                       {"tool.exe": FAKE_EXE, "node_modules/x/i.js": "1", "lib/a.dll": b"\x00"})
    admin.install_staged(token, data, packs, trust_publisher=PUB)
    folder = os.path.join(packs, "bin")
    rec = lock.entry(data, "bin")
    from synox.packs.scan import pack_files
    assert sorted(rec["files"]) == pack_files(folder, include_cache=True)
    assert {"tool.exe", "node_modules/x/i.js", "lib/a.dll", "pack.json", "SKILL.md", "tool.py"} <= set(rec["files"])
    assert lock.verify(data, "bin", folder)[0] == lock.LOCKED
    with open(os.path.join(folder, "tool.exe"), "ab") as f:
        f.write(b"\x90")
    state, changes = lock.verify(data, "bin", folder)
    assert state == lock.TAMPERED and changes == ["改了 tool.exe"]


def test_planted_pycache_is_tamper_but_legacy_lock_ignores_it(tmp_path):
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _s = _stage(tmp_path, "a", _raw(publisher=None))
    admin.install_staged(token, data, packs)
    folder = os.path.join(packs, "bin")
    os.makedirs(os.path.join(folder, "__pycache__"))
    with open(os.path.join(folder, "__pycache__", "tool.cpython-311.pyc"), "wb") as f:
        f.write(b"\x00")
    state, changes = lock.verify(data, "bin", folder)
    assert state == lock.TAMPERED and "多了 __pycache__/tool.cpython-311.pyc" in changes
    stored = lock.load(data)                                         # P7 以前的鎖（沒有 hash_scope）：照舊不看快取
    stored["packs"]["bin"].pop("hash_scope")
    with open(lock.lock_path(data), "w", encoding="utf-8") as f:
        json.dump(stored, f)
    assert lock.verify(data, "bin", folder)[0] == lock.LOCKED


def test_tampered_t2_pack_not_loaded(make_bot, tmp_path):
    base = str(tmp_path / "packs")
    folder = _write(os.path.join(base, "bin"), _raw(caps=("subprocess", "exec")), {"tool.exe": FAKE_EXE})
    data = str(tmp_path / "data")
    m, _report, problems = admin.approve_installed(folder, data, approved_by=OWNER_ID, trust_publisher=PUB)
    assert problems == []
    with open(os.path.join(folder, "tool.exe"), "wb") as f:
        f.write(FAKE_EXE + b"\x01")
    bot = make_bot(pack_dirs=(base,))
    item = next(i for i in bot.app.extras["synox_pack_report"].items if i.name == "bin")
    assert item.status == "tampered" and "tool.exe" in item.detail


def test_approve_installed_t2_needs_publisher_then_carries_it(tmp_path):
    folder = _write(str(tmp_path / "packs" / "bin"), _raw(caps=("subprocess", "exec")), {"tool.exe": FAKE_EXE})
    data = str(tmp_path / "data")
    _m, _r, problems = admin.approve_installed(folder, data)
    assert problems and "--trust-publisher" in problems[0] and lock.entry(data, "bin") is None
    assert admin.approve_installed(folder, data, trust_publisher="wrong")[2]
    assert admin.approve_installed(folder, data, trust_publisher=PUB)[2] == []
    assert admin.approve_installed(folder, data)[2] == []                 # 同一個 publisher、沒變多：沿用
    assert lock.entry(data, "bin")["trusted_publisher"] == PUB
    with open(os.path.join(folder, "more.dll"), "wb") as f:
        f.write(b"\x00")
    problems = admin.approve_installed(folder, data)[2]
    assert problems and "more.dll" in problems[0]                        # 可執行的東西變多：要重新輸入


# ── 升級 ───────────────────────────────────────────────────────────────

def _installed_t2(tmp_path):
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _s = _stage(tmp_path, "v1", _raw(caps=("subprocess", "exec")), {"tool.exe": FAKE_EXE}, data=data)
    admin.install_staged(token, data, packs, trust_publisher=PUB)
    return data, packs


def test_upgrade_same_publisher_carries_confirmation(tmp_path):
    data, packs = _installed_t2(tmp_path)
    token, _s = _stage(tmp_path, "v2", _raw("0.2.0", caps=("subprocess", "exec")), {"tool.exe": FAKE_EXE + b"\x01"},
                       data=data)
    upg = upgrade.staged_upgrade(token, data, packs)
    assert not upg["tier"]["needs_publisher"] and "沿用之前確認過的發行者" in upgrade.format_upgrade(upg)
    upgrade.upgrade_staged(token, data, packs)
    assert lock.entry(data, "bin")["trusted_publisher"] == PUB and lock.entry(data, "bin")["version"] == "0.2.0"


@pytest.mark.parametrize("raw,files,needle,typed", [
    (_raw("0.2.0", caps=("subprocess", "exec"), publisher="Someone Else"), {"tool.exe": FAKE_EXE},
     "發行者 publisher Example Tools Ltd → Someone Else", "Someone Else"),
    (_raw("0.2.0", caps=("subprocess", "exec")), {"tool.exe": FAKE_EXE, "extra.dll": b"\x00"},
     "可執行的東西變多了：extra.dll", PUB),
])
def test_upgrade_changes_need_reconfirm(tmp_path, raw, files, needle, typed):
    data, packs = _installed_t2(tmp_path)
    token, _s = _stage(tmp_path, "v2", raw, files, data=data)
    upg = upgrade.staged_upgrade(token, data, packs)
    assert upg["tier"]["needs_publisher"]
    assert any(needle in c["text"] and c["alert"] for c in upg["changes"]), upg["changes"]
    assert "🔴 T2：要重新確認發行者" in upgrade.format_upgrade(upg)
    with pytest.raises(admin.PackAdminError):
        upgrade.upgrade_staged(token, data, packs)
    with pytest.raises(admin.PackAdminError):
        upgrade.upgrade_staged(token, data, packs, trust_publisher=PUB if typed != PUB else "x")
    upgrade.upgrade_staged(token, data, packs, trust_publisher=typed)
    assert lock.entry(data, "bin")["trusted_publisher"] == typed


def test_upgrade_t1_to_t2_with_new_exec_is_red(tmp_path):
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _s = _stage(tmp_path, "v1", _raw(), data=data)
    admin.install_staged(token, data, packs)
    token, _s = _stage(tmp_path, "v2", _raw("0.2.0", caps=("subprocess", "exec")), {"tool.exe": FAKE_EXE}, data=data)
    upg = upgrade.staged_upgrade(token, data, packs)
    texts = [c["text"] for c in upg["changes"] if c["alert"]]
    assert "新增能力 exec" in texts and any("T1 → T2" in t for t in texts) and upg["tier"]["needs_publisher"]
    with pytest.raises(admin.PackAdminError):
        upgrade.upgrade_staged(token, data, packs)
    upgrade.upgrade_staged(token, data, packs, trust_publisher=PUB)


# ── 執行期：伺服器版沒有真隔離＝成員看不到（不管 trust）；個人版 doctor 提醒 ─────

def _t2_cli(base, name="ext"):
    folder = _cli_pack(base, name, access="member")
    with open(os.path.join(folder, "pack.json"), encoding="utf-8") as f:
        raw = json.load(f)
    raw.update(capabilities=["exec"], publisher=PUB)
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(raw, f)
    with open(os.path.join(folder, "helper.exe"), "wb") as f:
        f.write(FAKE_EXE)
    return folder


def _sees(bot, tg_id):
    reg = bot.app.registry
    return reg.visible(bot.app.users.get_or_create(tg_id), reg.node("ext"))


@pytest.mark.parametrize("required_for", ["third-party", "none"])
def test_server_t2_core_still_owner_only_without_isolation(make_bot, tmp_path, required_for):
    base = str(tmp_path / "packs")
    folder = _t2_cli(base)
    assert admin.approve_installed(folder, str(tmp_path / "data"), approved_by=OWNER_ID, trust="core",
                                   trust_publisher=PUB)[2] == []
    sandbox.set_factory(lambda config: sandbox.NoneSandbox())
    bot = make_bot(raw={"mode": "server", "policy": {"sandbox": {"required_for": required_for}}}, pack_dirs=(base,))
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    item = next(i for i in bot.app.extras["synox_pack_report"].items if i.name == "ext")
    assert item.status == "loaded" and "T2" in item.detail and "只對擁有者開放" in item.detail
    assert _sees(bot, OWNER_ID) and not _sees(bot, OTHER_ID)


def test_server_t2_visible_with_real_isolation_and_t1_core_unaffected(tmp_path):
    from test_sandbox import Recording
    cfg = _cfg(tmp_path, mode="server", policy={"sandbox": {"required_for": "none"}})
    t2 = read(_t2_cli(str(tmp_path / "a")))
    assert sandbox.restricted_reason(cfg, t2, Recording(isolates=True, name="bwrap")) == ""
    t1 = read(_cli_pack(str(tmp_path / "b"), "plain"))
    assert sandbox.restricted_reason(cfg, t1, sandbox.NoneSandbox()) == ""
    assert sandbox.restricted_reason(cfg, t2, sandbox.NoneSandbox())


def test_server_t2_python_pack_owner_only_even_with_isolation(tmp_path):
    from test_sandbox import Recording
    folder = _write(str(tmp_path / "py"), {"name": "pyb", "title": "P", "summary": "s", "version": "0.1.0",
                                            "kind": "python", "skill": "SKILL.md", "capabilities": ["exec"],
                                            "publisher": PUB},
                    {"pack.py": "def install(app, pack):\n    pass\n", "fast.pyd": b"\x00"})
    m = read(folder)
    cfg = _cfg(tmp_path, mode="server")
    assert "沙盒包不到" in sandbox.restricted_reason(cfg, m, Recording(isolates=True, name="bwrap"))


def test_personal_t2_available_but_doctor_warns(tmp_path):
    packs = tmp_path / "packs"
    _t2_cli(str(packs))
    cfg = _cfg(tmp_path)
    m = read(str(packs / "ext"))
    assert sandbox.restricted_reason(cfg, m, sandbox.NoneSandbox()) == ""
    assert "helper.exe" in sandbox.t2_personal_note(cfg, m)
    from synox import doctor
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"owner_id": OWNER_ID, "data_dir": str(tmp_path / "data"), "llm": {"kind": "none"},
                                "packs": {"dirs": [str(packs)]}}), encoding="utf-8")
    lines = []
    doctor.run(offline=True, config_path=str(path), out=lines.append)
    assert any("T2" in x and "helper.exe" in x and "沒有沙盒" in x for x in lines)


# ── 網頁：報告有 T2 那一段，確認要帶 trust_publisher ─────────────────────

def test_web_install_t2_requires_publisher(make_bot, owner, tmp_path):
    from test_web import Client, ui_of
    user_packs = tmp_path / "userpacks"
    user_packs.mkdir()
    bot = make_bot(pack_dirs=(str(user_packs),))
    c = Client(ui_of(bot))
    c.login(owner)
    blob = _zip(_write(str(tmp_path / "src"), _raw(caps=("subprocess", "exec")), {"tool.exe": FAKE_EXE}))
    status, _h, body = c.raw("POST", "/api/packs/upload", blob)
    summary = json.loads(body)
    assert status == 200 and summary["tier"]["tier"] == "T2" and summary["tier"]["warning_lines"]
    status, data = c.post("/api/packs/install", {"token": summary["token"]})
    assert status == 400 and PUB in data["error"]
    status, data = c.post("/api/packs/install", {"token": summary["token"], "trust_publisher": "nope"})
    assert status == 400
    status, data = c.post("/api/packs/install", {"token": summary["token"], "trust_publisher": PUB})
    assert status == 200 and data["name"] == "bin", data
