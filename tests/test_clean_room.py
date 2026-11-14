# -*- coding: utf-8 -*-
"""全新電腦能用（docs/adr/0003）：工具庫（tools/ 的 .synoxpack＋index.json）、文字版 `synox init`、
`synox tools list｜install`。全部在暫存資料夾；不連網、不開埠、不叫 AI、不真的 pip install。"""
import argparse
import hashlib
import json
import os

import pytest

from conftest import FIXTURE_PACKS, OWNER_ID

from synox import config as synox_config
from synox.packs import library as packs_library
from synox.sdk import zip_pack
from synox.wizard import init_cli
from synox.wizard import tools as library

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── 工具庫（wizard/tools.py）─────────────────────────────────────────

def make_tools(folder, names=("notes",), *, bundles=None, tamper=None):
    """測試用的 money／notes 打包成 .synoxpack＋index.json（跟 SYNOX_Libs scripts/build.py 同一個格式）。"""
    os.makedirs(folder, exist_ok=True)
    entries = []
    for name in names:
        path = zip_pack(os.path.join(FIXTURE_PACKS, name), str(folder))
        with open(path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        if tamper == name:
            digest = "0" * 64
        entries.append({"name": name, "title": name.upper(), "summary": f"{name} 的說明", "version": "9.9.9",
                        "file": os.path.basename(path), "sha256": digest, "requires": {"sdk": ">=0.2,<0.3"},
                        "bundles": [k for k, b in (bundles or {}).items() if name in b["packs"]]})
    index = {"library": "SYNOX_Libs", "library_version": "0.1.1", "packs": entries, "bundles": bundles or {}}
    with open(os.path.join(folder, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    return str(folder)


def test_read_pick_and_verify(tmp_path):
    folder = make_tools(tmp_path / "tools", ("notes", "money"),
                        bundles={"starter": {"title": "入門", "packs": ["notes", "nope"]}})
    lib = library.read(folder)
    assert [e.name for e in lib.entries] == ["notes", "money"] and lib.version == "0.1.1"
    chosen, unknown = library.pick(lib, ["starter, money", "notes", "what"])
    assert [e.name for e in chosen] == ["notes", "money"] and unknown == ["what"]
    assert library.pick(lib, ["none"]) == ([], [])
    assert library.file_of(lib, lib.by_name()["notes"]).endswith(".synoxpack")
    text = "\n".join(library.list_lines(lib, {"notes"}))
    assert "✅ 已裝 notes" in text and "starter" in text


def test_hash_mismatch_and_bad_file_names_are_refused(tmp_path):
    folder = make_tools(tmp_path / "tools", ("notes",), tamper="notes")
    lib = library.read(folder)
    with pytest.raises(library.LibraryError, match="雜湊"):
        library.file_of(lib, lib.entries[0])
    for bad in ("../x.synoxpack", "sub/x.synoxpack", "x.zip", "..\\x.synoxpack"):
        entry = library.Entry(name="x", version="1", title="", summary="", file=bad, sha256="0" * 64)
        with pytest.raises(library.LibraryError, match="檔名"):
            library.file_of(lib, entry)


def test_why_not_library_explains(tmp_path):
    assert "不存在" in library.why_not_library(str(tmp_path / "nope"))
    src = tmp_path / "SYNOX_Libs"
    (src / "packs").mkdir(parents=True)
    (src / "scripts").mkdir()
    assert "原始碼" in library.why_not_library(str(src))
    (src / "dist").mkdir()
    (src / "dist" / "index.json").write_text("{}", encoding="utf-8")
    assert "原始碼" in library.why_not_library(str(src))
    assert "下載" in library.why_not_library("https://example.invalid/tools/")
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "index.json").write_text("[1]", encoding="utf-8")
    with pytest.raises(library.LibraryError, match="不是工具庫的目錄"):
        library.read(str(tmp_path / "broken"))


def test_config_value_is_relative_inside_synox(tmp_path):
    root = tmp_path / "SYNOX"
    assert library.to_config_value(str(root / "tools"), str(root)) == "tools"
    assert library.to_config_value(str(root / "a" / "b"), str(root)) == "a/b"
    outside = str(tmp_path / "elsewhere")
    assert library.to_config_value(outside, str(root)) == os.path.abspath(outside)
    assert library.resolve("tools", str(root)) == os.path.normpath(str(root / "tools"))


def test_default_library_is_tools_next_to_synox(tmp_path):
    """config.json 沒寫 packs.library：發佈物附的 <SYNOX>/tools（有 index.json）就是工具庫——相對位置，不是絕對路徑。"""
    cfg = synox_config.SynoxConfig.from_dict({"owner_id": OWNER_ID}, require_token=False, root=str(tmp_path))
    assert packs_library.library_location(cfg) == ""
    make_tools(tmp_path / "tools")
    assert packs_library.library_location(cfg) == str(tmp_path / "tools")
    lines = packs_library.doctor_lines(cfg, [])
    assert any(str(tmp_path / "tools") in x for x in lines) and not any("⚠️" in x for x in lines)
    cfg.packs["library"] = "SYNOX_Libs_src"
    (tmp_path / "SYNOX_Libs_src" / "packs").mkdir(parents=True)
    (tmp_path / "SYNOX_Libs_src" / "scripts").mkdir()
    assert any("⚠️" in x and "原始碼" in x for x in packs_library.doctor_lines(cfg, []))


# ── synox init（文字版）─────────────────────────────────────────────

def init_args(**kw):
    base = dict(non_interactive=True, dry_run=False, mode=None, telegram_token=None, owner_id=None, llm=None,
                model=None, base_url=None, api_key_env=None, library=None, tools=None)
    base.update(kw)
    return argparse.Namespace(**base)


TOKEN = "123456789:" + "A" * 35          # 格式對的假 token（不連 Telegram）


def run_init(tmp_path, args, *, answers=None, secrets=None):
    out = []
    q = list(answers or [])
    s = list(secrets or [])
    rc = init_cli.run(args, config_path=str(tmp_path / "config.json"), out=out.append,
                      ask=lambda prompt: q.pop(0), secret=lambda prompt: s.pop(0),
                      packs_dir=str(tmp_path / "packs"))
    return rc, "\n".join(out)


def read_cfg(tmp_path):
    with open(tmp_path / "config.json", encoding="utf-8") as f:
        return json.load(f)


def test_init_non_interactive_web_only(tmp_path):
    rc, text = run_init(tmp_path, init_args(llm="none"))
    assert rc == 0, text
    cfg = read_cfg(tmp_path)
    assert cfg["mode"] == "personal" and cfg["bot_token"] == "" and cfg["owner_id"] == 10 ** 15
    assert cfg["llm"]["kind"] == "none" and "library" not in cfg["packs"]
    assert "還沒設工具庫" in text
    synox_config.SynoxConfig.load(str(tmp_path / "config.json"), require_token=False)     # 讀得回來


def test_init_dry_run_writes_nothing_and_hides_secrets(tmp_path):
    make_tools(tmp_path / "tools", ("notes",))
    rc, text = run_init(tmp_path, init_args(dry_run=True, telegram_token=TOKEN, owner_id="42", llm="openai",
                                            api_key_env="MY_KEY", tools=["notes"]))
    assert rc == 0, text
    assert not (tmp_path / "config.json").exists() and not (tmp_path / "packs").exists()
    assert not (tmp_path / "data").exists()
    assert TOKEN not in text and "（有填）" in text and '"library": "tools"' in text
    assert "notes 9.9.9：會裝" in text


def test_init_installs_only_what_was_picked(tmp_path):
    make_tools(tmp_path / "tools", ("notes", "money"))
    rc, text = run_init(tmp_path, init_args(llm="none", library="tools", tools=["notes"]))
    assert rc == 0, text
    assert "✅ notes" in text and os.path.isfile(tmp_path / "packs" / "notes" / "pack.json")
    assert not (tmp_path / "packs" / "money").exists()                   # 沒挑的不裝
    assert read_cfg(tmp_path)["packs"]["library"] == "tools"             # 相對位置
    assert os.path.isfile(tmp_path / "data" / "packs.lock")
    rc, text = run_init(tmp_path, init_args(llm="none", tools=["notes"]))   # 重跑：已經裝了就不動
    assert rc == 0 and "已經裝了" in text


def test_init_without_tools_flag_installs_nothing(tmp_path):
    make_tools(tmp_path / "tools", ("notes",))
    rc, text = run_init(tmp_path, init_args(llm="none"))
    assert rc == 0 and "notes" in text and not (tmp_path / "packs").exists()
    assert read_cfg(tmp_path)["packs"]["library"] == "tools"


def test_init_refuses_unknown_tool_and_tampered_file(tmp_path):
    make_tools(tmp_path / "tools", ("notes",), tamper="notes")
    rc, text = run_init(tmp_path, init_args(llm="none", tools=["nope"]))
    assert rc == 2 and "工具庫裡沒有：nope" in text and not (tmp_path / "config.json").exists()
    rc, text = run_init(tmp_path, init_args(llm="none", tools=["notes"]))
    assert rc == 0 and "雜湊" in text and not (tmp_path / "packs").exists()


def test_init_non_interactive_needs_key_env_not_key(tmp_path):
    rc, text = run_init(tmp_path, init_args(llm="openai"))
    assert rc == 2 and "--api-key-env" in text
    rc, text = run_init(tmp_path, init_args(llm="gemini", api_key_env="GEMINI_KEY"))
    assert rc == 0 and read_cfg(tmp_path)["llm"]["api_key"] == "env:GEMINI_KEY"


def test_init_bad_token_is_refused(tmp_path):
    rc, text = run_init(tmp_path, init_args(telegram_token="not-a-token", owner_id="1", llm="none"))
    assert rc == 2 and "格式不對" in text and not (tmp_path / "config.json").exists()


def test_init_interactive(tmp_path):
    """互動：模式選 2（伺服器版）、token 用 getpass、id、AI 選 none、工具庫 Enter（預設 tools）、挑 starter、確認裝。"""
    make_tools(tmp_path / "tools", ("notes", "money"), bundles={"starter": {"title": "入門", "packs": ["notes"]}})
    rc, text = run_init(tmp_path, init_args(non_interactive=False),
                        answers=["2", "42", "1", "", "starter", "y"], secrets=[TOKEN])
    assert rc == 0, text
    cfg = read_cfg(tmp_path)
    assert (cfg["mode"], cfg["owner_id"], cfg["bot_token"], cfg["llm"]["kind"]) == ("server", 42, TOKEN, "none")
    assert os.path.isfile(tmp_path / "packs" / "notes" / "pack.json") and not (tmp_path / "packs" / "money").exists()


def test_init_interactive_keeps_existing_and_can_cancel(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"mode": "server", "owner_id": 7, "bot_token": TOKEN,
                                                       "web": {"port": 9999}}), encoding="utf-8")

    def cancel(prompt):
        raise KeyboardInterrupt

    out = []
    rc = init_cli.run(init_args(non_interactive=False), config_path=str(tmp_path / "config.json"), out=out.append,
                      ask=cancel, secret=cancel, packs_dir=str(tmp_path / "packs"))
    assert rc == 1 and read_cfg(tmp_path)["web"]["port"] == 9999
    rc, text = run_init(tmp_path, init_args(llm="none"))
    cfg = read_cfg(tmp_path)
    assert rc == 0 and (cfg["mode"], cfg["owner_id"], cfg["bot_token"], cfg["web"]["port"]) == ("server", 7, TOKEN, 9999)


def test_init_key_goes_to_vault_not_config(tmp_path):
    saved = {}

    class FakeVault:
        def set_secret(self, name, value):
            saved[name] = value

    out = []
    q = ["1", "3", "", ""]                        # personal、（Telegram token 用 getpass 跳過）、AI 選 3＝openai、模型 Enter、工具庫 Enter
    rc = init_cli.run(init_args(non_interactive=False), config_path=str(tmp_path / "config.json"), out=out.append,
                      ask=lambda p: q.pop(0), secret=lambda p: "" if "token" in p else "sk-test-not-real",
                      packs_dir=str(tmp_path / "packs"), vault_opener=lambda cfg: FakeVault())
    assert rc == 0, "\n".join(out)
    q[:] = []
    cfg = read_cfg(tmp_path)
    assert cfg["llm"]["api_key"] == "vault:llm_api_key" and saved == {"llm_api_key": "sk-test-not-real"}
    assert "sk-test-not-real" not in (tmp_path / "config.json").read_text(encoding="utf-8")


# ── synox tools list｜install ─────────────────────────────────────────

def test_cli_tools_list_and_install(tmp_path, monkeypatch, capsys):
    from synox import __main__ as cli
    from synox.packs import loader
    tools = make_tools(tmp_path / "tools", ("notes", "money"))
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": OWNER_ID, "vault": {"mode": "file"}, "web": {"enabled": False}}),
                   encoding="utf-8")
    packs = tmp_path / "packs"
    monkeypatch.setattr(loader, "PACK_DIRS", (str(packs), str(tmp_path / "connectors")))     # 第二個資料夾不存在也沒關係
    assert cli.main(["--config", str(cfg), "tools", "list"]) == 0
    assert "notes" in capsys.readouterr().out
    assert cli.main(["--config", str(cfg), "tools", "install", "nope"]) == 2
    assert cli.main(["--config", str(cfg), "tools", "install", "money"]) == 1        # 沒有 --yes：只印報告、不裝
    assert not packs.exists()
    assert cli.main(["--config", str(cfg), "tools", "install", "money", "--yes"]) == 0
    assert (packs / "money" / "pack.json").is_file()
    assert cli.main(["--config", str(cfg), "tools", "list", "--library", str(tmp_path / "nowhere")]) == 2
    assert tools


def test_cli_init_dry_run(tmp_path, capsys):
    from synox import __main__ as cli
    cfg = tmp_path / "config.json"
    assert cli.main(["--config", str(cfg), "init", "--non-interactive", "--dry-run", "--llm", "none"]) == 0
    assert not cfg.exists() and "config.json" in capsys.readouterr().out
