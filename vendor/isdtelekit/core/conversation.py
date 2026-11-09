"""
多輪對話狀態：某個聊天正在等你回答什麼（表單問到一半、/sudo 等驗證碼、聊天型功能）。

    ConversationManager
      start(chat_id, user_id, session_type, handler, ...)  開一段；已經有一段就取代它（舊的記在 session.replaced）
      get(chat_id)        取得目前這段（閒置太久的在這裡過期）
      touch(chat_id)      又回了一句：閒置時間從頭算
      set_idle(chat_id, s)  改這段的期限（例如問到驗證碼那一題，只等 120 秒）
      end(chat_id)        結束
      supersede(api, chat_id)  新的互動指令要開始：結束舊的那段並說一聲（不叫人先 /exit）
      pop_expired(chat_id)     剛剛過期的那段（dispatcher 用它說「上一個問答已過期」）

    Session
      handler(api, chat_id, user, text)：這個聊天的下一則訊息都交給它（指令樹上沒有的 /xxx 也是，
      所以對話裡可以有自己的子指令 /save、/list）。

閒置期限：start(..., idle_seconds=秒) 自己給；不然 long_idle=True（本來就會聊一陣子的）用
timing.long_conversation_idle，其他用 timing.conversation_idle（core/timing.py）。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

from isdtelekit.core.timing import Timing


@dataclass
class Session:
    chat_id: int
    user_tg_id: int
    session_type: str                          # 例如 "form"、"sudo"、"chat"
    messages: List[dict] = field(default_factory=list)   # 想記對話內容的功能自己用
    handler: Optional[Callable] = field(default=None, repr=False)
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    label: str = ""                            # 給人看的名字（例如 /pass_new）；沒給就用 session_type
    idle_seconds: float = 600.0                # 閒置多久過期
    last_active: float = field(default_factory=time.time)
    replaced: Optional["Session"] = field(default=None, repr=False)   # 被這段取代掉的舊對話
    state: dict = field(default_factory=dict)  # handler 自己的狀態（問到第幾題…）

    @property
    def name(self) -> str:
        return self.label or self.session_type


class ConversationManager:
    """對話狀態管理器。Telegram 收訊、本機畫面、排程是不同的執行緒，都會碰它，所以加鎖。"""

    def __init__(self, timing: Optional[Timing] = None, clock: Callable[[], float] = time.time):
        self.timing = timing or Timing()
        self._clock = clock
        self._sessions: Dict[int, Session] = {}
        self._expired: Dict[int, Session] = {}
        self._lock = threading.Lock()

    def start(self, chat_id: int, user_tg_id: int, session_type: str, handler: Callable, *,
              idle_seconds: Optional[float] = None, label: str = "", long_idle: bool = False) -> Session:
        """開啟一個新 Session。若已有 Session 就取代它（舊的放在 session.replaced；要跟使用者說就用 supersede()）。"""
        if idle_seconds is None:
            idle_seconds = self.timing.long_conversation_idle if long_idle else self.timing.conversation_idle
        session = Session(chat_id=chat_id, user_tg_id=user_tg_id, session_type=session_type, handler=handler,
                          label=label, idle_seconds=idle_seconds, last_active=self._clock())
        with self._lock:
            session.replaced = self._sessions.get(chat_id)
            self._sessions[chat_id] = session
            self._expired.pop(chat_id, None)
        logging.info("Session started: chat=%s type=%s", chat_id, session_type)
        return session

    def get(self, chat_id: int) -> Optional[Session]:
        with self._lock:
            session = self._sessions.get(chat_id)
            if session is not None and self._clock() - session.last_active > session.idle_seconds:
                del self._sessions[chat_id]
                self._expired[chat_id] = session
                logging.info("Session expired: chat=%s type=%s (idle %.0fs)", chat_id, session.session_type,
                             self._clock() - session.last_active)
                return None
            return session

    def touch(self, chat_id: int) -> None:
        with self._lock:
            session = self._sessions.get(chat_id)
            if session is not None:
                session.last_active = self._clock()

    def set_idle(self, chat_id: int, seconds: float) -> None:
        with self._lock:
            session = self._sessions.get(chat_id)
            if session is not None:
                session.idle_seconds = seconds
                session.last_active = self._clock()

    def end(self, chat_id: int) -> Optional[Session]:
        with self._lock:
            session = self._sessions.pop(chat_id, None)
        if session:
            logging.info("Session ended: chat=%s type=%s", chat_id, session.session_type)
        return session

    def is_active(self, chat_id: int) -> bool:
        return self.get(chat_id) is not None

    def supersede(self, api, chat_id: int) -> Optional[Session]:
        """新的互動指令要開始：舊的那段直接結束（不再叫人先 /exit），並說一聲。"""
        old = self.end(chat_id) if self.is_active(chat_id) else None
        if old is not None:
            api.send_message(chat_id, f"（已結束上一個「{old.name}」的問答）")
        return old

    def pop_expired(self, chat_id: int) -> Optional[Session]:
        with self._lock:
            return self._expired.pop(chat_id, None)
