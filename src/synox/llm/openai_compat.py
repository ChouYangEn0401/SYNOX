"""
OpenAI 相容的 /v1/chat/completions：OpenAI、Gemini 的相容端點、公司閘道、Ollama、LM Studio 都是這一支。

    {"kind": "openai_compat", "base_url": "https://api.openai.com/v1", "api_key": "…", "model": "…",
     "tools": true}             閘道沒開 tool-calling 就寫 false → agent 走文字協定（textproto）
"""

from __future__ import annotations

import json
from typing import List, Optional, Sequence

import requests

from synox.llm.base import (ASSISTANT, TOOL, ChatAdapter, LLMError, Message, Reply, ToolCall, ToolSpec,
                            http_error)


class OpenAICompatAdapter(ChatAdapter):
    kind = "openai_compat"

    def __init__(self, base_url: str, api_key: str = "", model: str = "", *, tools: bool = True,
                 max_tokens: int = 1024, timeout: float = 90.0, session=None):
        if not base_url:
            raise LLMError("openai_compat 要填 base_url（例如 https://api.openai.com/v1）。")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.model = model
        self.supports_tools = bool(tools)
        self.max_tokens = int(max_tokens)
        self.timeout = timeout
        self._http = session or requests
        self.name = f"OpenAI 相容（{model or '未指定模型'}）"

    @staticmethod
    def to_wire(messages: Sequence[Message]) -> List[dict]:
        out = []
        for m in messages:
            if m.role == TOOL:
                out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
            elif m.role == ASSISTANT and m.tool_calls:
                out.append({"role": "assistant", "content": m.content or None, "tool_calls": [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.name, "arguments": json.dumps(c.args, ensure_ascii=False)}}
                    for c in m.tool_calls]})
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    def chat(self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()) -> Reply:
        body = {"model": self.model, "messages": self.to_wire(messages), "max_tokens": self.max_tokens}
        if tools and self.supports_tools:
            body["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                               "parameters": t.parameters}} for t in tools]
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            resp = self._http.post(f"{self.base_url}/chat/completions", json=body, headers=headers,
                                   timeout=self.timeout)
        except requests.RequestException as e:
            raise LLMError(f"連不到 {self.base_url}：{type(e).__name__}。檢查網址和網路。")
        if resp.status_code != 200:
            raise LLMError(http_error(resp.status_code, getattr(resp, "text", "")))
        try:
            data = resp.json()
            msg = data["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError("伺服器回的不是 OpenAI 相容的格式。")
        calls = []
        for i, c in enumerate(msg.get("tool_calls") or []):
            fn = c.get("function") or {}
            raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except ValueError:
                args = {"_raw": raw}
            calls.append(ToolCall(name=fn.get("name", ""), args=args if isinstance(args, dict) else {},
                                  id=c.get("id") or f"call_{i}"))
        usage = data.get("usage") or {}
        return Reply(text=msg.get("content") or "", tool_calls=calls,
                     usage={"input": int(usage.get("prompt_tokens") or 0),
                            "output": int(usage.get("completion_tokens") or 0)})

    def probe(self) -> Optional[str]:
        if not self.model:
            return "還沒填模型名稱。"
        return super().probe()
