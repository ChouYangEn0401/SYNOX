"""
這台電腦已登入的 Claude Code（走使用者自己的訂閱）：`claude -p --output-format json`。

- 沒有原生 tool-calling 給我們用 → supports_tools=False，agent 走文字協定（textproto.py）。
- 給 claude 的旗標：`--tools ""`（一個內建工具都不給）、`--setting-sources ""`（不吃使用者的 CLAUDE.md、hooks、
  記憶）、`--strict-mcp-config`（不載任何 MCP server）；工作目錄是 data/claude_workspace（空資料夾）。
  它能做的事只有「回一段文字」，要做事一律經 SYNOX 的工具（授權在 agent）。
- 跟 SDK invariant 10（外部程式一律經 JobRunner）的差別：adapter 不拿 app（invariant 2），所以這裡直接用
  subprocess.run（argv 陣列、不開視窗、有逾時）。見 docs/AGENT.md「跟 SDK 的差異」。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Optional, Sequence

from synox.llm.base import ASSISTANT, SYSTEM, TOOL, ChatAdapter, LLMError, Message, Reply, ToolSpec

NOT_FOUND = "這台電腦找不到 claude（Claude Code）。先安裝並登入 Claude Code，或改選其他 AI 來源。"


def find_claude() -> Optional[str]:
    return shutil.which("claude")


def flatten(messages: Sequence[Message]) -> str:
    """多輪訊息 → 一段文字（claude -p 一次只吃一個 prompt）。"""
    parts = []
    for m in messages:
        if m.role == SYSTEM:
            parts.append(f"［系統說明］\n{m.content}")
        elif m.role == ASSISTANT:
            parts.append(f"［助理］\n{m.content}")
        elif m.role == TOOL:
            parts.append(f"［工具 {m.name} 的結果］\n{m.content}")
        else:
            parts.append(f"［使用者］\n{m.content}")
    parts.append("［助理］")
    return "\n\n".join(parts)


class ClaudeCodeAdapter(ChatAdapter):
    kind = "claude_code"
    supports_tools = False

    def __init__(self, model: str = "", *, workdir: str = "", timeout: float = 180.0, runner=None, which=None):
        self.model = model
        self.workdir = workdir
        self.timeout = timeout
        self._run = runner or subprocess.run
        self._which = which or find_claude
        self.name = f"Claude Code（{model or '預設模型'}）"

    def argv(self, exe: str) -> list:
        argv = [exe, "-p", "--output-format", "json", "--tools", "", "--setting-sources", "", "--strict-mcp-config"]
        if self.model:
            argv += ["--model", self.model]
        return argv

    def chat(self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()) -> Reply:
        exe = self._which()
        if not exe:
            raise LLMError(NOT_FOUND)
        if self.workdir:
            os.makedirs(self.workdir, exist_ok=True)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            done = self._run(self.argv(exe), input=flatten(messages), capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=self.timeout,
                             cwd=self.workdir or None, creationflags=flags)
        except subprocess.TimeoutExpired:
            raise LLMError(f"Claude Code 超過 {int(self.timeout)} 秒沒回。")
        except OSError as e:
            raise LLMError(f"叫不起 claude：{e}")
        out = (done.stdout or "").strip()
        try:
            data = json.loads(out.splitlines()[-1]) if out else {}
        except ValueError:
            data = {}
        if done.returncode != 0 or data.get("is_error") or "result" not in data:
            detail = data.get("result") or (done.stderr or out or "").strip()[-200:]
            raise LLMError(f"Claude Code 回了錯誤：{detail or '（沒有訊息）'}。是不是還沒登入？")
        usage = data.get("usage") or {}
        return Reply(text=str(data.get("result") or ""), usage={"input": int(usage.get("input_tokens") or 0),
                                                                "output": int(usage.get("output_tokens") or 0)})

    def probe(self) -> Optional[str]:
        if not self._which():
            return NOT_FOUND
        return super().probe()
