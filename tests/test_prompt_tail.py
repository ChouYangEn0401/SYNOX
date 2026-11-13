"""系統提示尾端的「本輪規則」＋時間放最後一行（docs/adr/0017）、多步覆誦目標（0018）、Qwen3 不思考取樣參數（0019）。
預設只對本地／弱來源；雲端（這裡的 fake）的提示一個字都不變。全部用假 adapter／假 opener，不載入模型。"""

import json
from datetime import datetime

import pytest
from isdtelekit.host.config import ConfigError

from synox.agent import delimit
from synox.agent import loop as loop_mod
from synox.agent import tools as tools_mod
from synox.agent.room import MSG_TAG, RoomAgent, room_message
from synox.config import SynoxConfig
from synox.llm import local
from synox.llm.base import SYSTEM, TOOL, USER, Message
from synox.llm.factory import make_adapter

TAIL = {"kind": "fake", "prompt_tail": "on"}


def _prompt(bot, owner, nonce):
    loop = bot.app.extras["synox_agent"]
    user = bot.app.users.get_or_create(owner)
    tools = loop.tools_for(user, owner) + [tools_mod.cannot_do_spec()]
    return loop, loop.system_prompt([], tools, True, user, nonce), tools


def test_default_cloud_prompt_is_unchanged(make_bot, owner):
    bot = make_bot(["好"])
    loop, head, _tools = _prompt(bot, owner, "abcd1234")
    lines = head.split("\n")
    assert lines[3] == delimit.prompt_line("abcd1234") and lines[4].startswith("現在時間：")
    assert not loop.tail_on() and loop_mod.TAIL_HEAD not in head
    bot.talk(owner, "嗨")
    sent = loop.adapter.calls[0][0][0].content
    assert loop_mod.TAIL_HEAD not in sent


def test_tail_rules_last_and_time_on_the_last_line(make_bot, owner):
    bot = make_bot(["好"], llm=TAIL)
    bot.talk(owner, "嗨")
    loop = bot.app.extras["synox_agent"]
    system = loop.adapter.calls[0][0][0]
    assert system.role == SYSTEM
    tail = system.content.rsplit("\n\n", 1)[1]
    assert tail.startswith(loop_mod.TAIL_HEAD)
    assert system.content.split("\n")[-1].startswith("- 現在時間：")
    assert tools_mod.CANNOT_DO in tail and "沒有呼叫工具，就什麼都沒做" in tail and "工具失敗就照實說失敗" in tail
    assert tail.count("SYNOX-TOOL-") == 2 == system.content.count("SYNOX-TOOL-")       # 這一輪的分隔符只在尾端


def test_head_is_identical_across_turns(make_bot, owner):
    bot = make_bot(["好"], llm=TAIL)
    _loop, first, tools = _prompt(bot, owner, "aaaa1111")
    _loop, second, _ = _prompt(bot, owner, "bbbb2222")
    assert first == second                                         # 開頭整段沒有 nonce、沒有時間：prefix cache 命中
    assert "現在時間" not in first and "SYNOX-TOOL" not in first
    a = loop_mod.tail_rules(tools, "aaaa1111", datetime(2026, 11, 13, 14, 5))
    b = loop_mod.tail_rules(tools, "aaaa1111", datetime(2026, 11, 13, 14, 5))
    assert a == b and a.split("\n")[-1] == "- 現在時間：2026-11-13 14:05（週五）。"


def test_tail_without_tools_has_only_the_time():
    text = loop_mod.tail_rules([], "", datetime(2026, 11, 13, 14, 5))
    assert text == loop_mod.TAIL_HEAD + "\n- 現在時間：2026-11-13 14:05（週五）。"


def test_auto_follows_the_source(make_bot, owner):
    class _Local:
        kind = "local"

    bot = make_bot(["好"])
    loop = bot.app.extras["synox_agent"]
    loop.llm = {}
    real = loop.adapter
    loop.adapter = _Local()
    assert loop.tail_on()
    loop.adapter = real
    assert not loop.tail_on()
    loop.llm = {"prompt_tail": "off"}
    loop.adapter = _Local()
    assert not loop.tail_on()


def test_config_checks_prompt_tail():
    cfg = SynoxConfig.from_dict({"owner_id": 1, "llm": {"kind": "fake", "prompt_tail": True}}, require_token=False)
    assert cfg.llm["prompt_tail"] == "on"
    with pytest.raises(ConfigError):
        SynoxConfig.from_dict({"owner_id": 1, "llm": {"kind": "fake", "prompt_tail": "sometimes"}}, require_token=False)


# ── 覆誦 ─────────────────────────────────────────────────────────────

LONG = "幫我把下週要準備的東西都記下來：" + "雨傘、" * 40


def test_recite_only_from_the_second_step(make_bot, owner):
    script = [{"tool": "note__add", "args": {"text": "秘密參數123"}}, {"tool": "note__list", "args": {}}, "好了"]
    bot = make_bot(script, llm=TAIL)
    bot.talk(owner, LONG)
    loop = bot.app.extras["synox_agent"]
    tool_msgs = [m for m in loop.adapter.calls[2][0] if m.role == TOOL]
    assert len(tool_msgs) == 2
    assert "（目標：" not in tool_msgs[0].content                          # 第一步不覆誦
    line = tool_msgs[1].content.split("\n")[-1]
    assert line.startswith("（目標：幫我把下週要準備的東西都記下來：") and "…；做完就回答，做不到就說）" in line
    assert "秘密參數" not in line and len(line) < 120


def test_no_recite_by_default(make_bot, owner):
    script = [{"tool": "note__add", "args": {"text": "x"}}, {"tool": "note__list", "args": {}}, "好了"]
    bot = make_bot(script)
    bot.talk(owner, "記一下")
    loop = bot.app.extras["synox_agent"]
    assert not any("（目標：" in m.content for m in loop.adapter.calls[2][0])


def test_text_protocol_recites_too(make_bot, owner):
    script = [{"tool": "note__add", "args": {"text": "x"}}, {"tool": "note__list", "args": {}}, "好了"]
    bot = make_bot(script, llm=TAIL, supports_tools=False)
    bot.talk(owner, "記一下然後列出來")
    loop = bot.app.extras["synox_agent"]
    results = [m for m in loop.adapter.calls[2][0] if m.role == USER and m.content.startswith("〔工具結果〕")]
    assert len(results) == 2 and results[1].content.endswith(loop_mod.recite_line("記一下然後列出來"))


def test_room_goal_strips_label_and_markers():
    said = room_message("小明", "幫我查天氣", (), "n0nce123")
    agent = RoomAgent.__new__(RoomAgent)
    assert agent.goal_of(said) == "幫我查天氣"
    assert MSG_TAG not in loop_mod.recite_line(agent.goal_of(said))


# ── Qwen3 不思考取樣參數（只有 kind=local 的 ollama）────────────────────────────

class _Resp:
    status = 200

    def __init__(self, obj):
        self._lines = [json.dumps(obj).encode() + b"\n"]

    def readline(self):
        return self._lines.pop(0) if self._lines else b""

    def close(self):
        pass


def _send(adapter_kw, server="ollama"):
    sent = []

    def opener(req, timeout):
        sent.append(json.loads(req.data.decode()))
        if server == "ollama":
            return _Resp({"message": {"content": "好"}, "done": True, "prompt_eval_count": 1, "eval_count": 1})
        return _Resp({"choices": [{"delta": {"content": "好"}, "finish_reason": "stop"}]})

    a = local.LocalAdapter(server=server, context_size=8192, opener=opener, **adapter_kw)
    a._ctx_looked = True
    a.chat([Message(USER, "嗨")])
    return sent[0]


def test_qwen3_gets_the_no_think_preset_by_default():
    opts = _send({"model": "qwen3:8b"})["options"]
    assert {k: opts[k] for k in local.QWEN3_NO_THINK} == local.QWEN3_NO_THINK
    assert opts["num_ctx"] == 8192 and opts["num_predict"] == 1024


def test_other_models_and_off_get_server_defaults():
    assert set(_send({"model": "llama3.1:8b"})["options"]) == {"num_ctx", "num_predict"}
    assert set(_send({"model": "qwen3:8b", "sampling": "off"})["options"]) == {"num_ctx", "num_predict"}
    assert _send({"model": "llama3.1:8b", "sampling": "qwen3"})["options"]["top_k"] == 20


def test_options_override_and_openai_servers_untouched():
    opts = _send({"model": "qwen3:8b", "options": {"temperature": 0.5, "repeat_penalty": 1.05}})["options"]
    assert opts["temperature"] == 0.5 and opts["repeat_penalty"] == 1.05 and opts["top_p"] == 0.8
    body = _send({"model": "qwen3:8b", "options": {"temperature": 0.5}}, server="vllm")
    assert not any(k in body for k in ("temperature", "top_p", "top_k", "min_p", "options"))


def test_sampling_and_options_are_checked_and_reach_the_adapter():
    llm = {"kind": "local", "model": "qwen3:8b", "sampling": "QWEN3", "options": {"temperature": 0.6}}
    cfg = SynoxConfig.from_dict({"owner_id": 1, "llm": llm}, require_token=False)
    assert cfg.llm["sampling"] == "qwen3" and cfg.llm["options"] == {"temperature": 0.6}
    adapter = make_adapter(cfg)
    assert adapter.sampling == "qwen3" and adapter.options == {"temperature": 0.6}
    for bad in ({"sampling": "hot"}, {"options": {"num_ctx": 4096}}, {"options": {"Temp": 1}},
                {"options": {"temperature": [1]}}, {"options": "x"}):
        with pytest.raises(ConfigError):
            SynoxConfig.from_dict({"owner_id": 1, "llm": {"kind": "local", "model": "m", **bad}}, require_token=False)


def test_harness_doctor_line():
    from synox.agent import auto

    class _A:
        def __init__(self, kind):
            self.kind = kind

    cloud = auto.doctor_line({}, _A("openai"))
    assert "每輪工具上限 不限" in cloud and "不裁" in cloud and "本輪規則與覆誦 關" in cloud
    mine = auto.doctor_line({"context_size": 8192}, _A("local"))
    assert "上限 12" in mine and "8192" in mine and "3000 字" in mine and "本輪規則與覆誦 開" in mine
