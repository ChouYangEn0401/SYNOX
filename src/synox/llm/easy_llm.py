"""
用 API 金鑰的 AI 來源：都經創始維護者的套件 ntu_easy_llm（0.5.0 起的 `ntu_easy_llm.agent`）。

    {"kind": "openai",        "api_key": "vault:llm_api_key", "model": "gpt-4.1-mini"}
    {"kind": "anthropic",     "api_key": "vault:llm_api_key", "model": "claude-sonnet-4-5"}
    {"kind": "gemini",        "api_key": "vault:llm_api_key", "model": "gemini-2.5-flash"}
    {"kind": "openai_compat", "base_url": "http://localhost:11434/v1", "api_key": "", "model": "llama3.1",
     "tools": true}             公司閘道、Ollama；閘道沒開 tool-calling 就寫 false → agent 走文字協定（textproto）
    base_url 對 openai／anthropic／gemini 是可選的覆寫。

- ntu_easy_llm 是選用相依（pyproject 的 `llm` 組）：**用到的時候才 import**，沒裝就丟 LLMError 說怎麼裝，
  其他功能（指令、Claude Code、假 AI）不受影響。
- adapter 只會聊天（invariant 2）：這裡只做 SYNOX 的 Message／ToolSpec／Reply 跟 ntu_easy_llm 的格式互轉，
  以及把它的錯誤（狀態碼、連不到、格式不對）翻成一句中文。
- session：測試傳一個假的 requests 風格物件（不連網），原樣交給 ntu_easy_llm.agent.chat。
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from synox.llm.base import ChatAdapter, LLMError, Message, Reply, ToolCall, ToolSpec, http_error

INSTALL_HINT = ("在 SYNOX 資料夾跑 `.venv\\Scripts\\python.exe -m pip install -e .[llm]`（裝官方 release 的 0.5.0 wheel），"
                "或改選 Claude Code／本地模型／先不用 AI。")
MISSING = "還沒安裝 ntu_easy_llm：用 API 金鑰的 AI（OpenAI、Anthropic、Gemini、相容端點）要靠它。" + INSTALL_HINT
MIN_VERSION = (0, 5, 0)

# kind → (ntu_easy_llm 的 provider, 顯示名稱)
PROVIDERS = {
    "openai": ("openai", "OpenAI"),
    "anthropic": ("anthropic", "Anthropic"),
    "gemini": ("gemini", "Gemini"),
    "openai_compat": ("openai_compatible", "OpenAI 相容"),
}


def load_agent_module():
    """import ntu_easy_llm.agent；沒裝或太舊丟 LLMError（中文、說怎麼裝）。"""
    try:
        import ntu_easy_llm
        from ntu_easy_llm import agent
    except ImportError:
        raise LLMError(MISSING)
    version = getattr(ntu_easy_llm, "__version__", "0")
    try:
        parts = tuple(int(p) for p in version.split(".")[:3])
    except ValueError:
        parts = MIN_VERSION
    if parts < MIN_VERSION:
        raise LLMError(f"ntu_easy_llm 版本太舊（{version}），要 0.5.0 以上才有工具呼叫。" + INSTALL_HINT)
    return agent


def installed() -> bool:
    try:
        load_agent_module()
    except LLMError:
        return False
    return True


class EasyLLMAdapter(ChatAdapter):

    def __init__(self, kind: str, api_key: str = "", model: str = "", *, base_url: str = "", tools: bool = True,
                 max_tokens: int = 1024, timeout: float = 90.0, session=None):
        if kind not in PROVIDERS:
            raise LLMError(f"不認得的 AI 來源 {kind}。")
        if kind == "openai_compat" and not (base_url or "").strip():
            raise LLMError("相容端點要填網址（例如 http://localhost:11434/v1 或公司給的 https://…/v1）。")
        self.kind = kind
        self.provider, label = PROVIDERS[kind]
        self.api_key = api_key or ""
        self.model = model or ""
        self.base_url = (base_url or "").strip().rstrip("/")
        self.supports_tools = bool(tools)
        self.max_tokens = int(max_tokens)
        self.timeout = timeout
        self._session = session
        self.name = f"{label}（{self.model or '未指定模型'}）"

    @staticmethod
    def to_neutral(messages: Sequence[Message]) -> List[dict]:
        out = []
        for m in messages:
            item = {"role": m.role, "content": m.content}
            if m.tool_calls:
                item["tool_calls"] = [{"id": c.id, "name": c.name, "arguments": c.args} for c in m.tool_calls]
            if m.tool_call_id:
                item["tool_call_id"] = m.tool_call_id
            if m.name:
                item["name"] = m.name
            out.append(item)
        return out

    def chat(self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()) -> Reply:
        agent = load_agent_module()
        if self.kind != "openai_compat" and not self.api_key:
            raise LLMError(f"還沒填 {PROVIDERS[self.kind][1]} 的 API key。")
        specs = [agent.Tool(t.name, t.description, t.parameters) for t in tools] \
            if tools and self.supports_tools else None
        where = self.base_url or PROVIDERS[self.kind][1]
        try:
            reply = agent.chat(self.provider, self.model, self.to_neutral(messages), specs, api_key=self.api_key,
                               base_url=self.base_url or None, max_tokens=self.max_tokens, timeout=self.timeout,
                               session=self._session)
        except agent.LLMHTTPError as e:
            raise LLMError(http_error(e.status, e.body))
        except agent.LLMConnectionError:
            raise LLMError(f"連不到 {where}。檢查網址和網路。")
        except agent.LLMResponseError:
            raise LLMError(f"{where} 回的格式看不懂（是不是網址填錯了？）。")
        except ValueError as e:
            raise LLMError(f"設定不完整：{e}")
        calls = [ToolCall(name=c.name, args=dict(c.arguments or {}), id=c.id) for c in reply.tool_calls]
        return Reply(text=reply.text or "", tool_calls=calls,
                     usage={"input": int(reply.usage.input_tokens), "output": int(reply.usage.output_tokens)})

    def probe(self) -> Optional[str]:
        if not self.model:
            return "還沒填模型名稱。"
        try:
            load_agent_module()
        except LLMError as e:
            return str(e)
        return super().probe()
