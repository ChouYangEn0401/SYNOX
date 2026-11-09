"""
LLM adapter 的介面（spec §5）。adapter **只會聊天**：不拿 registry、不拿 Telegram api（invariant 2）；
授權、執行工具、核准卡都是 agent 的事。

    class ChatAdapter:
        name: str                  顯示用
        supports_tools: bool       False → agent 改用 textproto（JSON-in-text）
        chat(messages, tools=()) -> Reply
        probe() -> str | None      精靈的「測一下」：None＝好，否則一句人話的錯誤
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

SYSTEM, USER, ASSISTANT, TOOL = "system", "user", "assistant", "tool"


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})


@dataclass
class ToolCall:
    name: str
    args: dict = field(default_factory=dict)
    id: str = ""


@dataclass
class Message:
    role: str                                        # system | user | assistant | tool
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)    # assistant 要呼叫的工具（原生 tool-calling）
    tool_call_id: str = ""                           # role=tool：回的是哪一個呼叫
    name: str = ""                                   # role=tool：工具名


@dataclass
class Reply:
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    usage: Dict[str, int] = field(default_factory=dict)   # {"input": n, "output": n}


class LLMError(Exception):
    """叫不動 LLM；訊息是給人看的一句話。"""


class ChatAdapter:
    name: str = "adapter"
    kind: str = ""
    supports_tools: bool = False

    def chat(self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()) -> Reply:
        raise NotImplementedError

    def probe(self) -> Optional[str]:
        """真的打一句確認接得通。None＝好；否則一句人話。"""
        try:
            reply = self.chat([Message(USER, "請只回一個字：好")])
        except LLMError as e:
            return str(e)
        except Exception as e:                        # 測一下不該讓精靈當掉
            return f"測試失敗：{e}"
        if not (reply.text or reply.tool_calls):
            return "接通了，但 AI 回了空白。"
        return None


def http_error(status: int, body: str = "") -> str:
    """HTTP 狀態碼 → 一句人話（openai_compat、anthropic 共用）。"""
    hint = {
        400: "請求被拒（400）：模型名稱或參數不對",
        401: "金鑰不對（401）",
        403: "這把金鑰沒有權限（403）",
        404: "網址或模型名稱不對（404）",
        429: "用量超過上限或太頻繁（429），等一下再試或檢查額度",
    }.get(status, f"伺服器回了錯誤（{status}）")
    snippet = " ".join((body or "").split())[:160]
    return f"{hint}。" + (f"\n伺服器說：{snippet}" if snippet else "")
