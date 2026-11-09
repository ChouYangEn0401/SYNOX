"""個人版／伺服器版（config 的 mode）：設定解析、伺服器版每人一份資料（互相解不開）、訪客只看得到 access: everyone。"""

import json
import os

import pytest

from isdtelekit.host.config import ConfigError
from isdtelekit.users.roles import BasicRoles

from synox.config import SynoxConfig, parse_mode
from synox.packs import loader
from synox.vault import Vault, VaultError

from conftest import OTHER_ID, enc_files, trust_core

STRANGER = 777


# ── 設定 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [(None, "personal"), ("", "personal"), ("personal", "personal"),
                                          ("server", "server"), (" Server ", "server")])
def test_parse_mode(raw, expected):
    assert parse_mode(raw) == expected


def test_bad_mode_is_a_clear_error(tmp_path):
    with pytest.raises(ConfigError) as e:
        SynoxConfig.from_dict({"owner_id": 1, "mode": "company"}, require_token=False, root=str(tmp_path))
    assert "personal" in str(e.value) and "server" in str(e.value)


def test_hand_written_config_with_mode_loads(tmp_path):
    """工程師模式：自己寫的 config.json（照 config.example.json）直接能用。"""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"bot_token": "123456789:AAH-abcdefghijklmnopqrstuvwxyz012345", "owner_id": 42,
                                "mode": "server", "llm": {"kind": "none"}}), encoding="utf-8")
    config = SynoxConfig.load(str(path))
    assert config.mode == "server" and config.server and config.data_dir == os.path.join(str(tmp_path), "data")
    assert SynoxConfig.from_dict({"owner_id": 1}, require_token=False, root=str(tmp_path)).mode == "personal"


def test_example_config_is_valid_and_personal():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "config.example.json"), encoding="utf-8") as f:
        raw = json.load(f)
    config = SynoxConfig.from_dict(raw, root=root)
    assert config.mode == "personal" and raw["mode"] == "personal"


# ── 個人版：照舊 ─────────────────────────────────────────────────────

def test_personal_mode_keeps_one_shared_file_and_no_accounts(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/note 買牛奶")
    assert "notes.json.enc" in enc_files(bot)
    assert not os.path.exists(os.path.join(bot.app.config.data_dir, "users"))
    assert bot.app.registry.node("user") is None and bot.app.registry.node("limit") is None
    group = bot.app.registry.node("note")
    assert group.policy.owner_only                                     # access=member 在個人版＝只有擁有者


# ── 伺服器版：每人一份 ───────────────────────────────────────────────

def test_server_mode_installs_account_packs(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    assert bot.app.registry.node("user") is not None and bot.app.registry.node("limit") is not None
    bot.say(owner, f"/user_role {OTHER_ID} member")
    assert bot.app.users.get(OTHER_ID).role == BasicRoles.MEMBER


def test_server_mode_isolates_each_persons_data(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    bot.say(owner, "/note 擁有者的秘密")
    bot.say(OTHER_ID, "/note 成員的筆記")
    bot.say(OTHER_ID, "/money 120 午餐")
    data = bot.app.config.data_dir
    mine = os.path.join(data, "users", str(owner), "notes.json.enc")
    theirs = os.path.join(data, "users", str(OTHER_ID), "notes.json.enc")
    assert os.path.isfile(mine) and os.path.isfile(theirs)
    assert os.path.isfile(os.path.join(data, "users", str(OTHER_ID), "money.json.enc"))
    assert not os.path.exists(os.path.join(data, "notes.json.enc"))   # 沒有共用檔
    for path in (mine, theirs):
        with open(path, "rb") as f:
            blob = f.read()
        assert "筆記".encode("utf-8") not in blob and "秘密".encode("utf-8") not in blob

    bot.clear()
    bot.say(OTHER_ID, "/note_list")
    assert "成員的筆記" in bot.last(OTHER_ID) and "秘密" not in bot.last(OTHER_ID)
    bot.say(owner, "/note_list")
    assert "擁有者的秘密" in bot.last(owner) and "成員的筆記" not in bot.last(owner)
    bot.say(OTHER_ID, "/note_clear")                               # DANGER：只清自己的
    bot.say(owner, "/note_list")
    assert "擁有者的秘密" in bot.last(owner)


def test_cross_read_is_impossible(tmp_path):
    master = Vault(b"m" * 32, str(tmp_path))
    a, b = master.for_user(1001), master.for_user(1002)
    a.save_json("notes", {"items": ["A 的"]})
    b.save_json("notes", {"items": ["B 的"]})
    assert a.load_json("notes") == {"items": ["A 的"]} and master.for_user(1001) is a
    with open(b.path("notes"), "rb") as f:
        blob_b = f.read()
    with pytest.raises(VaultError):
        a.decrypt(blob_b)                                          # A 的金鑰解不開 B 的檔
    with pytest.raises(VaultError):
        master.decrypt(blob_b)                                     # 主金鑰本身也不能直接解（要先衍生）
    assert Vault(b"m" * 32, str(tmp_path)).for_user(1002).load_json("notes") == {"items": ["B 的"]}  # 衍生是確定的
    with pytest.raises(ValueError):
        master.for_user("1001")


def test_plain_store_is_per_user_in_server_mode(tmp_path):
    store = loader.PackStore("remind", str(tmp_path), None, per_user=True)

    class U:
        def __init__(self, tg_id):
            self.tg_id = tg_id
    store.of(U(5)).save({"x": 1})
    assert os.path.isfile(os.path.join(str(tmp_path), "users", "5", "remind.json"))
    assert store.of(U(6)).load({}) == {} and store.of(5) is store.of(U(5))
    shared = loader.PackStore("remind", str(tmp_path), None)
    assert shared.of(U(5)) is shared


# ── 伺服器版：訪客只看得到 everyone ─────────────────────────────────

def _everyone_pack(base):
    folder = os.path.join(base, "hello")
    os.makedirs(folder)
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "hello", "title": "👋 打招呼", "summary": "誰都能用", "version": "0.1.0",
                   "kind": "python", "access": "everyone"}, f)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: hello\ndescription: d\n---\n")
    with open(os.path.join(folder, "pack.py"), "w", encoding="utf-8") as f:
        f.write("def install(app, pack):\n"
                "    pack.group.leaf('hi', lambda api, c, u, a: api.send_message(c, 'hi there'), '打招呼', default=True)\n")
    return base


def test_server_guest_sees_only_everyone_packs(make_bot, owner, tmp_path):
    extra = _everyone_pack(str(tmp_path / "extra"))
    trust_core(tmp_path / "data", os.path.join(extra, "hello"))     # 手放的 python pack＝third-party（PERM-8）
    bot = make_bot(raw={"mode": "server"}, pack_dirs=loader.PACK_DIRS + (extra,))
    bot.say(STRANGER, "/start")
    guest = bot.app.users.get(STRANGER)
    assert guest is not None and guest.role == BasicRoles.GUEST       # 陌生人自動登記成訪客
    registry = bot.app.registry
    pack_groups = {p.manifest.group for p in bot.app.extras["synox_packs"]}
    visible = {g for g in pack_groups if registry.visible(guest, registry.node(g))}
    assert visible == {"hello"}
    bot.say(STRANGER, "/hello")
    assert bot.last(STRANGER) == "hi there"
    bot.clear()
    bot.say(STRANGER, "/note 想偷用")
    assert not os.path.exists(os.path.join(bot.app.config.data_dir, "users", str(STRANGER)))
    # 升成成員之後就能用 notes（access: member），而且是自己的一份
    bot.say(owner, f"/user_role {STRANGER} member")
    member = bot.app.users.get(STRANGER)
    assert registry.visible(member, registry.node("note")) and registry.visible(member, registry.node("remind"))
    assert not registry.visible(member, registry.node("gcal"))         # connector（access: owner）仍然只有擁有者
    bot.say(STRANGER, "/note 我的")
    assert os.path.isfile(os.path.join(bot.app.config.data_dir, "users", str(STRANGER), "notes.json.enc"))
