"""停止詞（docs/adr/0010）、做不到的出口 system__cannot_do（0011）、同一個呼叫連續失敗與步數用完的總結（0012）。"""

import json

from conftest import enc_files

from synox.agent import claims, loop as loop_mod, tools as tools_mod
from synox.llm import local
from synox.llm.base import Message, USER


def _adapter(bot):
    return bot.app.extras["synox_agent"].adapter


# ── 停止詞 ───────────────────────────────────────────────────────────

def test_stop_words_native_and_text(make_bot, owner):
    bot = make_bot(["好"])
    bot.talk(owner, "嗨")
    assert _adapter(bot).stops == [loop_mod.NATIVE_STOP]
    bot = make_bot(["好"], supports_tools=False)
    bot.talk(owner, "嗨")
    assert _adapter(bot).stops == [loop_mod.TEXT_STOP] and loop_mod.TEXT_STOP == ("〔工具結果〕",)


def test_no_stop_words_when_thinking(make_bot, owner):
    bot = make_bot(["好"], llm={"kind": "fake", "think": True})
    bot.talk(owner, "嗨")
    assert _adapter(bot).stops == [()]


def test_adapters_without_stop_support_are_not_given_stop(make_bot, owner):
    from synox.llm.base import ChatAdapter, Reply

    class Old(ChatAdapter):                          # 舊的 adapter：chat 沒有 stop 參數
        supports_tools = True

        def chat(self, messages, tools=()):
            return Reply(text="好")

    bot = make_bot(adapter=Old())
    bot.talk(owner, "嗨")
    assert bot.last(owner) == "好"


class _Resp:
    def __init__(self, lines):
        self._lines = [json.dumps(x).encode() + b"\n" for x in lines]
        self.status = 200

    def readline(self):
        return self._lines.pop(0) if self._lines else b""

    def close(self):
        pass


def test_local_adapter_sends_stop_and_strips_think():
    sent = []

    def opener(req, timeout):
        sent.append(json.loads(req.data.decode()))
        return _Resp([{"message": {"content": "<think>想</think>好"}, "done": True, "prompt_eval_count": 1,
                       "eval_count": 1}])

    a = local.LocalAdapter("m", context_size=8192, opener=opener)
    reply = a.chat([Message(USER, "嗨")], stop=("〔工具結果〕",))
    assert sent[0]["options"]["stop"] == ["〔工具結果〕"] and reply.text == "好"

    def opener2(req, timeout):
        sent.append(json.loads(req.data.decode()))
        return _Resp([{"choices": [{"delta": {"content": "好"}, "finish_reason": "stop"}]}])

    b = local.LocalAdapter("m", server="vllm", opener=opener2)
    b._ctx_looked = True
    b.chat([Message(USER, "嗨")], stop=("<tool_response>",))
    assert sent[-1]["stop"] == ["<tool_response>"]


def test_easy_llm_does_not_claim_stop_support():
    from synox.llm.easy_llm import EasyLLMAdapter
    assert EasyLLMAdapter.supports_stop is False


# ── system__cannot_do ────────────────────────────────────────────────

def test_cannot_do_is_offered_in_both_modes(make_bot, owner):
    bot = make_bot(["好"])
    bot.talk(owner, "嗨")
    assert tools_mod.CANNOT_DO in [t.name for t in _adapter(bot).calls[0][1]]
    assert tools_mod.CANNOT_DO in _adapter(bot).calls[0][0][0].content           # 系統提示說了要用它
    bot = make_bot(["好"], supports_tools=False)
    bot.talk(owner, "嗨")
    assert f"- {tools_mod.CANNOT_DO}：" in _adapter(bot).calls[0][0][0].content      # 文字協定的工具說明


def test_cannot_do_ends_the_turn_and_does_nothing(make_bot, owner):
    token = "ghp_" + "a" * 36
    bot = make_bot([[{"tool": tools_mod.CANNOT_DO, "args": {"reason": f"沒有寄信的工具 {token}"}},
                     {"tool": "note__add", "args": {"text": "不該跑"}}]])
    bot.talk(owner, "幫我寄信")
    sent = bot.last(owner)
    assert sent.startswith("做不到：沒有寄信的工具") and token not in sent
    assert len(_adapter(bot).calls) == 1 and enc_files(bot) == []              # 同一則裡後面的呼叫沒有執行
    history = bot.app.extras["synox_agent"].history[owner]
    assert history[-1].content == sent


def test_cannot_do_reason_is_capped(make_bot, owner):
    bot = make_bot([{"tool": tools_mod.CANNOT_DO, "args": {"reason": "長" * 500}}])
    bot.talk(owner, "隨便")
    assert len(bot.last(owner)) <= len("做不到：") + loop_mod.CANNOT_DO_MAX + 1


def test_refuse_marker_counts_cannot_do():
    from synox.evals import checks
    assert "做不到" in checks.REFUSE_MARKERS


# ── 同一個呼叫連續失敗 ─────────────────────────────────────────────────

def test_same_failing_call_three_times_stops(make_bot, owner):
    bad = {"tool": "money__add", "args": {"amount": "abc", "category": "x"}}
    bot = make_bot([bad, bad, bad, "不該到這裡"])
    bot.talk(owner, "記帳")
    calls = _adapter(bot).calls
    assert loop_mod.REPEAT_HINT not in calls[1][0][-1].content                  # 第 1 次失敗：沒有提示
    assert calls[2][0][-1].content.endswith(loop_mod.REPEAT_HINT)              # 第 2 次：附一行
    assert len(calls) == 3 and bot.last(owner) == loop_mod.REPEAT_STOP


def test_different_failing_calls_are_not_repeats(make_bot, owner):
    bot = make_bot([{"tool": "money__add", "args": {"amount": "a", "category": "x"}},
                    {"tool": "money__add", "args": {"amount": "b", "category": "x"}},
                    {"tool": "money__add", "args": {"amount": "c", "category": "x"}}, "算了"])
    bot.talk(owner, "記帳")
    assert bot.last(owner) == "算了"
    assert all(loop_mod.REPEAT_HINT not in messages[-1].content for messages, _tools in _adapter(bot).calls)


def test_success_in_between_resets_the_count(make_bot, owner):
    bad = {"tool": "money__add", "args": {"amount": "abc", "category": "x"}}
    bot = make_bot([bad, bad, {"tool": "money__month", "args": {}}, bad, "好"])
    bot.talk(owner, "記帳")
    assert bot.last(owner) == "好"


# ── 步數用完的總結 ─────────────────────────────────────────────────────

LIMIT = {"kind": "fake", "max_steps": 3, "summarize_on_limit": "on", "completion_guard": "on"}


def test_step_limit_summary(make_bot, owner):
    bot = make_bot([{"tool": "money__month", "args": {}}] * 3 + ["查了三次這個月的支出，還沒整理出分類。"], llm=LIMIT)
    bot.talk(owner, "一直查")
    calls = _adapter(bot).calls
    assert len(calls) == 4 and calls[3][1] == [] and calls[3][0][-1].content == loop_mod.SUMMARY_ASK
    assert bot.last(owner) == "（做了 3 步還沒做完，先停在這裡。）查了三次這個月的支出，還沒整理出分類。"


def test_step_limit_summary_claim_is_gated(make_bot, owner):
    bot = make_bot([{"tool": "money__month", "args": {}}] * 3 + ["都完成了，已記下所有支出。"], llm=LIMIT)
    bot.talk(owner, "一直查")
    sent = bot.last(owner)
    assert sent.startswith("（做了 3 步還沒做完") and "沒有執行" in sent and "已記下所有支出" in sent


def test_step_limit_without_summary_is_unchanged(make_bot, owner):
    bot = make_bot([{"tool": "money__month", "args": {}}] * 10, raw={"llm": {"kind": "fake", "max_steps": 3}})
    bot.talk(owner, "一直查")
    assert bot.last(owner) == "（做了 3 步還沒做完，先停在這裡。可以換個說法再試。）"
    assert len(_adapter(bot).calls) == 3


def test_step_limit_summary_falls_back_when_empty(make_bot, owner):
    bot = make_bot([{"tool": "money__month", "args": {}}] * 3 + [""], llm=LIMIT)
    bot.talk(owner, "一直查")
    assert bot.last(owner) == "（做了 3 步還沒做完，先停在這裡。可以換個說法再試。）"


def test_doctor_mentions_the_guard(tmp_path):
    from synox import doctor
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": 1, "data_dir": str(tmp_path / "data"), "vault": {"mode": "file"},
                               "llm": {"kind": "fake"}}), encoding="utf-8")
    lines = []
    doctor.run(offline=True, config_path=str(cfg), out=lines.append)
    assert any("完成宣稱檢查" in line for line in lines)
    assert claims.doctor_line({"completion_guard": "off"}, object()).startswith("完成宣稱檢查（llm.completion_guard=off）：關")
