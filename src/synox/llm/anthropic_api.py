"""
Anthropic Messages API（/v1/messages），原生 tool use。

    {"kind": "anthropic", "api_key": "…", "model": "…"}      base_url 可選（預設 https://api.anthropic.com）
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import requests

from synox.llm.base import (ASSISTANT, SYSTEM, TOOL, ChatAdapter, LLMError, Message, Reply, ToolCall, ToolSpec,
                            http_error)

API_VERSION = "2023-06-01"


class AnthropicAdapter(ChatAdapter):
    kind = "anthropic"
    supports_tools = True

    def __init__(self, api_key: str, model: str, *, base_url: str = "https://api.anthropic.com",
                 max_tokens: int = 1024, timeout: float = 90.0, session=None):
        self.api_key = api_key or ""
        self.model = model
        self.base_url = (base_url or "https://api.anthropic.com").rstrip("/")
        self.max_tokens = int(max_tokens)
        self.timeout = timeout
        self._http = session or requests
        self.name = f"Anthropic（{model or '未指定模型'}）"

    @staticmethod
    def to_wire(messages: Sequence[Message]) -> Tuple[str, List[dict]]:
        system = "\n\n".join(m.content for m in messages if m.role == SYSTEM)
        out: List[dict] = []
        for m in messages:
            if m.role == SYSTEM:
                continue
            if m.role == TOOL:
                block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) \
                        and all(b.get("type") == "tool_result" for b in out[-1]["content"]):
                    out[-1]["content"].append(block)       # 同一輪的多個工具結果放在同一則 user
                else:
                    out.append({"role": "user", "content": [block]})
            elif m.role == ASSISTANT and m.tool_calls:
                blocks = [{"type": "text", "text": m.content}] if m.content else []
                blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.args} for c in m.tool_calls]
                out.append({"role": "assistant", "content": blocks})
            else:
                out.append({"role": "assistant" if m.role == ASSISTANT else "user", "content": m.content})
        return system, out

    def chat(self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()) -> Reply:
        if not self.api_key:
            raise LLMError("還沒填 Anthropic 的 API key。")
        system, wire = self.to_wire(messages)
        body = {"model": self.model, "max_tokens": self.max_tokens, "messages": wire}
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.parameters}
                             for t in tools]
        headers = {"x-api-key": self.api_key, "anthropic-version": API_VERSION, "content-type": "application/json"}
        try:
            resp = self._http.post(f"{self.base_url}/v1/messages", json=body, headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            raise LLMError(f"連不到 Anthropic：{type(e).__name__}。檢查網路。")
        if resp.status_code != 200:
            raise LLMError(http_error(resp.status_code, getattr(resp, "text", "")))
        try:
            data = resp.json()
            blocks = data["content"]
        except (ValueError, KeyError, TypeError):
            raise LLMError("Anthropic 回的格式看不懂。")
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        calls = [ToolCall(name=b.get("name", ""), args=b.get("input") or {}, id=b.get("id", ""))
                 for b in blocks if b.get("type") == "tool_use"]
        usage = data.get("usage") or {}
        return Reply(text=text, tool_calls=calls, usage={"input": int(usage.get("input_tokens") or 0),
                                                         "output": int(usage.get("output_tokens") or 0)})

    def probe(self) -> Optional[str]:
        if not self.model:
            return "還沒填模型名稱。"
        return super().probe()
