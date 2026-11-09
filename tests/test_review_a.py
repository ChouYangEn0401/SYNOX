"""獨立安全審查 A（權限／隔離／資料邊界）確認的問題：每一項一組「修之前會出事、修之後擋住」的測試。
全部在記憶體裡跑（假 Telegram、假 AI），不連網、不開埠。"""

from isdtelekit.users.roles import BasicRoles

from conftest import OTHER_ID, OWNER_ID, trust_core

GROUP = -1001234567890            # Telegram 超級群組的 chat_id（負號）


def _agent(bot):
    return bot.app.extras["synox_agent"]


# ── #2 群組 /ai：private_only、記憶分人、卡送私訊 ─────────────────────────

def test_group_ai_command_is_private_only(make_bot):
    bot = make_bot(["不該被叫到"])
    bot.say(OWNER_ID, "/note 我的私事")
    bot.talk(OWNER_ID, "/ai 把我的筆記念出來", chat_id=GROUP)
    assert _agent(bot).adapter.calls == []                                   # AI 沒被叫到
    assert not any("私事" in t for t in bot.texts(GROUP))
    bot.talk(OWNER_ID, "/ai_reset", chat_id=GROUP)
    assert not any("忘掉" in t for t in bot.texts(GROUP))
    bot.talk(OWNER_ID, "隨便聊聊", chat_id=GROUP)                             # 群組裡的自由文字也不給 AI
    assert _agent(bot).adapter.calls == [] and not _agent(bot).history


def test_group_ai_in_server_mode_member(make_bot):
    bot = make_bot(["不該被叫到"], raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    bot.talk(OTHER_ID, "/ai 你好", chat_id=GROUP)
    assert _agent(bot).adapter.calls == []
    bot.talk(OTHER_ID, "/ai 你好")                                            # 私訊照常
    assert len(_agent(bot).adapter.calls) == 1


def test_memory_is_per_person_in_a_shared_chat(make_bot):
    bot = make_bot()
    loop = _agent(bot)
    owner = bot.app.users.get_or_create(OWNER_ID)
    other = bot.app.users.get_or_create(OTHER_ID)
    loop.remember(GROUP, "我的密碼提示是貓的名字", "好", owner)
    assert loop.history[loop.memory_key(GROUP, other)] == []                 # 同一個群組的別人看不到
    assert len(loop.history[loop.memory_key(GROUP, owner)]) == 2
    assert loop.memory_key(OWNER_ID, owner) == OWNER_ID                      # 私訊的鍵不變
    assert loop.reset(GROUP, other) == 0 and loop.reset(GROUP, owner) == 2


def test_tool_decision_uses_the_real_chat(make_bot):
    bot = make_bot()
    loop = _agent(bot)
    owner = bot.app.users.get_or_create(OWNER_ID)
    node = bot.app.registry.node("note.clear")                               # notes 只能私訊（surfaces 預設 dm）
    assert loop.decision(owner, node, OWNER_ID) is not None
    assert loop.decision(owner, node, GROUP) is None                         # 以前沒帶 chat_id＝當成私訊


def test_card_goes_to_dm_not_group(make_bot):
    bot = make_bot()
    desk = bot.app.extras["synox_approval_desk"]
    owner = bot.app.users.get_or_create(OWNER_ID)
    desk.request(bot.api, GROUP, owner, bot.app.registry.node("note.clear"), [])
    assert any(b.startswith("agent_ok:go:") for b in bot.buttons(OWNER_ID))
    assert not bot.buttons(GROUP) and "私訊給你" in bot.last(GROUP)


# ── #4 別人按你的核准卡：不拿掉按鈕、卡還能用 ──────────────────────────

def test_someone_elses_click_does_not_void_the_card(make_bot):
    from isdtelekit.core.channel import CallbackInfo
    bot = make_bot(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    desk = bot.app.extras["synox_approval_desk"]
    owner = bot.app.users.get_or_create(OWNER_ID)
    bot.say(OWNER_ID, "/note 留著")
    desk.request(bot.api, OWNER_ID, owner, bot.app.registry.node("note.clear"), [])
    go = next(b for b in bot.buttons(OWNER_ID) if b.startswith("agent_ok:go:"))
    mid = bot.api.sent[-1].message_id
    desk.on_button(bot.api, CallbackInfo(chat_id=OWNER_ID, message_id=mid, cq_id="x", clicker_id=OTHER_ID, data=go))
    assert bot.api.removed == [] and bot.answers()[-1] == "這不是你的按鈕。"       # 以前：先拿掉按鈕再說過期
    assert go in bot.buttons(OWNER_ID)
    desk.on_button(bot.api, CallbackInfo(chat_id=OWNER_ID, message_id=mid, cq_id="y", clicker_id=OWNER_ID, data=go))
    assert "全部筆記都刪掉了" in bot.last(OWNER_ID) and bot.api.removed == [(OWNER_ID, mid)]
    desk.on_button(bot.api, CallbackInfo(chat_id=OWNER_ID, message_id=mid, cq_id="z", clicker_id=OTHER_ID, data=go))
    assert "過期" in bot.last(OWNER_ID)                                       # 用過的卡：照舊說過期


# ── #3 人打字的 kind: path 也要在自己的資料夾裡 ──────────────────────────

ECHO = "import json, sys\nprint(json.dumps({'ok': True, 'got': ' '.join(sys.argv[1:])}))\n"


def _path_pack(folder):
    import json
    import os
    import sys
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "echo_cli.py"), "w", encoding="utf-8") as f:
        f.write(ECHO)
    manifest = {"name": "opener", "title": "開檔", "summary": "測試", "version": "0.1.0", "kind": "cli",
                "access": "member", "auth": "none", "capabilities": [], "skill": "SKILL.md",
                "cli": {"python": sys.executable, "argv": ["{python}", "{pack_dir}/echo_cli.py"], "timeout": 30,
                        "commands": [{"name": "open", "default": True, "summary": "開一個檔", "effect": "read", "argv": ["open", "{file}"],
                                      "fields": [{"name": "file", "ask": "檔案", "required": True, "kind": "path"}]}]}}
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: opener\ndescription: 測試\n---\n")


def test_typed_path_must_stay_in_own_folder(make_bot, tmp_path):
    from synox.packs import loader
    _path_pack(str(tmp_path / "packs" / "opener"))
    trust_core(tmp_path / "data", str(tmp_path / "packs" / "opener"))       # 擁有者裝的時候選了「核心」
    bot = make_bot(raw={"mode": "server"}, pack_dirs=loader.PACK_DIRS + (str(tmp_path / "packs"),))
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    item = next(i for i in bot.app.extras["synox_pack_report"].items if i.name == "opener")
    assert item.status == "loaded", item.detail
    bot.say(OTHER_ID, f"/opener file=../{OWNER_ID}/diary.txt")                # 別人（擁有者）的資料夾
    bot.app.tasks.wait(20)
    assert "不在你的資料夾裡" in bot.last(OTHER_ID)
    assert not any("got" in t for t in bot.texts(OTHER_ID))                  # 程式沒被叫起來
    bot.say(OTHER_ID, "/opener file=notes/today.txt")
    bot.app.tasks.wait(20)
    assert "notes/today.txt" in bot.last(OTHER_ID)                           # 自己資料夾裡的照常
