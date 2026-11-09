"""
測試與 demo 用的假 AI：不連網、不花錢。

    FakeAdapter([{"tool": "money__add", "args": {"amount": "80", "category": "咖啡"}}, "記好了"])

劇本（script）一項一次 chat：
  - 字串                         → 一般文字回覆
  - {"tool": 名稱, "args": {…}}   → 一個工具呼叫
  - [ {…}, {…} ]                 → 同一次回覆裡好幾個工具呼叫
  - Reply                        → 原樣回
  - callable(messages, tools)    → 它回的 Reply
劇本用完回「（劇本結束）」。calls 記下每次收到的 (messages, tools)，測試可以檢查 AI 看到了什麼。

script=None 是「示範模式」（config 的 llm.kind = "fake"）：認得幾句固定的話，讓 Console.bat 不接真的 AI
也能走完「人話 → 工具 → 核准卡」：
  「記一筆 80 元咖啡」→ money__add　「把筆記全部刪掉」→ note__clear　「記住 買牛奶」→ note__add
  「08:00 提醒我 吃藥」→ remind__add
"""

from __future__ import annotations

import re
from typing import Callable, List, Optional, Sequence, Union

from synox.llm.base import TOOL, USER, ChatAdapter, Message, Reply, ToolCall, ToolSpec

Step = Union[str, dict, list, Reply, Callable]


class FakeAdapter(ChatAdapter):
    kind = "fake"

    def __init__(self, script: Optional[Sequence[Step]] = None, *, supports_tools: bool = True,
                 usage: Optional[dict] = None):
        self.script: Optional[List[Step]] = list(script) if script is not None else None
        self.supports_tools = supports_tools
        self.usage = usage if usage is not None else {"input": 10, "output": 5}
        self.calls: List[tuple] = []
        self.name = "假 AI（劇本）" if script is not None else "假 AI（示範模式）"

    def chat(self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()) -> Reply:
        self.calls.append((list(messages), list(tools)))
        if self.script is None:
            reply = demo_reply(messages, tools)
        elif not self.script:
            reply = Reply(text="（劇本結束）")
        else:
            reply = self._step(self.script.pop(0), messages, tools)
        if not reply.usage:
            reply.usage = dict(self.usage)
        return reply

    def _step(self, step: Step, messages, tools) -> Reply:
        if isinstance(step, Reply):
            return step
        if callable(step):
            return step(messages, tools)
        if isinstance(step, str):
            return Reply(text=step)
        steps = step if isinstance(step, list) else [step]
        calls = [ToolCall(name=s["tool"], args=dict(s.get("args") or {}), id=f"fake-{len(self.calls)}-{i}")
                 for i, s in enumerate(steps)]
        if not self.supports_tools:                    # 文字協定：把呼叫寫成 JSON 文字，交給 textproto 解析
            import json
            return Reply(text=json.dumps({"tool": calls[0].name, "args": calls[0].args}, ensure_ascii=False))
        return Reply(tool_calls=calls)

    def probe(self) -> Optional[str]:
        return None


# ── 示範模式 ─────────────────────────────────────────────────────────

_MONEY = re.compile(r"記(?:一筆|帳)?\s*(\d+(?:\.\d+)?)\s*(?:元|塊)?\s*(.+)")
_REMIND = re.compile(r"(\d{1,2}:\d{2}).*?提醒我?\s*(.+)")
_NOTE = re.compile(r"(?:記住|筆記)[：:\s]\s*(.+)")


def demo_reply(messages: Sequence[Message], tools: Sequence[ToolSpec]) -> Reply:
    last = messages[-1] if messages else Message(USER, "")
    if last.role == TOOL or last.content.startswith("〔工具結果〕"):
        result = last.content.split("\n", 1)[-1] if last.role != TOOL else last.content
        return Reply(text=f"好了，{result.strip() or '做完了'}")
    text = last.content.strip()
    names = {t.name for t in tools}
    if "筆記" in text and any(w in text for w in ("全部刪", "全刪", "清空", "刪光")):
        return _call("note__clear", {}, names)
    m = _MONEY.search(text)
    if m:
        return _call("money__add", {"amount": m.group(1), "category": m.group(2).strip()}, names)
    m = _REMIND.search(text)
    if m:
        return _call("remind__add", {"time": m.group(1), "text": m.group(2).strip()}, names)
    m = _NOTE.search(text)
    if m:
        return _call("note__add", {"text": m.group(1).strip()}, names)
    return Reply(text="（示範用的假 AI，沒有真的接上 AI）我只聽得懂：「記一筆 80 元咖啡」「記住 買牛奶」"
                      "「08:00 提醒我 吃藥」「把筆記全部刪掉」。要真的 AI，重跑 Setup.bat 選一個 AI 來源。")


def _call(name: str, args: dict, available) -> Reply:
    if available and name not in available:
        return Reply(text=f"（示範 AI）想用 {name}，但這個工具現在沒有開。")
    return Reply(tool_calls=[ToolCall(name=name, args=args, id="demo-1")])
