"""make_adapter(config) → ChatAdapter 或 None（llm.kind = "none"）。換 LLM 只改 config.json 的 llm。"""

from __future__ import annotations

import logging
import os
from typing import Optional

from synox.llm.base import ChatAdapter, LLMError

VAULT_PREFIX = "vault:"


def resolve_secret(value: str, vault=None) -> str:
    """'vault:llm_api_key' → data/secrets.json.enc 裡的值；'env:NAME' → 環境變數；其他照原樣。"""
    value = str(value or "")
    if value.startswith(VAULT_PREFIX):
        if vault is None:
            raise LLMError("設定的金鑰放在保管箱，但保管箱沒有打開。")
        found = vault.secret(value[len(VAULT_PREFIX):])
        if not found:
            raise LLMError(f"保管箱裡找不到 {value[len(VAULT_PREFIX):]}；重跑 Setup.bat 再填一次金鑰。")
        return found
    if value.startswith("env:"):
        return os.environ.get(value[4:], "")
    return value


CLOUD_TIMEOUT = 90.0


def easy_timeout(llm: dict) -> float:
    """API 金鑰來源的逾時：config 的 llm.timeout（秒）；沒寫（或 0）時，openai_compat 指到這台或家裡網路
    （loopback／私網，多半是本地模型）＝450 秒，其他＝90 秒。"""
    from synox.llm.local import DEFAULT_TIMEOUT, is_local_url
    try:
        value = float(llm.get("timeout") or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value > 0:
        return value
    if llm.get("kind") == "openai_compat" and is_local_url(str(llm.get("base_url") or "")):
        return DEFAULT_TIMEOUT
    return CLOUD_TIMEOUT


def make_adapter(config, vault=None, *, session=None, opener=None) -> Optional[ChatAdapter]:
    """config：SynoxConfig 或只有 llm 那一塊的 dict（精靈「測一下」用）。
    session：ntu_easy_llm 的假 requests（測試）；opener：本地模型的假 urllib opener（測試）。"""
    llm = dict(config.get("llm", config) if isinstance(config, dict) else config.llm)
    kind = llm.get("kind", "none")
    max_tokens = int(llm.get("max_tokens") or 1024)
    if kind in ("none", "", None):
        return None
    if kind == "fake":
        from synox.llm.fake import FakeAdapter
        return FakeAdapter(llm.get("script"))
    if kind == "local":                                               # 內建：本地模型（Ollama、vLLM、LM Studio…）
        from synox.llm.local import LocalAdapter, validate
        try:
            s = validate(llm)
        except ValueError as e:
            raise LLMError(f"本地模型的設定不對：{e}")
        return LocalAdapter(s["model"], server=s["server"], base_url=s["base_url"], context_size=s["context_size"],
                            timeout=s["timeout"], max_total_timeout=s["max_total_timeout"], tools=s["tools"],
                            max_tokens=max_tokens, opener=opener, sampling=s["sampling"], options=s["options"])
    if kind in ("openai", "anthropic", "gemini", "openai_compat"):     # API 金鑰的來源都經 ntu_easy_llm
        from synox.llm.easy_llm import EasyLLMAdapter
        return EasyLLMAdapter(kind, resolve_secret(llm.get("api_key", ""), vault), llm.get("model", ""),
                              base_url=llm.get("base_url") or "", tools=llm.get("tools", True),
                              max_tokens=max_tokens, timeout=easy_timeout(llm), session=session)
    if kind == "claude_code":
        from synox.llm.claude_code import ClaudeCodeAdapter
        workdir = os.path.join(config.data_dir, "claude_workspace") if hasattr(config, "data_dir") else ""
        return ClaudeCodeAdapter(llm.get("model", ""), workdir=workdir)
    logging.error("[LLM] unknown llm.kind %r", kind)
    return None
