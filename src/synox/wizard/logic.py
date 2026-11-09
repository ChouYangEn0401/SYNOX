"""
精靈不用畫面的那一半：把使用者在三頁裡選的東西變成 config.json（可以單獨測試）。

    llm = llm_settings("own", provider="openai", api_key="sk-…", model="gpt-4o-mini")
    cfg = build_config(token, owner_id, llm)
    save(path, cfg, api_key)          # 金鑰進保管箱（data/secrets.json.enc），config.json 只寫 "vault:llm_api_key"
"""

from __future__ import annotations

import json
import os
from typing import Optional, Tuple

from synox.llm.factory import VAULT_PREFIX

SECRET_NAME = "llm_api_key"

# ② 自己的 API key：哪一家 → (kind, base_url, 建議的模型)。模型名稱只是預填，使用者可以改，「測一下」會驗。
PROVIDERS = {
    "openai": ("openai_compat", "https://api.openai.com/v1", "gpt-4o-mini"),
    "anthropic": ("anthropic", "https://api.anthropic.com", "claude-sonnet-4-5"),
    "gemini": ("openai_compat", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.0-flash"),
}
CHOICES = ("friend", "own", "claude_code", "none")


def llm_settings(choice: str, *, base_url: str = "", api_key: str = "", model: str = "",
                 provider: str = "openai") -> Tuple[dict, str]:
    """回 (config 的 llm 那一塊（金鑰先放明文，save() 會換成 vault: 參照）, 錯誤或空字串)。"""
    if choice == "none":
        return {"kind": "none"}, ""
    if choice == "claude_code":
        return {"kind": "claude_code", "model": model.strip()}, ""
    if choice == "friend":
        if not base_url.strip().startswith(("http://", "https://")):
            return {}, "AI 網址要以 http:// 或 https:// 開頭。"
        if not model.strip():
            return {}, "要填模型名稱（問給你網址的人）。"
        return {"kind": "openai_compat", "base_url": base_url.strip(), "api_key": api_key.strip(),
                "model": model.strip(), "tools": True}, ""
    if choice == "own":
        if provider not in PROVIDERS:
            return {}, f"不認得的服務 {provider}。"
        if not api_key.strip():
            return {}, "要貼上 API key。"
        kind, url, suggested = PROVIDERS[provider]
        out = {"kind": kind, "api_key": api_key.strip(), "model": model.strip() or suggested}
        if kind == "openai_compat":
            out["base_url"], out["tools"] = url, True
        return out, ""
    return {}, f"不認得的選項 {choice}。"


def build_config(token: str, owner_id: int, llm: dict, *, existing: Optional[dict] = None) -> dict:
    cfg = dict(existing or {})
    cfg.update({"bot_token": token.strip(), "owner_id": int(owner_id)})
    cfg["llm"] = {"max_steps": 6, "max_tokens": 1024, **{k: v for k, v in llm.items()}}
    cfg.setdefault("vault", {"mode": "dpapi" if os.name == "nt" else "file"})
    cfg.setdefault("packs", {"enabled": "all", "disabled": []})
    return cfg


def write_config(path: str, cfg: dict) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def read_existing(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(path: str, cfg: dict, vault_opener=None) -> dict:
    """寫 config.json。llm.api_key 是明文時先存進保管箱，config 裡換成 "vault:llm_api_key"。回寫進去的那份。"""
    cfg = json.loads(json.dumps(cfg))
    key = (cfg.get("llm") or {}).get("api_key", "")
    if key and not str(key).startswith(VAULT_PREFIX):
        if vault_opener is None:
            from synox.config import SynoxConfig
            from synox.vault import open_vault

            def vault_opener(c):
                return open_vault(SynoxConfig.from_dict(c, require_token=False,
                                                        root=os.path.dirname(os.path.abspath(path))))
        vault_opener(cfg).set_secret(SECRET_NAME, key)
        cfg["llm"]["api_key"] = VAULT_PREFIX + SECRET_NAME
    write_config(path, cfg)
    return cfg
