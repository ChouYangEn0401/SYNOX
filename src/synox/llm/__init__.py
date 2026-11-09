"""LLM adapter：只會聊天（spec §5、invariant 2）。make_adapter(config) 依 config.json 的 llm 選一支。"""

from synox.llm.base import ChatAdapter, LLMError, Message, Reply, ToolCall, ToolSpec
from synox.llm.factory import make_adapter

__all__ = ["ChatAdapter", "LLMError", "Message", "Reply", "ToolCall", "ToolSpec", "make_adapter"]
