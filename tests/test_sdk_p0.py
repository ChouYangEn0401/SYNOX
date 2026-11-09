# -*- coding: utf-8 -*-
"""SDK P0 小修：
(a) G3 經 AI 呼叫 cli pack 指令 → 同步跑、結果（包 nonce 分隔符）交回 AI；人打字照舊。
(b) G1 requires.env（＋auth.fields[].env）的名字傳給 JsonCli 當 keep_env，只放行這些。
(c) requires.synox 最低版本：寫錯＝pack.json 不合；不合＝不載入（incompatible）、doctor／安裝說人話。
(d) fields[].kind = text|int|number|bool|path|choice：loader 交給程式前照 kind 檢查與整理。
後端是一支本機的假命令列程式（真的經 JobRunner 跑），不連網、不開埠。"""
import json
import os
import sys

import pytest

from conftest import OWNER_ID

from synox.agent import delimit
from synox.agent import validate as gate4
from synox.llm.base import TOOL
from synox.packs import admin
from synox.packs.manifest import ManifestError, parse_spec, secret_env_names, synox_problem, validate

ECHO = r'''
import json, os, sys
print(json.dumps({"ok": True, "argv_text": " ".join(sys.argv[1:]),
                  "kept": os.environ.get("ECHO_API_TOKEN", "(none)"),
                  "other": os.environ.get("OTHER_SERVICE_TOKEN", "(none)")}, ensure_ascii=False))
'''


def _manifest(**over):
    m = {
        "name": "echo", "title": "回音", "summary": "測試用", "version": "0.1.0", "kind": "cli",
        "access": "owner", "capabilities": ["subprocess"], "skill": "SKILL.md",
        "cli": {"python": sys.executable, "argv": ["{python}", "{pack_dir}/echo_cli.py"], "json_flag": "--json",
                "timeout": 30,
                "commands": [
                    {"name": "add", "default": True, "positional": 1, "effect": "read", "summary": "回音",
                     "argv": ["add", "--amount={amount}"],
                     "fields": [{"name": "amount", "ask": "多少", "required": True}]},
                    {"name": "typed", "effect": "read", "summary": "有型別的欄位", "positional": 0,
                     "argv": ["typed", "--n={n}", "--x={x}", "--flag={flag}", "--color={color}"],
                     "fields": [{"name": "n", "ask": "次數", "kind": "int"},
                                {"name": "x", "ask": "比例", "kind": "number"},
                                {"name": "flag", "ask": "要不要", "kind": "bool"},
                                {"name": "color", "ask": "顏色", "kind": "choice", "choices": ["Red", "Blue"]}]},
                ]},
    }
    m.update(over)
    return m


def _pack(folder, **over) -> None:
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "echo_cli.py"), "w", encoding="utf-8") as f:
        f.write(ECHO)
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(_manifest(**over), f, ensure_ascii=False)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: echo\ndescription: 測試\n---\n")


def _tool_results(bot):
    adapter = bot.app.extras["synox_agent"].adapter
    messages, _tools = adapter.calls[-1]
    return [m.content for m in messages if m.role == TOOL]


# ── (a) G3 ────────────────────────────────────────────────────────────

def test_ai_call_to_cli_pack_returns_result_to_ai(make_bot, owner, tmp_path):
    _pack(str(tmp_path / "packs" / "echo"))
    bot = make_bot([{"tool": "echo__add", "args": {"amount": "120"}}, "好了"], pack_dirs=(str(tmp_path / "packs"),))
    bot.talk(owner, "回音 120")
    results = _tool_results(bot)
    assert len(results) == 1
    nonce, body = delimit.unwrap(results[0])
    assert nonce, results[0]                                   # 有包每輪的分隔符
    assert "--amount=120" in body                              # 結果交給 AI 了
    texts = bot.texts(owner)
    assert texts[-1] == "好了"
    assert not any("--amount=120" in t for t in texts)          # 沒有直接送給使用者
    bot.app.tasks.wait(5)
    assert not any("--amount=120" in t for t in bot.texts(owner))


def test_human_typed_cli_command_still_runs_in_background(make_bot, owner, tmp_path):
    _pack(str(tmp_path / "packs" / "echo"))
    bot = make_bot(pack_dirs=(str(tmp_path / "packs"),))
    bot.say(owner, "/echo 7")
    assert bot.app.tasks.wait(20)
    assert any("--amount=7" in t for t in bot.texts(owner))


# ── (b) G1 ────────────────────────────────────────────────────────────

def test_requires_env_is_passed_to_cli_but_other_secrets_are_not(make_bot, owner, tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_API_TOKEN", "tok-123")
    monkeypatch.setenv("OTHER_SERVICE_TOKEN", "should-not-leak")
    _pack(str(tmp_path / "packs" / "echo"), requires={"env": {"ECHO_API_TOKEN": "Echo 服務的 token"}})
    bot = make_bot(pack_dirs=(str(tmp_path / "packs"),))
    assert bot.app.extras["synox_pack_report"].items[0].status == "loaded"
    bot.say(owner, "/echo 1")
    assert bot.app.tasks.wait(20)
    joined = "\n".join(bot.texts(owner))
    assert "tok-123" in joined
    assert "should-not-leak" not in joined


def test_without_requires_env_secrets_stay_hidden(make_bot, owner, tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_API_TOKEN", "tok-123")
    _pack(str(tmp_path / "packs" / "echo"))
    bot = make_bot(pack_dirs=(str(tmp_path / "packs"),))
    bot.say(owner, "/echo 1")
    assert bot.app.tasks.wait(20)
    assert "tok-123" not in "\n".join(bot.texts(owner))


def test_secret_env_names_from_requires_and_auth_fields(tmp_path):
    folder = str(tmp_path / "p")
    _pack(folder, requires={"env": ["A_TOKEN"]},
          auth={"type": "token", "fields": [{"name": "key", "env": "B_API_KEY"}, {"name": "x"}]})
    m = validate(json.load(open(os.path.join(folder, "pack.json"), encoding="utf-8")), folder)
    assert secret_env_names(m) == ["A_TOKEN", "B_API_KEY"]


def test_requires_env_bad_names_are_rejected(tmp_path):
    folder = str(tmp_path / "p")
    _pack(folder)
    raw = _manifest(requires={"env": ["BAD NAME"]})
    with pytest.raises(ManifestError, match="requires.env"):
        validate(raw, folder)


# ── (c) requires.synox ─────────────────────────────────────────────────

def test_parse_spec():
    assert parse_spec(">=0.3") == [(">=", (0, 3, 0))]
    assert parse_spec("0.2.1") == [(">=", (0, 2, 1))]
    assert parse_spec(">=0.1, <1") == [(">=", (0, 1, 0)), ("<", (1, 0, 0))]
    for bad in ("", "abc", ">=x", "=>0.1", 3):
        with pytest.raises(ValueError):
            parse_spec(bad)


def test_requires_synox_bad_spec_is_invalid_manifest(tmp_path):
    folder = str(tmp_path / "p")
    _pack(folder)
    with pytest.raises(ManifestError, match="requires.synox"):
        validate(_manifest(requires={"synox": "latest"}), folder)


def test_synox_problem_human_message(tmp_path):
    folder = str(tmp_path / "p")
    _pack(folder)
    m = validate(_manifest(requires={"synox": ">=0.3"}), folder)
    assert synox_problem(m, "0.3.0") is None
    msg = synox_problem(m, "0.1.0")
    assert ">=0.3" in msg and "0.1.0" in msg and "更新 SYNOX" in msg
    m2 = validate(_manifest(requires={"synox": "<0.1"}), folder)
    assert "作者" in synox_problem(m2, "0.2.0")
    assert synox_problem(validate(_manifest(), folder), "0.0.1") is None       # 沒寫＝不限


def test_incompatible_pack_is_not_loaded(make_bot, owner, tmp_path):
    _pack(str(tmp_path / "packs" / "echo"), requires={"synox": ">=99.0"})
    bot = make_bot(pack_dirs=(str(tmp_path / "packs"),))
    item = bot.app.extras["synox_pack_report"].items[0]
    assert item.status == "incompatible"
    assert "SYNOX >=99.0" in item.detail and "更新 SYNOX" in item.detail
    assert bot.app.registry.node("echo") is None
    assert bot.app.extras["synox_pack_report"].ok          # 不算壞掉，只是這台太舊


def test_compatible_pack_loads(make_bot, owner, tmp_path):
    _pack(str(tmp_path / "packs" / "echo"), requires={"synox": ">=0.1"})
    bot = make_bot(pack_dirs=(str(tmp_path / "packs"),))
    assert bot.app.extras["synox_pack_report"].items[0].status == "loaded"


def test_install_gate_refuses_incompatible(tmp_path):
    folder = str(tmp_path / "p")
    _pack(folder, requires={"synox": ">=99.0"})
    _m, _report, _hashes, problems = admin.run_gates(folder)
    assert any("SYNOX >=99.0" in p for p in problems)


def test_doctor_explains_incompatible(tmp_path, monkeypatch):
    from synox import doctor
    packs = tmp_path / "packs"
    _pack(str(packs / "echo"), requires={"synox": ">=99.0"})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": OWNER_ID, "data_dir": str(tmp_path / "data"), "vault": {"mode": "file"},
                               "llm": {"kind": "none"}, "packs": {"dirs": [str(packs)]}}), encoding="utf-8")
    lines = []
    doctor.run(offline=True, config_path=str(cfg), out=lines.append)
    hit = [ln for ln in lines if "echo" in ln and "不會載入" in ln]
    assert hit and "SYNOX >=99.0" in hit[0], lines


# ── (d) fields[].kind ──────────────────────────────────────────────────

@pytest.mark.parametrize("kind,value,ok", [
    ("int", "3", True), ("int", "1,000", True), ("int", "3.5", False), ("int", "三", False),
    ("number", "12.5", True), ("number", "nan", False), ("number", "abc", False),
    ("bool", "yes", True), ("bool", "是", True), ("bool", "False", True), ("bool", "maybe", False),
    ("choice", "red", True), ("choice", "Green", False),
    ("text", "anything", True),
])
def test_kind_problem(kind, value, ok):
    assert (gate4.kind_problem(kind, value, ("Red", "Blue")) is None) == ok


def test_normalize():
    assert gate4.normalize("bool", "是") == "true" and gate4.normalize("bool", "NO") == "false"
    assert gate4.normalize("int", "1,000") == "1000"
    assert gate4.normalize("choice", "blue", ("Red", "Blue")) == "Blue"
    assert gate4.normalize("text", " x ") == " x "


def test_manifest_field_kinds(tmp_path):
    folder = str(tmp_path / "p")
    _pack(folder)
    validate(_manifest(), folder)                                          # int|number|bool|choice 都收
    bad_kind = _manifest()
    bad_kind["cli"]["commands"][1]["fields"][0]["kind"] = "date"
    with pytest.raises(ManifestError, match="kind 只能是"):
        validate(bad_kind, folder)
    no_choices = _manifest()
    del no_choices["cli"]["commands"][1]["fields"][3]["choices"]
    with pytest.raises(ManifestError, match="choices"):
        validate(no_choices, folder)


def test_typed_fields_checked_and_normalized_when_typed(make_bot, owner, tmp_path):
    _pack(str(tmp_path / "packs" / "echo"))
    bot = make_bot(pack_dirs=(str(tmp_path / "packs"),))
    bot.say(owner, "/echo_typed n=三")
    bot.app.tasks.wait(5)
    assert any("次數要是整數" in t for t in bot.texts(owner)), bot.texts(owner)
    bot.say(owner, "/echo_typed color=green")
    bot.app.tasks.wait(5)
    assert any("Red" in t and "Blue" in t for t in bot.texts(owner)), bot.texts(owner)
    bot.say(owner, "/echo_typed n=1,000 x=2.5 flag=是 color=blue")
    assert bot.app.tasks.wait(20)
    joined = "\n".join(bot.texts(owner))
    assert "--n=1000 --x=2.5 --flag=true --color=Blue" in joined, joined


def test_typed_fields_checked_on_ai_path(make_bot, owner, tmp_path):
    _pack(str(tmp_path / "packs" / "echo"))
    bot = make_bot([{"tool": "echo__typed", "args": {"n": "很多"}},
                    {"tool": "echo__typed", "args": {"n": "2", "flag": "no"}}, "好"],
                   pack_dirs=(str(tmp_path / "packs"),))
    bot.talk(owner, "跑一下")
    results = [delimit.unwrap(r)[1] for r in _tool_results(bot)]
    assert "次數要是整數" in results[0] and "typed" not in results[0]       # 沒執行
    assert "--n=2" in results[1] and "--flag=false" in results[1]
    adapter = bot.app.extras["synox_agent"].adapter
    _messages, tools = adapter.calls[0]
    spec = next(t for t in tools if t.name == "echo__typed")
    params = getattr(spec, "parameters", None) or getattr(spec, "schema", None) or {}
    assert all(p.get("type") == "string" for p in params.get("properties", {}).values())   # schema 仍是字串
