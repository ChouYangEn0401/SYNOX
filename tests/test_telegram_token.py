"""Telegram bot token 放保管箱（synox/telegram_token.py）：存的地方寫參照、讀的地方解參照、舊的明文自動搬、哪裡都不露出來。
全部用假 token，不連網。"""

import json
import logging
import os

import pytest
from isdtelekit.host.config import ConfigError

from synox import telegram_token as tt
from synox.config import SynoxConfig, redacted
from synox.vault import Vault
from synox.wizard import logic

TOKEN = "123456:TEST" + "x" * 30          # 假的，但格式對（has_token 要 True）
OTHER = "654321:TEST" + "y" * 30


class FakeVault:
    def __init__(self, secrets=None, fail=False):
        self.secrets = dict(secrets or {})
        self.fail = fail

    def secret(self, name):
        if self.fail:
            raise OSError("vault is locked")
        return self.secrets.get(name)

    def set_secret(self, name, value):
        if self.fail:
            raise OSError("vault is locked")
        self.secrets[name] = value


def _vault(tmp_path):
    return Vault(b"k" * 32, str(tmp_path / "data"))


def _write(path, cfg):
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _everything_under(folder) -> str:
    """資料夾底下所有檔案的內容接起來（找有沒有明文 token 留在哪裡）。"""
    out = []
    for root, _dirs, files in os.walk(folder):
        for name in files:
            with open(os.path.join(root, name), "rb") as f:
                out.append(f.read().decode("utf-8", "replace"))
    return "\n".join(out)


# ── resolve／mask ─────────────────────────────────────────────────────────

def test_resolve_plain_env_and_vault(monkeypatch):
    assert tt.resolve(TOKEN) == TOKEN and tt.resolve("") == ""
    monkeypatch.setenv("SYNOX_TEST_TG", TOKEN)
    assert tt.resolve("env:SYNOX_TEST_TG") == TOKEN
    assert tt.resolve(tt.REF, FakeVault({tt.VAULT_NAME: TOKEN})) == TOKEN
    opened = []
    assert tt.resolve(tt.REF, opener=lambda: opened.append(1) or FakeVault({tt.VAULT_NAME: TOKEN})) == TOKEN
    assert opened == [1]
    assert tt.resolve(TOKEN, opener=lambda: opened.append(2)) == TOKEN and opened == [1]   # 明文不開保管箱


def test_resolve_failures_never_mention_the_token(monkeypatch):
    monkeypatch.delenv("SYNOX_TEST_TG_MISSING", raising=False)
    for value, vault in (("env:SYNOX_TEST_TG_MISSING", None), (tt.REF, None), (tt.REF, FakeVault()),
                         (tt.REF, FakeVault({tt.VAULT_NAME: TOKEN}, fail=True))):
        with pytest.raises(tt.TokenUnavailable) as e:
            tt.resolve(value, vault)
        assert TOKEN not in str(e.value)


def test_mask_keeps_only_the_tail():
    assert tt.mask(TOKEN) == "…" + TOKEN[-4:] and TOKEN[:-4] not in tt.mask(TOKEN)
    assert tt.mask("") == "" and tt.mask("short") == "…"


# ── 存的地方寫參照 ─────────────────────────────────────────────────────────

def test_wizard_save_puts_token_in_vault(tmp_path):
    vault = FakeVault()
    cfg = logic.build_config(TOKEN, 4242, {"kind": "none"})
    assert cfg["bot_token"] == TOKEN                       # 還在記憶體裡：save 才搬
    path = tmp_path / "config.json"
    saved = logic.save(str(path), cfg, vault_opener=lambda c: vault)
    assert saved["bot_token"] == tt.REF and vault.secrets == {tt.VAULT_NAME: TOKEN}
    assert TOKEN not in path.read_text(encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8"))["bot_token"] == tt.REF


def test_wizard_save_with_real_vault_then_load_resolves(tmp_path):
    cfg = logic.build_config(TOKEN, 4242, {"kind": "none"})
    cfg["vault"] = {"mode": "file"}
    path = tmp_path / "config.json"
    logic.save(str(path), cfg)
    assert TOKEN not in path.read_text(encoding="utf-8")
    config = SynoxConfig.load(str(path))                   # require_token=True：參照解得開就過
    assert config.bot_token == TOKEN and config.has_token
    assert config.raw["bot_token"] == tt.REF               # raw 留參照（doctor、回報都看 raw）
    assert TOKEN not in repr(config)


def test_wizard_save_keeps_env_reference_and_skip(tmp_path):
    vault = FakeVault()
    path = tmp_path / "config.json"
    cfg = logic.build_config("env:SYNOX_TG", 1, {"kind": "none"})
    assert logic.save(str(path), cfg, vault_opener=lambda c: vault)["bot_token"] == "env:SYNOX_TG"
    cfg = logic.build_config("", 1, {"kind": "none"})
    assert logic.save(str(path), cfg, vault_opener=lambda c: vault)["bot_token"] == ""
    assert vault.secrets == {}


def test_wizard_reuses_vaulted_token(tmp_path):
    """重跑精靈：existing 裡是參照 → 畫面拿到真的 token 可以沿用，存回去還是參照。"""
    vault = FakeVault({tt.VAULT_NAME: TOKEN})
    existing = {"bot_token": tt.REF, "owner_id": 4242}
    assert logic.existing_telegram_token(existing, vault_opener=lambda c: vault) == TOKEN
    assert logic.existing_telegram_token({"bot_token": tt.REF}, vault_opener=lambda c: FakeVault(fail=True)) == ""
    assert logic.existing_telegram_token({"bot_token": TOKEN}) == TOKEN


def test_init_cli_writes_reference(tmp_path):
    import argparse
    from synox.wizard import init_cli
    vault = FakeVault()
    path = tmp_path / "config.json"
    args = argparse.Namespace(non_interactive=True, dry_run=False, mode="personal", telegram_token=TOKEN,
                              owner_id="4242", llm="none", library=None, tools=None)
    lines = []
    rc = init_cli.run(args, config_path=str(path), out=lines.append, packs_dir=str(tmp_path / "packs"),
                      vault_opener=lambda c: vault)
    assert rc == 0, lines
    assert json.loads(path.read_text(encoding="utf-8"))["bot_token"] == tt.REF
    assert vault.secrets[tt.VAULT_NAME] == TOKEN and TOKEN not in "\n".join(lines)
    # 再跑一次、什麼都不給：沿用保管箱裡的
    args.telegram_token = None
    assert init_cli.run(args, config_path=str(path), out=lines.append, packs_dir=str(tmp_path / "packs"),
                        vault_opener=lambda c: vault) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["bot_token"] == tt.REF
    assert vault.secrets[tt.VAULT_NAME] == TOKEN


# ── 舊的明文自動搬 ─────────────────────────────────────────────────────────

def test_migrate_moves_plaintext_and_is_idempotent(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    path = tmp_path / "config.json"
    _write(path, {"bot_token": TOKEN, "owner_id": 4242, "vault": {"mode": "file"}, "llm": {"kind": "none"}})
    (tmp_path / "config.json.bak").write_text(json.dumps({"bot_token": TOKEN}), encoding="utf-8")
    (tmp_path / "config.json.tmp").write_text('{"bot_token": "%s"}' % TOKEN, encoding="utf-8")
    assert tt.migrate(str(path)) == tt.MIGRATED
    data = json.loads(path.read_text(encoding="utf-8"))
    # schema_version：write_config 一律蓋上目前的版本號（ADR 0044）
    assert data == {"bot_token": tt.REF, "owner_id": 4242, "vault": {"mode": "file"}, "llm": {"kind": "none"},
                    "schema_version": 1}
    assert TOKEN not in _everything_under(tmp_path)        # config.json、殘檔、log 都沒有明文（保管箱是密文）
    assert TOKEN not in caplog.text
    config = SynoxConfig.load(str(path))
    assert config.bot_token == TOKEN and config.has_token
    before = path.read_bytes()
    assert tt.migrate(str(path)) == tt.UNCHANGED and path.read_bytes() == before
    left = {n for n in os.listdir(tmp_path) if n.startswith("config.json")}
    assert left <= {"config.json", "config.json.bak", "config.json.tmp"}          # 沒有多出新的備份
    assert "config.json" in left and "config.json.bak" in left                    # （.tmp 被 write_config 自己用掉了）


def test_migrate_vault_unavailable_leaves_config_untouched(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    path = tmp_path / "config.json"
    _write(path, {"bot_token": TOKEN, "owner_id": 4242})
    before = path.read_bytes()
    assert tt.migrate(str(path), vault_opener=lambda raw: FakeVault(fail=True)) == tt.FAILED
    assert path.read_bytes() == before
    assert "保管箱" in caplog.text and TOKEN not in caplog.text

    def boom(raw):
        raise RuntimeError("cannot open " + raw["bot_token"])   # 就算例外訊息帶著 token，也不准進 log
    assert tt.migrate(str(path), vault_opener=boom) == tt.FAILED
    assert path.read_bytes() == before and TOKEN not in caplog.text


def test_migrate_ignores_references_missing_and_broken(tmp_path):
    path = tmp_path / "config.json"
    assert tt.migrate(str(path)) == tt.UNCHANGED                  # 沒有 config.json
    path.write_text("{ not json", encoding="utf-8")
    assert tt.migrate(str(path)) == tt.UNCHANGED
    for value in (tt.REF, "env:X", ""):
        _write(path, {"bot_token": value, "owner_id": 1})
        before = path.read_bytes()
        assert tt.migrate(str(path), vault_opener=lambda raw: pytest.fail("should not open")) == tt.UNCHANGED
        assert path.read_bytes() == before


def test_startup_migrates_before_loading(tmp_path, monkeypatch):
    """`python -m synox run` 一開始就搬（__main__.load_for_run）。"""
    from synox import __main__ as main
    path = tmp_path / "config.json"
    _write(path, {"bot_token": TOKEN, "owner_id": 4242, "vault": {"mode": "file"}, "llm": {"kind": "none"},
                  "web": {"enabled": False}})
    config = main.load_for_run(str(path))
    assert config.bot_token == TOKEN and main.run_channels(config) == ("telegram",)
    assert json.loads(path.read_text(encoding="utf-8"))["bot_token"] == tt.REF


# ── 讀的地方解參照 ─────────────────────────────────────────────────────────

def test_load_with_given_vault(tmp_path):
    vault = FakeVault({tt.VAULT_NAME: TOKEN})
    config = SynoxConfig.from_dict({"bot_token": tt.REF, "owner_id": 1}, root=str(tmp_path), vault=vault)
    assert config.bot_token == TOKEN and config.token_problem == ""


def test_load_vault_reference_unreadable(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    raw = {"bot_token": tt.REF, "owner_id": 1, "web": {"enabled": False}}
    config = SynoxConfig.from_dict(raw, require_token=False, root=str(tmp_path), vault=FakeVault())
    assert config.bot_token == "" and not config.has_token and "保管箱" in config.token_problem
    with pytest.raises(ConfigError) as e:
        SynoxConfig.from_dict(raw, root=str(tmp_path), vault=FakeVault())
    assert "保管箱" in str(e.value)


def test_env_reference_still_works(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNOX_TEST_TG", TOKEN)
    config = SynoxConfig.from_dict({"bot_token": "env:SYNOX_TEST_TG", "owner_id": 1}, root=str(tmp_path))
    assert config.bot_token == TOKEN and config.has_token


# ── 哪裡都不露出來 ─────────────────────────────────────────────────────────

def test_token_never_leaks(tmp_path, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    path = tmp_path / "config.json"
    _write(path, {"bot_token": TOKEN, "owner_id": 4242, "vault": {"mode": "file"}, "llm": {"kind": "none"},
                  "web": {"enabled": False}})
    assert tt.migrate(str(path)) == tt.MIGRATED
    config = SynoxConfig.load(str(path))
    assert config.bot_token == TOKEN
    # repr／doctor 的設定摘要
    assert TOKEN not in repr(config) and TOKEN not in json.dumps(redacted(config.raw), ensure_ascii=False)
    # log：SDK 連線錯誤會把 https://api.telegram.org/bot<token>/getUpdates 印出來
    logging.getLogger().error("HTTP GET error [getUpdates]: url /bot%s/getUpdates", config.bot_token)
    logging.error("plain %s", TOKEN)
    assert TOKEN not in caplog.text and "/bot***/getUpdates" in caplog.text
    # synox about
    from synox import brand
    assert TOKEN not in brand.about_text(str(path), root=str(tmp_path))
    # 回報摘要要遮的清單有真正的 token（raw 裡只剩參照了）
    from synox.web import report
    assert TOKEN in report.secret_values(None, config)
    # doctor：只說放在哪
    from synox import doctor
    lines = []
    doctor.run(offline=True, config_path=str(path), out=lines.append)
    text = "\n".join(lines)
    assert "在保管箱" in text and TOKEN not in text
    # 例外訊息
    with pytest.raises(tt.TokenUnavailable) as e:
        tt.resolve(tt.REF, FakeVault())
    assert TOKEN not in str(e.value)
    assert TOKEN not in capsys.readouterr().out
