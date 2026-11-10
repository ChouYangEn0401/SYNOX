# -*- coding: utf-8 -*-
"""SDK P3「確認來回」：工具執行中回 needs_confirm → 核准卡 → 按 ✅ 用同一組參數重跑（SYNOX 驗過一次性憑證才給
SYNOX_CONFIRMED=1）→ 工具真的做。憑證單次、過期、參數被改、別人、❌ 取消、人打字與 AI 兩條路、與 commands[].confirm 並存、
不能從環境變數或 pack.json 偽造、synox-sdk run --confirmed、MCP 模式的表達。子程序都是本機 Python，不連網、不開埠。"""
import io
import json
import os
import time

from conftest import OWNER_ID

from synox import sdk
from synox.packs import confirm as tc
from synox.sdk import author

TOOL = r'''"""確認來回的示範工具。"""
from synox_sdk import Confirm, confirmed, context, serve, tool


@tool("WRITE")
def purge(days: int):
    """刪掉舊的。"""
    key = f"d{days}"
    if not confirmed(key):
        raise Confirm(f"要刪 3 筆（{days} 天前的）", token=key)
    ctx = context()
    return f"刪了 3 筆 token={ctx.confirm_token} confirmed={ctx.confirmed}"


@tool("WRITE")
def nag():
    """一直要確認。"""
    raise Confirm("再確認一次")


@tool("WRITE", confirm=True)
def send(text: str):
    """送出去（AI 要先問人）。"""
    if not confirmed():
        raise Confirm(f"真的要送 {text}？")
    return f"送了 {text}"


if __name__ == "__main__":
    serve()
'''


def _pack(tmp_path, env=None):
    folder = tmp_path / "packs" / "demo"
    folder.mkdir(parents=True)
    (folder / "tool.py").write_text(TOOL, encoding="utf-8")
    sdk.write_single_file(str(folder / "synox_sdk.py"))
    sdk.init_from(str(folder / "tool.py"), "demo", "示範")
    if env:
        raw = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
        raw["cli"]["env"] = env
        (folder / "pack.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return folder


def _bot(make_bot, tmp_path, script=None, env=None):
    folder = _pack(tmp_path, env)
    bot = make_bot(script, pack_dirs=(str(folder.parent),))
    assert bot.app.extras["synox_pack_report"].items[0].status == "loaded"
    return bot


def _buttons(bot, kind):
    return [b for b in bot.buttons(OWNER_ID) if b.startswith(f"agent_ok:{kind}:")]


def _joined(bot):
    return "\n".join(bot.texts(OWNER_ID))


# ── 憑證本身 ───────────────────────────────────────────────────────────

class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_grant_single_use_bound_and_expiring():
    clock = Clock()
    g = tc.ConfirmGrants(clock)
    values = {"days": "7"}
    gid = g.issue("demo", "purge", values, 1, "d7", ttl=60)
    assert g.redeem(gid, "demo", "purge", values, 1) == "d7"
    assert g.redeem(gid, "demo", "purge", values, 1) is None              # 單次
    gid = g.issue("demo", "purge", values, 1, "d7", ttl=60)
    assert g.redeem(gid, "demo", "purge", {"days": "70"}, 1) is None       # 參數被改：不行，而且作廢
    assert g.redeem(gid, "demo", "purge", values, 1) is None
    for other in (("demo", "nag", values, 1), ("other", "purge", values, 1), ("demo", "purge", values, 2)):
        gid = g.issue("demo", "purge", values, 1, "", ttl=60)
        assert g.redeem(gid, *other) is None                               # 別的指令、別的 pack、別人
    gid = g.issue("demo", "purge", values, 1, "", ttl=60)
    clock.now += 61
    assert g.redeem(gid, "demo", "purge", values, 1) is None              # 過期
    gid = g.issue("demo", "purge", values, 1, "", ttl=60)
    g.discard(gid)                                                         # ❌
    assert g.redeem(gid, "demo", "purge", values, 1) is None
    assert g.redeem("nope", "demo", "purge", values, 1) is None


def test_env_and_token_rules():
    assert tc.env_for(None) == {"SYNOX_CONFIRMED": "0", "SYNOX_CONFIRM_TOKEN": ""}
    assert tc.env_for("d7") == {"SYNOX_CONFIRMED": "1", "SYNOX_CONFIRM_TOKEN": "d7"}
    assert tc.tool_token({"confirm_token": "abc-1.2:3_x"}) == "abc-1.2:3_x"
    for bad in ("有中文", "a b", "x\n", "", "a" * 129, 5, None):
        assert tc.tool_token({"confirm_token": bad}) == ""
    assert tc.summary_of({"summary": "x" * 900}).endswith("…") and len(tc.summary_of({"summary": "x" * 900})) == 500


# ── SDK 端：confirmed()、context() ─────────────────────────────────────

def test_confirmed_reads_synox_env(monkeypatch):
    monkeypatch.delenv("SYNOX_CONFIRMED", raising=False)
    monkeypatch.delenv("SYNOX_CONFIRM_TOKEN", raising=False)
    assert author.confirmed() is False and author.context().confirmed is False
    monkeypatch.setenv("SYNOX_CONFIRM_TOKEN", "k")                         # 只有 token、沒有 SYNOX_CONFIRMED=1：不算
    assert author.confirmed() is False and author.context().confirm_token == ""
    monkeypatch.setenv("SYNOX_CONFIRMED", "1")
    assert author.confirmed() and author.confirmed("k") and not author.confirmed("other")
    ctx = author.context()
    assert ctx.confirmed is True and ctx.confirm_token == "k"


def test_mcp_confirm_expression_and_meta(monkeypatch):
    calls = []

    @author.tool("WRITE", name="purge")
    def purge(days: int):
        """刪掉舊的。"""
        calls.append(author.confirmed("d%d" % days))
        if not author.confirmed("d%d" % days):
            raise author.Confirm("要刪 3 筆", token="d%d" % days)
        return "刪了"

    monkeypatch.setenv("SYNOX_CONFIRMED", "1")                             # MCP 模式不看環境變數
    monkeypatch.setenv("SYNOX_CONFIRM_TOKEN", "d7")
    specs = {s["name"]: s for s in author.specs_for([purge])}
    info = {"name": "t", "version": "1"}
    ask = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "purge", "arguments": {"days": 7}}}
    res = author._mcp_handle(ask, specs, info)["result"]
    assert res["isError"] is False and "還沒做" in res["content"][0]["text"]
    assert res["structuredContent"] == {"needs_confirm": True, "summary": "要刪 3 筆", "confirm_token": "d7"}
    again = json.loads(json.dumps(ask))
    again["params"]["_meta"] = {"synox/confirm_token": "d7"}
    res = author._mcp_handle(again, specs, info)["result"]
    assert res["isError"] is False and res["content"][0]["text"] == "刪了" and "structuredContent" not in res
    again["params"]["_meta"] = {"synox/confirm_token": "d8"}                # 對不上的 token：不算
    assert "structuredContent" in author._mcp_handle(again, specs, info)["result"]
    assert calls == [False, True, False]
    assert author._MCP_CONFIRM is None                                    # 呼叫結束就清掉


# ── 人自己打字 ─────────────────────────────────────────────────────────

def test_typed_needs_confirm_then_rerun_same_args(make_bot, tmp_path):
    bot = _bot(make_bot, tmp_path)
    bot.say(OWNER_ID, "/demo_purge 7")
    bot.app.tasks.wait(20)
    card = bot.last(OWNER_ID)
    assert "要你確認才會做" in card and "要刪 3 筆（7 天前的）" in card and "days=7" in card
    assert "刪了" not in _joined(bot)                                      # 還沒做
    go = _buttons(bot, "go")
    assert go and _buttons(bot, "no")
    bot.press_and_wait(OWNER_ID, go[0])
    assert "刪了 3 筆 token=d7 confirmed=True" in bot.last(OWNER_ID)       # 同一組參數重跑、token 原樣送回
    bot.press_and_wait(OWNER_ID, go[0])                                    # 同一張卡只能用一次
    assert "過期" in bot.last(OWNER_ID)
    assert len(tc.grants_of(bot.app)) == 0


def test_typed_cancel(make_bot, tmp_path):
    bot = _bot(make_bot, tmp_path)
    bot.say(OWNER_ID, "/demo_purge 7")
    bot.app.tasks.wait(20)
    bot.press_and_wait(OWNER_ID, _buttons(bot, "no")[0])
    assert "不執行" in bot.last(OWNER_ID) and "刪了" not in _joined(bot)
    assert len(tc.grants_of(bot.app)) == 0                                 # ❌ 憑證作廢


def test_expired_grant_does_not_run(make_bot, tmp_path):
    bot = _bot(make_bot, tmp_path)
    bot.say(OWNER_ID, "/demo_purge 7")
    bot.app.tasks.wait(20)
    tc.grants_of(bot.app)._clock = lambda: time.time() + 10_000            # 憑證過期（卡片本身還沒）
    bot.press_and_wait(OWNER_ID, _buttons(bot, "go")[0])
    assert bot.last(OWNER_ID) == tc.EXPIRED and "刪了" not in _joined(bot)


def test_confirm_cannot_be_forged_from_env_or_pack_json(make_bot, tmp_path, monkeypatch):
    monkeypatch.setenv("SYNOX_CONFIRMED", "1")                             # SYNOX 自己的環境帶了也沒用
    monkeypatch.setenv("SYNOX_CONFIRM_TOKEN", "d7")
    bot = _bot(make_bot, tmp_path, env={"SYNOX_CONFIRMED": "1", "SYNOX_CONFIRM_TOKEN": "d7"})   # pack 自己寫也沒用
    bot.say(OWNER_ID, "/demo_purge 7")
    bot.app.tasks.wait(20)
    assert "要你確認才會做" in bot.last(OWNER_ID) and "刪了" not in _joined(bot)


def test_tool_that_asks_again_stops(make_bot, tmp_path):
    bot = _bot(make_bot, tmp_path)
    bot.say(OWNER_ID, "/demo_nag")
    bot.app.tasks.wait(20)
    bot.press_and_wait(OWNER_ID, _buttons(bot, "go")[0])
    assert bot.last(OWNER_ID) == tc.AGAIN.format(name="nag")
    assert not _buttons(bot, "go") or len([t for t in bot.texts(OWNER_ID) if "要你確認才會做" in t]) == 1


def test_tampered_args_cannot_reuse_grant(make_bot, tmp_path):
    bot = _bot(make_bot, tmp_path)
    bot.say(OWNER_ID, "/demo_purge 7")
    bot.app.tasks.wait(20)
    token = _buttons(bot, "go")[0].split(":")[2]
    desk = bot.app.extras["synox_approval_desk"]
    payload = desk.pending._items[token][0]
    # 重跑要用的那組參數在中間被改掉（同一張憑證、不同參數）：憑證對不上 → 不執行
    stored = [c.cell_contents for c in payload["rerun"].__closure__ if isinstance(c.cell_contents, dict)]
    assert stored == [{"days": "7"}]
    stored[0]["days"] = "70"
    bot.press_and_wait(OWNER_ID, _buttons(bot, "go")[0])
    assert bot.last(OWNER_ID) == tc.EXPIRED and "刪了" not in _joined(bot)
    assert len(tc.grants_of(bot.app)) == 0                                 # 對不上的憑證也作廢


# ── 經 AI ──────────────────────────────────────────────────────────────

def test_ai_call_needs_confirm_ends_turn_and_card_goes_to_user(make_bot, tmp_path):
    bot = _bot(make_bot, tmp_path, script=[{"tool": "demo__purge", "args": {"days": "7"}}, "不該走到這裡"])
    bot.talk(OWNER_ID, "把 7 天前的刪掉")
    adapter = bot.app.extras["synox_agent"].adapter
    assert len(adapter.calls) == 1                                         # 卡出去了，這一輪停住
    assert "要刪 3 筆（7 天前的）" in bot.last(OWNER_ID) and "不該走到這裡" not in _joined(bot)
    bot.press_and_wait(OWNER_ID, _buttons(bot, "go")[0])
    assert "刪了 3 筆 token=d7 confirmed=True" in bot.last(OWNER_ID)       # 結果直接給人
    history = bot.app.extras["synox_agent"].history
    assert any("已執行" in m.content for h in history.values() for m in h)


def test_coexists_with_commands_confirm(make_bot, tmp_path):
    bot = _bot(make_bot, tmp_path, script=[{"tool": "demo__send", "args": {"text": "hi"}}])
    bot.talk(OWNER_ID, "幫我送 hi")
    assert "AI 想執行" in bot.last(OWNER_ID)                               # commands[].confirm：AI 呼叫前的卡
    bot.press_and_wait(OWNER_ID, _buttons(bot, "go")[0])
    assert "要你確認才會做" in bot.last(OWNER_ID) and "真的要送 hi" in bot.last(OWNER_ID)   # 工具自己的卡
    bot.press_and_wait(OWNER_ID, _buttons(bot, "go")[-1])
    assert "送了 hi" in bot.last(OWNER_ID)


# ── synox-sdk run --confirmed ──────────────────────────────────────────

def test_run_command_simulates_confirm(tmp_path):
    folder = _pack(tmp_path)
    out = io.StringIO()
    assert sdk.run_command(str(folder), "purge", ["7"], data_dir=str(tmp_path / "d"), out=out) == 0
    text = out.getvalue()
    assert "SYNOX 會出確認卡：要刪 3 筆" in text and "--confirmed" in text and "刪了" not in text
    out = io.StringIO()
    assert sdk.run_command(str(folder), "purge", ["7"], data_dir=str(tmp_path / "d"), confirmed=True, out=out) == 0
    assert "SYNOX 會回：刪了 3 筆 token=d7 confirmed=True" in out.getvalue()
    out = io.StringIO()
    assert sdk.run_command(str(folder), "nag", [], data_dir=str(tmp_path / "d"), confirmed=True, out=out) == 1
    assert "又要求確認" in out.getvalue()
    assert os.path.isfile(folder / "pack.json")
