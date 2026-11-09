"""
精靈跟 Telegram 講話的那幾個呼叫（只用 requests，不開任何埠：getUpdates 是我們去問 Telegram）。

    ok, name = get_me(token)                         → (True, "my_bot") 或 (False, "token 不對…")
    code = new_pairing_code()                        → "042917"
    who = wait_for_code(token, code, stop=event)     → {"id": 123, "username": "…", "first_name": "…"} 或 None

wait_for_code 只認「精靈開始等之後」才傳來、私訊、內容剛好是那六個數字的訊息；認到之後把那些 update 確認掉
（下一次 getUpdates 帶 offset），bot 正式啟動時就不會再收到那串數字。
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from typing import Optional, Tuple

import requests

from isdtelekit.host.config import TOKEN_RE

API = "https://api.telegram.org/bot{token}/{method}"


def valid_token(token: str) -> bool:
    return bool(TOKEN_RE.match((token or "").strip()))


def new_pairing_code() -> str:
    return f"{secrets.randbelow(10 ** 6):06d}"


def _call(http, token: str, method: str, params: Optional[dict] = None, http_timeout: float = 15.0) -> dict:
    resp = http.post(API.format(token=token.strip(), method=method), json=params or {}, timeout=http_timeout)
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if getattr(resp, "status_code", 200) == 401 or data.get("error_code") == 401:
        raise PermissionError("token 不對（Telegram 說 401）：再到 @BotFather 複製一次。")
    if not data.get("ok"):
        raise RuntimeError(data.get("description") or f"Telegram 回了錯誤（{getattr(resp, 'status_code', '?')}）")
    return data


def get_me(token: str, http=requests) -> Tuple[bool, str]:
    if not valid_token(token):
        return False, "這看起來不是 token（長得像 123456789:AAH…，中間有冒號）。"
    try:
        data = _call(http, token, "getMe")
    except PermissionError as e:
        return False, str(e)
    except requests.RequestException:
        return False, "連不到 Telegram：檢查網路。"
    except RuntimeError as e:
        return False, f"Telegram 說：{e}"
    return True, data["result"].get("username", "")


def matches(update: dict, code: str) -> Optional[dict]:
    """這個 update 是不是「私訊傳了配對碼」；是的話回傳送訊息的人。"""
    msg = update.get("message") or {}
    text = re.sub(r"\s+", "", str(msg.get("text") or ""))
    chat = msg.get("chat") or {}
    sender = msg.get("from") or {}
    if text == code and chat.get("type", "private") == "private" and sender.get("id") and not sender.get("is_bot"):
        return {"id": int(sender["id"]), "username": sender.get("username", ""),
                "first_name": sender.get("first_name", "")}
    return None


def wait_for_code(token: str, code: str, *, timeout: float = 900.0, stop: Optional[threading.Event] = None,
                  http=requests, poll: int = 20, clock=time.time) -> Optional[dict]:
    stop = stop or threading.Event()
    deadline = clock() + timeout
    offset = None
    try:                                           # 先跳過以前就在排隊的訊息
        backlog = _call(http, token, "getUpdates", {"offset": -1, "timeout": 0}).get("result") or []
        if backlog:
            offset = backlog[-1]["update_id"] + 1
    except (requests.RequestException, RuntimeError, PermissionError):
        pass
    while not stop.is_set() and clock() < deadline:
        try:
            params = {"timeout": poll, "allowed_updates": ["message"]}
            if offset is not None:
                params["offset"] = offset
            updates = _call(http, token, "getUpdates", params, http_timeout=poll + 10).get("result") or []
        except PermissionError:
            return None
        except (requests.RequestException, RuntimeError):
            stop.wait(3)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            who = matches(update, code)
            if who is not None:
                try:
                    _call(http, token, "getUpdates", {"offset": offset, "timeout": 0})
                    _call(http, token, "sendMessage", {"chat_id": who["id"],
                                                      "text": "✅ 配對成功！回到電腦上的安裝畫面，按「下一步」。"})
                except (requests.RequestException, RuntimeError, PermissionError):
                    pass
                return who
    return None
