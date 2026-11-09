"""
時效：每一個「在等你」的狀態都有期限；過期了就明說，不會默默套用（ClawBot invariant 17）。

ClawBot 2026-10-02 晚上的實例：一段問答從 21:46 一直開著，32 分鐘後打給 /sudo 的驗證碼被它吃掉；
最後一串 6 位數沒有東西在等，被 AI 當成股票代號。所以：

| 狀態 | 期限（config.json） | 過期之後 |
|------|---------------------|----------|
| 問答型對話（表單、精靈） | conversation_idle_minutes＝10（聊天類 chat_idle_minutes＝30） | 下一句先說「已過期」，再照一般訊息處理 |
| 等驗證碼的那一題 | code_prompt_seconds＝120 | 同上；碼一收到就驗、就送出 |
| 新的互動指令碰到舊問答 | — | 新的取代舊的（不叫人先 /exit） |
| bot 離線時累積的非唯讀指令 | stale_message_minutes＝3 | 先問「要現在執行嗎」，不直接跑 |
| 危險或 🔐 指令的按鈕 | button_ttl_minutes＝30 | 按了只回「過期了，重新下指令」 |
| 確認按鈕 | confirm_ttl＝10 分鐘 | 同上；token 隨機，重啟後舊按鈕不會批准新動作 |
| 一次性的選擇（「繼續剛剛的指令」） | choice_ttl＝120 秒 | 同上 |

Pending：按鈕背後的資料放在記憶體，用隨機 token 對應（callback_data 只帶 token），有主人、有期限、用一次就沒了。
新增「會等使用者」的東西時，一定要給它期限。
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple


@dataclass(frozen=True)
class Timing:
    conversation_idle: float = 600.0
    long_conversation_idle: float = 1800.0
    code_prompt: float = 120.0
    stale_message: float = 180.0
    button_ttl: float = 1800.0
    confirm_ttl: float = 600.0
    choice_ttl: float = 120.0

    @classmethod
    def from_config(cls, raw: Optional[dict]) -> "Timing":
        """config.json 的 *_minutes／*_seconds 欄位；沒寫或寫壞的用預設值。"""
        raw = raw or {}
        base = cls()

        def minutes(key: str, default: float) -> float:
            try:
                return max(0.0, float(raw[key]) * 60) if key in raw else default
            except (TypeError, ValueError):
                return default

        def seconds(key: str, default: float) -> float:
            try:
                return max(0.0, float(raw[key])) if key in raw else default
            except (TypeError, ValueError):
                return default

        return cls(conversation_idle=minutes("conversation_idle_minutes", base.conversation_idle),
                   long_conversation_idle=minutes("chat_idle_minutes", base.long_conversation_idle),
                   code_prompt=seconds("code_prompt_seconds", base.code_prompt),
                   stale_message=minutes("stale_message_minutes", base.stale_message),
                   button_ttl=minutes("button_ttl_minutes", base.button_ttl))


class Pending:
    """token → (資料, 主人, 到期)。take() 用一次就拿走；別人、過期、不認得都回 None。"""

    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._items: Dict[str, Tuple[Any, Optional[int], float]] = {}
        self._lock = threading.Lock()

    def put(self, payload: Any, owner_id: Optional[int], ttl: float) -> str:
        token = secrets.token_hex(4)
        now = self._clock()
        with self._lock:
            self._items = {k: v for k, v in self._items.items() if v[2] > now}
            self._items[token] = (payload, owner_id, now + ttl)
        return token

    def take(self, token: str, owner_id: Optional[int] = None) -> Optional[Any]:
        with self._lock:
            item = self._items.get(token)
            if item is None:
                return None
            payload, owner, expires = item
            if owner is not None and owner_id is not None and owner != owner_id:
                return None                      # 不是你的按鈕：留著給本人
            del self._items[token]
        return payload if expires > self._clock() else None

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
