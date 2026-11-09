"""
工具的「確認來回」（SDK P3）：工具在執行中才知道危險（「要刪 3 筆」）時回 needs_confirm 信封，
SYNOX 出核准卡給下令的人，按 ✅ 才用**同一組參數**重跑一次，這一次子程序的環境多了

    SYNOX_CONFIRMED=1            這一次是人按過 ✅ 的重跑（SYNOX 驗過一次性的確認憑證才給）
    SYNOX_CONFIRM_TOKEN=<字>     工具第一次回的 confirm_token（原樣送回，讓工具對得上自己看到的那份資料）

其他時候一律 SYNOX_CONFIRMED=0、SYNOX_CONFIRM_TOKEN 空的（蓋過 pack 的 cli.env 與 SYNOX 自己的環境），
所以「已確認」只可能來自這裡，AI 或 pack.json 都造不出來；重跑的 argv 跟第一次一樣，沒有「--yes」這種 AI 能塞的參數。

確認憑證（grant）放在記憶體：隨機 id、綁 pack／指令／參數雜湊／使用者、數分鐘過期、用一次就沒了；重啟就失效。
按 ❌、過期、參數對不上（被改過）＝不執行。
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

ENV_CONFIRMED = "SYNOX_CONFIRMED"
ENV_TOKEN = "SYNOX_CONFIRM_TOKEN"
ENV_NAMES = (ENV_CONFIRMED, ENV_TOKEN)
TOKEN_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")        # 工具給的 confirm_token：只收這種（放得進環境變數、不夾控制字元）
SUMMARY_MAX = 500
DEFAULT_TTL = 300.0

EXPIRED = "⌛ 這個確認過期了（或參數跟確認的不一樣），沒有執行。要做請重新下一次指令。"
AGAIN = "❌ {name}：按了確認之後工具又要求確認，沒有執行（工具的問題，請回報給 pack 作者）。"
NO_DESK = "❌ {name}：這個動作要你確認，但確認卡沒有接上，所以沒有執行。"


def args_hash(pack: str, command: str, values: Dict[str, Any], user_id: Optional[int]) -> str:
    blob = json.dumps({"pack": pack, "command": command, "user": user_id,
                       "values": {str(k): str(v) for k, v in (values or {}).items()}},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def tool_token(envelope: dict) -> str:
    token = envelope.get("confirm_token")
    return token if isinstance(token, str) and TOKEN_RE.fullmatch(token) else ""


def summary_of(envelope: dict) -> str:
    text = envelope.get("summary")
    if not isinstance(text, str) or not text.strip():
        text = envelope.get("message") if isinstance(envelope.get("message"), str) else ""
    text = (text or "").strip() or "這個動作要你確認"
    return text if len(text) <= SUMMARY_MAX else text[:SUMMARY_MAX - 1] + "…"


def is_needs_confirm(data: Any) -> bool:
    return isinstance(data, dict) and data.get("needs_confirm") is True


def env_for(token: Optional[str]) -> Dict[str, str]:
    """子程序的確認旗標。token=None＝沒確認（一律明寫 0，蓋過任何地方帶進來的值）。"""
    if token is None:
        return {ENV_CONFIRMED: "0", ENV_TOKEN: ""}
    return {ENV_CONFIRMED: "1", ENV_TOKEN: token}


@dataclass
class Grant:
    digest: str
    user_id: Optional[int]
    token: str                  # 工具的 confirm_token（重跑時原樣送回）
    expires: float


class ConfirmGrants:
    """一次性確認憑證。issue()＝工具要確認時發；redeem()＝重跑時驗（成功就拿走）；discard()＝按 ❌。"""

    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._items: Dict[str, Grant] = {}
        self._lock = threading.Lock()

    def issue(self, pack: str, command: str, values: Dict[str, Any], user_id: Optional[int], token: str = "",
              ttl: float = DEFAULT_TTL) -> str:
        now = self._clock()
        gid = secrets.token_hex(16)
        with self._lock:
            self._items = {k: g for k, g in self._items.items() if g.expires > now}
            self._items[gid] = Grant(args_hash(pack, command, values, user_id), user_id, token, now + float(ttl))
        return gid

    def redeem(self, gid: str, pack: str, command: str, values: Dict[str, Any], user_id: Optional[int]
               ) -> Optional[str]:
        """對得上（同一個 pack／指令／參數／人、沒過期）回工具的 token（可能是空字串）；對不上回 None。
        不管對不對得上，這張憑證都用掉了（被竄改過的就作廢，不留給下一次猜）。"""
        with self._lock:
            grant = self._items.pop(gid, None) if isinstance(gid, str) else None
        if grant is None or grant.expires <= self._clock():
            return None
        if grant.user_id != user_id or grant.digest != args_hash(pack, command, values, user_id):
            return None
        return grant.token

    def discard(self, gid: str) -> None:
        with self._lock:
            self._items.pop(gid, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


def grants_of(app) -> ConfirmGrants:
    found = app.extras.get("synox_confirm_grants")
    return found if found is not None else app.extras.setdefault("synox_confirm_grants", ConfirmGrants())


__all__ = ["AGAIN", "ConfirmGrants", "ENV_CONFIRMED", "ENV_NAMES", "ENV_TOKEN", "EXPIRED", "NO_DESK", "args_hash",
           "env_for", "grants_of", "is_needs_confirm", "summary_of", "tool_token"]
