"""備援（llm.waterfall，docs/adr/0046）：SYNOX 這一側——設定、包成員、結果翻回、ask 的按鈕卡。

換不換、換誰是 ntu_easy_llm router（`ntu_easy_llm.router.Router`）的事；這裡用**真的 router**，成員是 SYNOX 這一側的
假來源（照劇本回話或丟帶 kind 的 LLMError），不連網、不睡（觸發條件只用額度用完、金鑰失效，不走 429 的重試等待）。"""

import pytest

from synox.llm import router as wf
from synox.llm.base import USER, ChatAdapter, LLMError, Message, Reply
from synox.llm.factory import make_adapter

pytestmark = pytest.mark.usefixtures("no_sockets")


def needs_router():
    pytest.importorskip("ntu_easy_llm.router", reason="要 ntu_easy_llm 0.6 的 router")


class Member(ChatAdapter):
    """SYNOX 這一側的假來源：照劇本回話或丟 LLMError（帶 kind）。"""

    def __init__(self, name, script, *, tools=True, kind="fake"):
        self.name, self.kind, self.model = name, kind, name
        self.script = list(script)
        self.supports_tools = tools
        self.seen = []

    def chat(self, messages, tools=(), *, stop=()):
        self.seen.append((list(messages), list(tools)))
        step = self.script.pop(0)
        if isinstance(step, LLMError):
            raise step
        return Reply(text=step, usage={"input": 1, "output": 1})


def router_of(primary, backups, mode="auto", **policy):
    needs_router()
    built = wf.build(primary, backups, {"mode": mode, "backups": [{}] * len(backups), **policy})
    assert built is not None and type(built.router).__module__ == "ntu_easy_llm.router"
    return built


# ── 設定 ─────────────────────────────────────────────────────────────


def test_parse_shapes():
    assert wf.parse(None) is None
    out = wf.parse({"mode": "AUTO", "backups": [{"kind": "local", "model": "m"}], "retry_429": 1,
                    "triggers": ["quota_exhausted", "connection"], "_note": "註解"})
    assert out["mode"] == "auto" and out["retry_429"] == 1 and out["triggers"] == ["quota_exhausted", "connection"]
    for bad in ([], {"mode": "sometimes"}, {"mode": "auto", "backups": {}}, {"mode": "auto", "backups": [1]},
                {"mode": "auto", "backups": [{"kind": "fake", "waterfall": {}}]},
                {"mode": "auto", "backups": [{"kind": "none"}]},
                {"mode": "auto", "backups": [{"kind": "fake"}] * 5},
                {"mode": "auto", "triggers": ["trust"]}, {"mode": "auto", "triggers": "quota_exhausted"},
                {"mode": "auto", "cooldown_s": -1}, {"mode": "auto", "surprise": 1}):
        with pytest.raises(ValueError):
            wf.parse(bad)
    with pytest.raises(ValueError) as e:
        wf.parse({"mode": "auto", "triggers": ["trust"]})
    assert "永遠不能自動換" in str(e.value)


def test_config_checks_backups_like_llm(tmp_path):
    from synox.config import ConfigError, SynoxConfig
    base = {"owner_id": 1, "data_dir": str(tmp_path)}

    def load(llm):
        return SynoxConfig.from_dict({**base, "llm": llm}, require_token=False, root=str(tmp_path))
    c = load({"kind": "fake", "waterfall": {"mode": "ask", "backups": [{"kind": "local", "server": "ollama",
                                                                        "model": "m"}]}})
    assert "max_total_timeout" in c.llm["waterfall"]["backups"][0]         # 本地的預設照 local.validate 補上
    assert load({"kind": "fake"}).llm.get("waterfall") is None              # 沒寫＝照舊
    for bad in ({"kind": "fake", "waterfall": {"mode": "auto", "backups": [{"kind": "warp"}]}},
                {"kind": "fake", "waterfall": {"mode": "auto", "backups": [{"kind": "source", "source": "x"}]}},
                {"kind": "fake", "waterfall": {"mode": "auto", "backups": [{"kind": "local", "server": "nope",
                                                                            "model": "m"}]}}):
        with pytest.raises(ConfigError):
            load(bad)


def test_off_or_missing_is_exactly_the_old_single_source():
    plain = make_adapter({"llm": {"kind": "fake"}})
    assert type(plain).__name__ == "FakeAdapter"
    off = make_adapter({"llm": {"kind": "fake", "waterfall": {"mode": "off", "backups": [{"kind": "claude_code"}]}}})
    assert type(off).__name__ == "FakeAdapter"                               # off＝不建 router
    empty = make_adapter({"llm": {"kind": "fake", "waterfall": {"mode": "auto", "backups": []}}})
    assert type(empty).__name__ == "FakeAdapter"
    assert wf.status_line({"kind": "fake"}) == "備援：關（只用主要來源）"


def test_no_router_in_this_easy_llm_keeps_primary(monkeypatch):
    monkeypatch.setattr(wf, "router_class", lambda: None)
    a = make_adapter({"llm": {"kind": "fake", "waterfall": {"mode": "auto", "backups": [{"kind": "claude_code"}]}}})
    assert type(a).__name__ == "FakeAdapter"
    assert wf.status_line({"waterfall": {"mode": "auto", "backups": [{"kind": "fake"}]}}) == wf.NO_ROUTER


def test_factory_builds_the_real_router():
    needs_router()
    a = make_adapter({"llm": {"kind": "fake", "waterfall": {"mode": "ask", "backups": [{"kind": "claude_code"}]}}})
    assert isinstance(a, wf.RouterAdapter) and a.mode == "ask"
    assert [m.profile.id for m in a.members] == ["primary", "backup1"]
    assert a.members[1].profile.source == "remote/subscription/synox_claude_code"
    assert a.supports_tools is False                     # claude_code 沒有原生工具：整條鏈走文字協定
    assert wf.status_line({"waterfall": {"mode": "ask", "backups": [{"kind": "fake"}]}}) == "備援：先問我，1 個備援來源"


# ── auto ─────────────────────────────────────────────────────────────


def test_auto_switches_on_quota_and_says_so():
    a = router_of(Member("主要", [LLMError("額度沒了", kind="quota_exhausted")]), [Member("備援甲", ["好"])])
    reply = a.chat([Message(USER, "hi")])
    assert reply.text == "好"
    assert reply.warnings[0] == "已改用 備援甲（原因：額度用完）"


def test_auto_with_an_easy_llm_member_and_cooldown():
    """備援是 kind=source（ntu_easy_llm 自己的 adapter）；主要來源額度用完之後在冷卻，下一句直接跳過它。"""
    needs_router()
    primary = Member("主要", [LLMError("額度沒了", kind="quota_exhausted")])
    a = make_adapter({"llm": {"kind": "fake", "waterfall": {"mode": "auto", "backups": [
        {"kind": "source", "source": "local/fake", "model": "fake-1", "source_options": {"default": "備援回答"}}]}}})
    a.members[0].inner = primary                   # 主要來源換成會丟額度用完的假來源
    first = a.chat([Message(USER, "一")])
    assert first.text == "備援回答" and first.warnings[0].startswith("已改用 local/fake")
    second = a.chat([Message(USER, "二")])
    assert second.text == "備援回答" and len(primary.seen) == 1            # 冷卻中：沒有再叫主要來源
    rows = {r["id"]: r for r in a.status()}
    assert rows["primary"]["cooling_until"] and rows["primary"]["last_error"] == "quota_exhausted"


def test_auto_does_not_switch_on_ordinary_errors():
    backup = Member("備援甲", ["好"])
    a = router_of(Member("主要", [LLMError("伺服器壞了", kind="server_error")]), [backup])
    with pytest.raises(LLMError) as e:
        a.chat([Message(USER, "hi")])
    assert str(e.value) == "伺服器壞了" and e.value.kind == "server_error"      # 原本那句中文
    assert backup.seen == []


def test_untagged_synox_errors_are_unknown_and_never_trigger():
    backup = Member("備援甲", ["好"])
    a = router_of(Member("主要", [LLMError("不明")]), [backup])
    with pytest.raises(LLMError):
        a.chat([Message(USER, "hi")])
    assert backup.seen == []


def test_everyone_failed_lists_each():
    a = router_of(Member("主要", [LLMError("x", kind="quota_exhausted")]),
                  [Member("備援甲", [LLMError("y", kind="auth_invalid")])])
    with pytest.raises(LLMError) as e:
        a.chat([Message(USER, "hi")])
    assert "主要：額度用完" in str(e.value) and "備援甲：金鑰不對或已失效" in str(e.value)


def test_members_get_synox_messages_and_tools_round_trip():
    from synox.llm.base import ToolSpec
    backup = Member("備援甲", ["好"])
    a = router_of(Member("主要", [LLMError("x", kind="quota_exhausted")]), [backup])
    spec = ToolSpec("money__add", "記一筆", {"type": "object", "properties": {}})
    a.chat([Message(USER, "記 80")], [spec])
    msgs, tools = backup.seen[0]
    assert msgs[0].role == USER and msgs[0].content == "記 80" and tools[0].name == "money__add"


def test_weak_if_any_member_is_local():
    from synox.agent.auto import weak_source
    a = router_of(Member("雲", ["x"]), [Member("本地", ["y"], kind="local")])
    assert a.weak is True and weak_source(a) is True
    b = router_of(Member("雲", ["x"]), [Member("雲二", ["y"])])
    assert weak_source(b) is False


# ── ask ──────────────────────────────────────────────────────────────


def test_ask_raises_fallback_ask_with_choices_and_pinned_turn():
    backup = Member("備援甲", ["改用之後的回答"])
    a = router_of(Member("主要", [LLMError("額度沒了", kind="quota_exhausted")]), [backup], mode="ask")
    with pytest.raises(wf.FallbackAsk) as e:
        a.chat([Message(USER, "hi")])
    err = e.value
    assert err.kind == "quota_exhausted" and err.choices == [("backup1", "備援甲")] and err.adapter is a
    assert "主要：額度用完" in str(err)
    with a.pinned("backup1"):
        assert a.chat([Message(USER, "hi")]).text == "改用之後的回答"     # 選了之後直接用那一個，不經 router
    assert len(backup.seen) == 1
    with pytest.raises(LLMError):
        with a.pinned("nobody"):
            pass


def test_ask_card_resends_the_turn_with_the_chosen_source(make_bot, owner):
    needs_router()
    from synox.llm.fake import FakeAdapter
    primary = Member("主要", [LLMError("額度沒了", kind="quota_exhausted")])
    backup = FakeAdapter(["換過來了"])
    backup.name = "備援甲"
    a = wf.build(primary, [backup], {"mode": "ask", "backups": [{}]})
    bot = make_bot(adapter=a)
    bot.talk(owner, "今天天氣如何")
    assert "主要：額度用完" in bot.last(owner)
    use = [b for b in bot.buttons(owner) if b.startswith("agent_fb:use:")]
    assert use and any(b.startswith("agent_fb:no:") for b in bot.buttons(owner))
    bot.press(OTHER, use[0])                              # 別人按：當作不存在（agent 群組只給擁有者）
    bot.press_and_wait(owner, use[0])
    assert "換過來了" in bot.last(owner)
    bot.press(owner, use[0])                              # 用過一次就沒了
    assert "過期" in bot.last(owner)


def test_ask_card_no_button(make_bot, owner):
    needs_router()
    a = wf.build(Member("主要", [LLMError("x", kind="auth_invalid")]), [Member("備援甲", ["不該用到"])],
                 {"mode": "ask", "backups": [{}]})
    bot = make_bot(adapter=a)
    bot.talk(owner, "嗨")
    no = [b for b in bot.buttons(owner) if b.startswith("agent_fb:no:")][0]
    bot.press_and_wait(owner, no)
    assert "不換來源" in bot.last(owner)


OTHER = 555
