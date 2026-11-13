"""
LLM adapter 的介面（spec §5）。adapter **只會聊天**：不拿 registry、不拿 Telegram api（invariant 2）；
授權、執行工具、核准卡都是 agent 的事。

    class ChatAdapter:
        name: str                  顯示用
        supports_tools: bool       False → agent 改用 textproto（JSON-in-text）
        supports_stop: bool        True → chat 收 stop=（停止詞，docs/adr/0010）；False → agent 不傳（不支援就不送）
        supports_vision: bool      True → Message.images 會照這個來源的格式送出（docs/adr/0021）；False → agent 不送圖
        check_vision() -> bool     有圖的那一輪才問（預設＝supports_vision）；本地 Ollama 的 auto 在這裡唯讀查 /api/show
        chat(messages, tools=(), *, stop=()) -> Reply
        probe() -> str | None      精靈的「測一下」：None＝好，否則一句人話的錯誤

Reply.text 一律是「給人看的字」：思考段（<think>…</think>）由 adapter 去掉（textproto.strip_think）；agent 也會再去一次。
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


@dataclass(frozen=True)
class ImagePart:
    """一張要給 AI 看的圖（docs/adr/0021）：位元組只在記憶體，不寫檔、不進 log（repr 只印格式與大小）。"""
    mime: str                                        # image/jpeg | image/png | image/webp | image/gif
    data: bytes = field(repr=False)

    def __repr__(self) -> str:
        return f"ImagePart({self.mime}, {len(self.data)} bytes)"

    def b64(self) -> str:
        import base64
        return base64.b64encode(self.data).decode("ascii")

    def data_uri(self) -> str:
        return f"data:{self.mime};base64,{self.b64()}"


@dataclass
class Message:
    # 圖片（VLM，docs/adr/0021）：images 只有 role=user 會有；各 adapter 的轉換函式各自處理，不把圖塞進 content。
    role: str                                       # system | user | assistant | tool
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)    # assistant 要呼叫的工具（原生 tool-calling）
    tool_call_id: str = ""                           # role=tool：回的是哪一個呼叫
    name: str = ""                                   # role=tool：工具名
    images: List[ImagePart] = field(default_factory=list)       # role=user：這一則附的圖（對話記憶裡永遠是空的）


@dataclass
class Reply:
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    usage: Dict[str, int] = field(default_factory=dict)   # {"input": n, "output": n}
    warnings: List[str] = field(default_factory=list)     # 給人看的提醒（例如本地模型的提示很可能被截斷）；不是錯誤


class LLMError(Exception):
    """叫不動 LLM；訊息是給人看的一句話。"""


class ChatAdapter:
    name: str = "adapter"
    kind: str = ""
    supports_tools: bool = False
    supports_stop: bool = False
    supports_vision: bool = False

    def check_vision(self) -> bool:
        """這個來源現在收不收得下圖（有圖的那一輪才問）。預設＝supports_vision；唯讀，不載入模型。"""
        return bool(self.supports_vision)

    def chat(self, messages: Sequence[Message], tools: Sequence[ToolSpec] = (), *, stop: Sequence[str] = ()) -> Reply:
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


def has_images(messages: Sequence[Message]) -> bool:
    return any(getattr(m, "images", None) for m in messages)


def no_vision(name: str) -> LLMError:
    """adapter 收到圖、自己卻不支援：明講，不偷偷丟掉圖（docs/adr/0021）。"""
    return LLMError(f"此來源不支援圖片（{name}）：圖片沒有送出。")


def http_error(status: int, body: str = "") -> str:
    """HTTP 狀態碼 → 一句人話（easy_llm 的四種來源共用）。"""
    hint = {
        400: "請求被拒（400）：模型名稱或參數不對",
        401: "金鑰不對（401）",
        403: "這把金鑰沒有權限（403）",
        404: "網址或模型名稱不對（404）",
        429: "用量超過上限或太頻繁（429），等一下再試或檢查額度",
    }.get(status, f"伺服器回了錯誤（{status}）")
    snippet = " ".join((body or "").split())[:160]
    return f"{hint}。" + (f"\n伺服器說：{snippet}" if snippet else "")
