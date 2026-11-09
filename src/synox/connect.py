"""
python -m synox connect <pack>：在這台電腦上把一個 pack 要的帳號（pack.json 的 auth.fields）存進保管箱。

    {"auth": {"type": "caldav", "fields": [
        {"name": "server", "ask": "伺服器網址", "default": "https://caldav.icloud.com"},
        {"name": "username", "ask": "帳號"},
        {"name": "password", "ask": "App 專用密碼", "secret": true}]}}

為什麼不在聊天裡設：Telegram 訊息不是端對端加密、會留在聊天紀錄，而且 dispatcher 的 [ROUTE] log 會印出指令全文。
這裡 secret 的欄位用 getpass 讀（不顯示、不進 log），存到 pack.store.of(user) 的 key="auth"——
跟 pack 自己讀的是同一份（storage=vault → 密文；伺服器版是那個人自己的 data/users/<id>/）。

--user <id>：伺服器版替哪個人設（預設擁有者）。--clear：清掉存的帳號。
"""

from __future__ import annotations

import getpass
import os
from typing import Callable, Optional

from synox.packs.loader import PackStore, discover
from synox.packs.manifest import ManifestError, read

AUTH_KEY = "auth"


def find_pack(name: str, dirs):
    for folder in discover(dirs):
        try:
            m = read(folder)
        except ManifestError:
            continue
        if m.name == name or os.path.basename(folder) == name:
            return m
    return None


def auth_fields(m) -> list:
    fields = (m.auth_info or {}).get("fields") or []
    return [f for f in fields if isinstance(f, dict) and isinstance(f.get("name"), str) and f["name"]]


def store_for(m, config, vault, tg_id: Optional[int]) -> PackStore:
    server = getattr(config, "mode", "personal") == "server"
    store = PackStore(m.name, config.data_dir, vault if m.storage == "vault" else None, per_user=server)
    return store.of(int(tg_id)) if server else store


def run(name: str, config, vault, *, user: Optional[int] = None, clear: bool = False,
        ask: Callable[[str], str] = input, ask_secret: Callable[[str], str] = getpass.getpass,
        out: Callable[[str], None] = print, dirs=None) -> int:
    m = find_pack(name, dirs if dirs is not None else config.pack_dirs())
    if m is None:
        out(f"❌ 找不到叫 {name} 的 pack。")
        return 2
    fields = auth_fields(m)
    if not fields:
        out(f"❌ {m.name} 的 pack.json 沒有 auth.fields，不需要（也不能）在這裡設定帳號。")
        return 2
    if m.storage != "vault":
        out(f"❌ {m.name} 的 storage 不是 vault：帳號會變成明文，不存。")
        return 2
    tg_id = user if user is not None else getattr(config, "owner_id", None)
    if getattr(config, "mode", "personal") == "server" and not isinstance(tg_id, int):
        out("❌ 伺服器版要指定替誰設定：--user <Telegram id>")
        return 2
    store = store_for(m, config, vault, tg_id)
    if clear:
        store.save({}, key=AUTH_KEY)
        out(f"🗑 {m.title}：已清掉存的帳號。")
        return 0
    out(f"🔐 {m.title}：帳號會加密存在這台電腦的保管箱（{os.path.basename(store.file(AUTH_KEY))}）。")
    old = store.load(None, key=AUTH_KEY) or {}
    values = {}
    for f in fields:
        label = f.get("ask") or f["name"]
        if f.get("secret"):
            value = ask_secret(f"{label}（輸入時不會顯示）：")
        else:
            default = old.get(f["name"]) or f.get("default") or ""
            value = ask(f"{label}" + (f" [{default}]" if default else "") + "：").strip() or default
        value = (value or "").strip()
        if not value:
            out(f"❌ {label} 沒有填，沒有存。")
            return 1
        values[f["name"]] = value
    store.save(values, key=AUTH_KEY)
    out(f"✅ 存好了。到 Telegram 打 /{m.group}_status 測試連線。")
    return 0
