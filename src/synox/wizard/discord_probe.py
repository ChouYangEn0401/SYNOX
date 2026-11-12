"""
精靈跟 Discord 講話的那幾個呼叫（跟 telegram_probe.py 對應，介面故意長得一樣）：

    ok, name = get_me(token)                  → (True, "my_bot") 或 (False, "token 不對…")
    bid = bot_id(token)                        → "123456789012345"（組邀請連結要用）或 None
    url = invite_url(bid)                      → 把 bot 加進任一個 Discord 伺服器的連結
    code = new_pairing_code()                  → 跟 telegram_probe 共用（六位數字）
    who = wait_for_code(token, code, stop=ev)  → {"id", "username", "channel_id"} 或 None

Discord bot 收不到「還沒加進任何伺服器的人」的私訊，所以配對前一定要先把 bot 加進（任一個）伺服器；
wait_for_code 開一條 Gateway 連線等「私訊傳了配對碼」，跟 telegram_probe.wait_for_code 邏輯相同。
"""

from __future__ import annotations

import re
import threading
from typing import Optional, Tuple

TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-\.]{20,}$")


def valid_token(token: str) -> bool:
    return bool(TOKEN_RE.match((token or "").strip()))


def _whoami(token: str, http=None) -> dict:
    from synox.discord.rest import DiscordChannel
    return DiscordChannel(token.strip(), identities=None, http=http).get_me()


def get_me(token: str, http=None) -> Tuple[bool, str]:
    token = (token or "").strip()
    if not valid_token(token):
        return False, "這看起來不是 token（Discord 的 bot token 通常是一長串字母數字）。"
    out = _whoami(token, http=http)
    if not out.get("ok"):
        err = str(out.get("error", ""))
        if "401" in err:
            return False, "token 不對（Discord 說 401）：回 Developer Portal 的 Bot 頁重新 Reset Token。"
        return False, f"連不到 Discord：{err or '原因不明'}"
    me = out.get("result") or {}
    return True, me.get("username") or str(me.get("id") or "")


def bot_id(token: str, http=None) -> Optional[str]:
    out = _whoami(token, http=http)
    if not out.get("ok"):
        return None
    return str((out.get("result") or {}).get("id") or "") or None


def invite_url(client_id: str) -> str:
    """把 bot 加進（使用者自己挑的）伺服器的連結；permissions=2048＝只給「傳訊息」。"""
    return f"https://discord.com/oauth2/authorize?client_id={client_id}&scope=bot&permissions=2048"


def new_pairing_code() -> str:
    from synox.wizard.telegram_probe import new_pairing_code as _new
    return _new()


def wait_for_code(token: str, code: str, *, timeout: float = 900.0,
                  stop: Optional[threading.Event] = None) -> Optional[dict]:
    from synox.discord import wait_for_pairing
    return wait_for_pairing(token.strip(), code, timeout=timeout, stop=stop)
