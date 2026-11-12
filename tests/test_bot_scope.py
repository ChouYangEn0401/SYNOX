# -*- coding: utf-8 -*-
"""PERM-4 bot 範圍：每個 Discord bot 的 packs／max_effect／ai 真的生效（打字、/help、群組、AI 工具清單），
/bot_status 與 doctor 列出每個 bot 會出現的 pack 和「設定了但不會出現」的原因。
全部假傳輸（假 HTTP、直接餵 Gateway 事件），不連 Discord、不開埠。"""

from isdtelekit.core.registry import TYPED

from synox import policy
from synox.discord import scope
from synox.discord.bots import BotSpec
from synox.llm.fake import FakeAdapter

from test_discord import dm
from test_discord_multibot import TOK_A, TOK_B, _config_file, make_app

TOK_R, TOK_N = "token.readonly", "token.noai"
SECRETS = {"discord_bot_token:alpha": TOK_A, "discord_bot_token:bravo": TOK_B,
           "discord_bot_token:ro": TOK_R, "discord_bot_token:noai": TOK_N}
BOTS = {"bots": {
    "alpha": {"surface": "dm", "packs": "all"},
    "bravo": {"surface": "dm", "packs": ["notes"]},
    "ro": {"surface": "dm", "packs": ["notes", "money", "weather"], "max_effect": "read"},
    "noai": {"surface": "dm", "packs": ["notes"], "ai": False},
}}
CHANNELS = {"alpha": "dmA-777", "bravo": "dmB-777", "ro": "dmR-777", "noai": "dmN-777"}


def _app(tmp_path):
    return make_app(tmp_path, BOTS, secrets=SECRETS)


def say(app, http, bot, text, uid="777"):
    """用 bot 私訊一句，回這次那個 bot 回的每一則文字。"""
    channel = CHANNELS[bot]
    before = len(http.calls)
    app.extras["discord_entries"][bot].on_dispatch("MESSAGE_CREATE", dm(uid=uid, text=text, channel=channel)["d"])
    app.tasks.wait(5)
    return [kw["json"].get("content", "") for m, u, kw in http.calls[before:]
            if m == "POST" and u.endswith(f"/channels/{channel}/messages")]


def owner(app):
    return app.users.get_or_create(app.config.owner_id)


# ── 人打字 ───────────────────────────────────────────────────────────

def test_same_person_money_on_a_unknown_on_notes_only_bot(tmp_path):
    app, http, _ = _app(tmp_path)
    assert "共 0 元" in " ".join(say(app, http, "alpha", "/money_month"))
    out = say(app, http, "bravo", "/money_month")
    assert out == ["未知指令：/money_month，輸入 /help 查看可用指令。"]          # 跟不存在的指令一模一樣
    assert say(app, http, "bravo", "/money 80 咖啡") == ["未知指令：/money，輸入 /help 查看可用指令。"]
    assert say(app, http, "bravo", "/nosuch") == ["未知指令：/nosuch，輸入 /help 查看可用指令。"]
    assert not say(app, http, "bravo", "/note 買牛奶")[0].startswith("未知指令")   # 開了的 pack 照常（舊訊息先問）
    assert "未知指令" not in " ".join(say(app, http, "bravo", "/note_list"))
    assert not any("80" in r for r in say(app, http, "alpha", "/money_list"))   # bravo 那筆 /money 沒有記進去


def test_help_and_group_menu_follow_the_bot(tmp_path):
    app, http, _ = _app(tmp_path)
    a = " ".join(say(app, http, "alpha", "/help all"))
    b = " ".join(say(app, http, "bravo", "/help all"))
    assert "/money" in a and "/note" in a
    assert "/money" not in b and "/note" in b
    assert "/remind_add" in b                       # ⏰ 提醒（系統）是系統指令，跟 /schedule_* 一樣不看 bot 的 pack 清單
    reg = app.registry
    with policy.using_bot(app.extras["discord_specs"]["bravo"]):
        assert policy.hidden(app, owner(app), reg.node("money"))                  # 群組本身也不存在（打群組名同未知指令）
        assert not reg.visible(owner(app), reg.node("money"))
        assert app.dispatcher._hidden_from(owner(app), reg.node("money"))
        assert not app.dispatcher._hidden_from(owner(app), reg.node("note"))
    assert not app.dispatcher._hidden_from(owner(app), reg.node("money"))       # 沒有 bot（Telegram、網頁）＝不限制


def test_max_effect_read_refuses_write_command(tmp_path):
    app, http, _ = _app(tmp_path)
    out = say(app, http, "ro", "/note 買牛奶")
    assert len(out) == 1 and "唯讀" in out[0] and "寫入" in out[0] and "/note" in out[0]
    assert not out[0].startswith("未知指令")                                     # pack 有開：被拒，不是不存在
    listed = " ".join(say(app, http, "alpha", "/note_list"))
    assert "買牛奶" not in listed                                               # 沒有記進去
    assert "未知指令" not in " ".join(say(app, http, "ro", "/note_list"))         # 唯讀的照常
    help_text = " ".join(say(app, http, "ro", "/help all"))
    assert "/note_list" in help_text and "/note_clear" not in help_text         # 超過上限的不列
    d = policy.decide(app, owner(app), app.registry.node("note.clear"), via=TYPED, chat_id=app.config.owner_id,
                      bot=app.extras["discord_specs"]["ro"])
    assert not d.allowed and d.reason == "bot_effect"


def test_bot_with_ai_off_has_no_agent(tmp_path):
    app, http, _ = _app(tmp_path)
    app.extras["synox_agent"].adapter = FakeAdapter(["不該被叫到"])
    assert say(app, http, "noai", "/ai 你好")[0].startswith("未知指令")
    out = say(app, http, "noai", "你好")
    assert out and "不該被叫到" not in out[0]
    assert app.extras["synox_agent"].adapter.calls == []


# ── AI 工具清單 ──────────────────────────────────────────────────────

def _tools_seen(app):
    return {t.name for t in app.extras["synox_agent"].adapter.calls[-1][1]}


def test_ai_tool_list_follows_the_bot(tmp_path):
    app, http, _ = _app(tmp_path)
    app.extras["synox_agent"].adapter = FakeAdapter(["好"])
    say(app, http, "alpha", "幫我看看")
    full = _tools_seen(app)
    assert any(t.startswith("money__") for t in full) and "note__add" in full
    app.extras["synox_agent"].adapter = FakeAdapter(["好"])
    say(app, http, "bravo", "幫我看看")
    b = _tools_seen(app)
    assert "note__add" in b
    assert not any(t.startswith("money__") for t in b)
    system = app.extras["synox_agent"].adapter.calls[-1][0][0].content
    assert "記帳" not in system                                                 # 系統提示也沒有別的 pack 的名字
    app.extras["synox_agent"].adapter = FakeAdapter(["好"])
    say(app, http, "ro", "幫我看看")
    r = _tools_seen(app)
    assert "note__list" in r and "money__month" in r
    assert "note__add" not in r and "money__add" not in r and "note__clear" not in r


def test_ai_calling_tool_outside_bot_is_not_run(tmp_path):
    app, http, _ = _app(tmp_path)
    app.extras["synox_agent"].adapter = FakeAdapter([{"tool": "money__add", "args": {"amount": "80"}}, "好"])
    assert say(app, http, "bravo", "記一筆 80") == ["好"]
    msgs = [m for m in app.extras["synox_agent"].adapter.calls[-1][0] if m.role == "tool"]
    assert any("沒有 money__add 這個工具" in m.content for m in msgs)
    assert not any("80" in r for r in say(app, http, "alpha", "/money_list"))


# ── /bot_status、doctor ─────────────────────────────────────────────

def test_bot_status_lists_effective_and_hidden_packs(tmp_path):
    app, http, _ = _app(tmp_path)
    text = "\n".join(say(app, http, "alpha", "/bot_status"))
    assert "bot bravo" in text and "bot ro" in text
    ro = text.split("bot ro")[1].split("bot noai")[0]
    assert "weather：沒有載入" in ro                                            # 清單寫了但沒裝
    assert "money（2 個指令超過上限「唯讀」，不會出現）" in ro
    assert say(app, http, "alpha", "/bot_status", uid="4242")[0].startswith("未知指令")   # 個人版：只有擁有者


def test_bot_status_and_doctor_explain_card_limit(tmp_path):
    """審查 A #11：確認卡綁在 agent 群組，ai:false 的 bot（和頻道型、訪客）按不了——先在 /bot_status、doctor 說明。"""
    app, http, _ = _app(tmp_path)
    text = "\n".join(say(app, http, "alpha", "/bot_status"))
    noai = text.split("bot noai")[1]
    assert "確認卡按不動" in noai and "ai: false" in noai
    assert "確認卡按不動" not in text.split("bot alpha")[1].split("bot bravo")[0]     # 開著 AI 的私訊型：按得動
    channel = BotSpec(name="room", token="vault:x", surface="channel")
    assert "頻道型" in scope.card_limit(channel)
    from synox import doctor
    (tmp_path / "doc" / "data").mkdir(parents=True)
    cfg = _config_file(tmp_path / "doc", BOTS)
    lines = []
    doctor.run(offline=True, config_path=cfg, out=lines.append)
    assert "確認卡按不動" in "\n".join(lines).split("bot noai（")[1]


def test_report_effect_reason_is_extensible():
    spec = BotSpec(name="x", token="vault:x", packs=("w", "r", "c"), max_effect="read")
    infos = {"w": scope.PackInfo("w", ("write", "danger")), "r": scope.PackInfo("r", ("read", "write")),
             "c": scope.PackInfo("c", ())}
    rep = scope.report(spec, infos)
    assert [n for n, _ in rep["effective"]] == ["r"]
    hidden = dict(rep["hidden"])
    assert "超過這個 bot 的上限「唯讀」" in hidden["w"] and "沒有任何指令" in hidden["c"]
    assert scope.REASONS[-1] is scope._over_max_effect                          # PERM-2 在後面加原因


def test_doctor_shows_bot_scope(tmp_path):
    from synox import doctor
    from synox.vault import Vault
    from synox.vault.keyring import write_key
    cfg = _config_file(tmp_path, BOTS)
    data = tmp_path / "data"
    data.mkdir()
    write_key(str(data / ".synox.key"), b"k" * 32, "file")
    vault = Vault(b"k" * 32, str(data))
    for k, v in SECRETS.items():
        vault.set_secret(k, v)
    lines = []
    doctor.run(offline=True, config_path=cfg, out=lines.append)
    text = "\n".join(lines)
    assert "4 個 bot" in text
    bravo = text.split("bot bravo")[1].split("bot ro")[0]
    assert "會出現：notes" in bravo and "沒開給這個 bot：" in bravo
    assert "weather：沒有載入" in text.split("bot ro")[1]
    assert TOK_A not in text
