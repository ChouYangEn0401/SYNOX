"""Context 預算（agent/context.py，docs/adr/0015、0016）：估算、Qwen-Agent 式分級截斷、工具結果上限；
迴圈只在 llm.context_size 有設時才裁，送副本（對話紀錄不改），截了一律寫 log 並另送一則提醒。全部用假 adapter。"""

import logging

import pytest

from synox.agent import context
from synox.config import SynoxConfig
from synox.llm import textproto
from synox.llm.base import ASSISTANT, SYSTEM, TOOL, USER, Message, ToolCall
from isdtelekit.host.config import ConfigError


def test_estimate():
    assert context.estimate("中" * 100) == 115
    assert context.estimate("a" * 400) == 115
    assert context.estimate("") == 0
    assert context.estimate("中文ab") == 3          # (2 + 0.5) × 1.15 → 3


def test_cap_result():
    text = "頭" * 2000 + "尾" * 1000 + "末" * 1000
    out = context.cap_result(text, 300)
    assert out.startswith("頭" * 200) and out.endswith("末" * 100)
    assert "（省略 3700 字；" in out
    assert context.cap_result("短", 300) == "短"
    assert context.cap_result(text, 0) == text


def _conversation(n_turns=10, results=3, result_chars=800):
    msgs = [Message(SYSTEM, "系統說明" * 20 + "\n\n## 使用者偏好\n" + "偏好" * 100)]
    for i in range(n_turns):
        msgs += [Message(USER, f"第 {i} 輪的問題" + "問" * 60), Message(ASSISTANT, f"第 {i} 輪的回答" + "答" * 60)]
    msgs.append(Message(USER, "這一輪要做的事"))
    for i in range(results):
        msgs.append(Message(ASSISTANT, "", tool_calls=[ToolCall("note__list", {}, f"c{i}")]))
        msgs.append(Message(TOOL, f"結果{i}：" + "字" * result_chars, tool_call_id=f"c{i}", name="note__list"))
    return msgs


def test_fit_limit_zero_returns_as_is():
    msgs = _conversation()
    out = context.fit(msgs, 0)
    assert out.messages == msgs and not out.changed


def test_fit_drops_old_turns_first_and_keeps_system_and_latest_user():
    msgs = _conversation(results=0)
    total = context.total_tokens(msgs)
    out = context.fit(msgs, total - 300, start=21)
    assert out.dropped_turns >= 1 and not out.omitted_results and not out.cut_chars
    assert out.messages[0] is msgs[0] and out.messages[-1] is msgs[-1]
    assert out.messages[1].content.startswith(f"第 {out.dropped_turns} 輪")         # 丟的是最舊的那幾對
    assert context.total_tokens(out.messages) <= total - 300
    assert len(msgs) == 22                                                            # 原本的 list 沒被改


def test_fit_order_turns_then_old_results_then_last_result_then_soul():
    msgs = _conversation()
    snapshot = [(m.role, m.content) for m in msgs]
    system_and_user = context.total_tokens([msgs[0], msgs[21]])
    out = context.fit(msgs, system_and_user + 400, start=21)
    roles = [m.role for m in out.messages]
    assert out.dropped_turns == 10 and roles[:2] == [SYSTEM, USER]                    # (1) 歷史全丟
    tools = [m for m in out.messages if m.role == TOOL]
    assert [t.content for t in tools[:-1]] == [context.OMITTED, context.OMITTED]       # (2) 前面的結果省略
    assert "（省略" in tools[-1].content and tools[-1].content.startswith("結果2：")    # (3) 最後一則保頭
    assert out.cut_chars > 0 and out.omitted_results == 2
    assert out.messages[1].content == "這一輪要做的事"                                # 最新的 USER 原樣
    assert [(m.role, m.content) for m in msgs] == snapshot                             # 原本的 Message 都沒被改
    # (4) 還是不夠：拿掉 soul 區塊（系統提示的其他部分不動）
    soul = "## 使用者偏好\n" + "偏好" * 100
    tight = context.fit(msgs, context.total_tokens([msgs[0]]), start=21, soul=soul)
    assert tight.soul_dropped and context.SOUL_OMITTED in tight.messages[0].content
    assert tight.messages[0].content.startswith("系統說明") and tight.over


def test_fit_text_protocol_results():
    msgs = [Message(SYSTEM, "s"), Message(USER, "做事")]
    for i in range(3):
        msgs += [Message(ASSISTANT, '{"tool": "note__list", "args": {}}'),
                 Message(USER, textproto.result_message("note__list", "字" * 500))]
    out = context.fit(msgs, context.total_tokens(msgs) - 400, start=1)
    first = out.messages[3]
    assert first.content == f"{textproto.RESULT_PREFIX}note__list\n{context.OMITTED}"
    assert context.is_result(first) and out.omitted_results >= 1


def test_note_text():
    assert context.note_text(limit=8192) == ""
    text = context.note_text(limit=8192, dropped_turns=2, omitted_results=1, capped=["note__list", "note__list"])
    assert "context_size=8192" in text and "較舊的 2 輪對話" in text and "note__list" in text
    assert "仍然太長" in context.note_text(limit=4096, over=True)


def test_settings():
    assert context.context_limit({}) == 0 and context.context_limit({"context_size": 8192}) == 8192
    assert context.result_chars({}) == 0                                       # 沒預算：不限（以前的行為）
    assert context.result_chars({"context_size": 8192}) == context.DEFAULT_RESULT_CHARS
    assert context.result_chars({"tool_result_chars": 500}) == 500
    assert context.result_chars({"context_size": 8192, "tool_result_chars": 0}) == 0
    cfg = SynoxConfig.from_dict({"owner_id": 1, "llm": {"kind": "openai", "context_size": 16384,
                                                        "tool_result_chars": "2000"}}, require_token=False)
    assert cfg.llm["context_size"] == 16384 and cfg.llm["tool_result_chars"] == 2000
    for bad in ({"tool_result_chars": "lots"}, {"context_size": 10}):
        with pytest.raises(ConfigError):
            SynoxConfig.from_dict({"owner_id": 1, "llm": {"kind": "openai", **bad}}, require_token=False)


# ── 迴圈 ─────────────────────────────────────────────────────────────

def _fill_history(loop, owner, n=10):
    for i in range(n):
        loop.remember(owner, f"第 {i} 輪" + "問" * 200, f"第 {i} 輪的回答" + "答" * 200)


def test_loop_without_context_size_sends_everything(make_bot, owner):
    bot = make_bot(["好"])
    loop = bot.app.extras["synox_agent"]
    _fill_history(loop, owner)
    bot.talk(owner, "嗨")
    sent = loop.adapter.calls[0][0]
    assert len(sent) == 14 and bot.texts()[-1] == "好"                         # 記憶最多 6 輪
    assert not any("context 預算" in t for t in bot.texts())


def test_loop_fits_a_copy_and_tells_the_user(make_bot, owner, caplog):
    bot = make_bot(["好", "好"])
    loop = bot.app.extras["synox_agent"]
    bot.talk(owner, "嗨")                                                   # 先量系統提示＋工具規格多大
    first = loop.adapter.calls[0]
    tools_json = context.estimate(str([(t.name, t.description, t.parameters) for t in first[1]]))
    base = context.total_tokens(first[0]) + tools_json + 1024
    loop.reset(owner)
    _fill_history(loop, owner)
    loop.llm["context_size"] = base + 600
    with caplog.at_level(logging.WARNING):
        bot.talk(owner, "再一次")
    sent = loop.adapter.calls[1][0]
    assert len(sent) < 14 and sent[0].role == SYSTEM and sent[-1].content == "再一次"
    assert len(loop.history[owner]) == 12                                   # 記憶本身沒被裁（6 輪上限＋這一輪）
    texts = bot.texts()
    assert texts[-2] == "好" and texts[-1].startswith("⚠️ 對話超過 context 預算") and "較舊的" in texts[-1]
    assert "context budget" in caplog.text


def test_loop_caps_long_tool_results(make_bot, owner):
    bot = make_bot([{"tool": "note__add", "args": {"text": "長" * 300}}, "記好了"],
                   llm={"kind": "fake", "tool_result_chars": 40})
    bot.talk(owner, "記一下")
    loop = bot.app.extras["synox_agent"]
    tool_msg = [m for m in loop.adapter.calls[1][0] if m.role == TOOL][0]
    assert "（省略" in tool_msg.content and len(tool_msg.content) < 200
    assert tool_msg.content.startswith("⟦SYNOX-TOOL-") and tool_msg.content.rstrip().endswith("⟧")
    texts = bot.texts()
    assert texts[-2] == "記好了" and "note__add" in texts[-1] and "context 預算" in texts[-1]


def test_local_truncation_warning_does_not_fire_after_fit(make_bot, owner):
    """規格 2 的截斷偵測（llm/local.py）在 fit 之後不該觸發：送出去的估算在 context 之內、伺服器回合理的 prompt_eval_count。"""
    import json as _json

    from synox.llm import local

    sent = []

    class _Resp:
        status = 200

        def __init__(self, n):
            self._lines = [_json.dumps({"message": {"content": "好"}, "done": True, "prompt_eval_count": n,
                                        "eval_count": 1}).encode() + b"\n"]

        def readline(self):
            return self._lines.pop(0) if self._lines else b""

        def close(self):
            pass

    def opener(req, timeout):
        body = _json.loads(req.data.decode())
        sent.append(body)
        chars = sum(len(m["content"]) for m in body["messages"])
        return _Resp(chars // 2)                                          # 合理的數字（遠低於 context）

    probe = make_bot(["好"])
    loop = probe.app.extras["synox_agent"]
    probe.talk(owner, "嗨")
    first = loop.adapter.calls[0]
    size = context.total_tokens(first[0]) + context.estimate(str([(t.name, t.description, t.parameters)
                                                                  for t in first[1]])) + 1024 + 800
    adapter = local.LocalAdapter("m", context_size=size, opener=opener)
    bot = make_bot(adapter=adapter, llm={"kind": "local", "model": "m", "context_size": size, "max_tools": 0})
    loop = bot.app.extras["synox_agent"]
    _fill_history(loop, owner)
    bot.talk(owner, "嗨")
    assert len(sent[0]["messages"]) < 14                               # 有裁
    texts = bot.texts()
    assert "好" in texts and not any("AI 來源的提醒" in t for t in texts) and not adapter.last_warning
