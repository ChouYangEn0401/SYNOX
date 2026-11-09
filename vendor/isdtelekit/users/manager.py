"""
UserManager：使用者的單一真相來源。

- 以內部使用者 id（= Telegram id）為主鍵，在記憶體中維護，每次異動寫入 users.json
  （core/jsonstore.py：原子寫入，壞檔改名留證據，讀不懂的那一筆跳過）。
- 任何傳訊息過來的人都會被登記成最低一級（dispatcher 對每條訊息都呼叫 get_or_create）。
- 機器擁有者受保護：bootstrap_admin(owner_id) 之後，別人不能把他降到最高一級以下
  （降級的「反懲罰」在 packs/users_admin.py，這裡只拒絕）。
- 讀改寫都在一把鎖裡：不同 channel 是不同執行緒（兩位管理員同時按「接受升級」，pop_pending_promotion 只會讓其中一位拿到）。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from isdtelekit.core.jsonstore import load_json, save_json
from isdtelekit.users.models import User
from isdtelekit.users.roles import BasicRoles

USERS_PATH = "data/users.json"


class UserManager:

    PENDING_EXPIRY_SECONDS = 60 * 60 * 24  # 升級申請 24 小時沒處理就過期

    def __init__(self, path: str = USERS_PATH, roles=BasicRoles, clock: Callable[[], float] = time.time):
        self.path = path
        self.roles = roles
        self.lowest_role = min(roles)
        self.top_role = max(roles)
        self._clock = clock
        self._lock = threading.RLock()
        self._users: Dict[int, User] = {}
        self.machine_owner_id: Optional[int] = None
        self._role_listeners: List[Callable[[User], None]] = []   # 角色變了要做的事（例如重設 Telegram 指令選單）
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        self._load()

    # ---------- 公開 API ----------

    def get(self, tg_id: int) -> Optional[User]:
        return self._users.get(tg_id)

    def get_or_create(self, tg_id: int, username: str = "") -> User:
        """查詢使用者；不存在就以最低一級建立並存檔。之後傳來的 username 不同就更新。"""
        with self._lock:
            user = self._users.get(tg_id)
            if user is None:
                user = self._users[tg_id] = User(tg_id=tg_id, username=username, role=self.lowest_role)
                self._save()
                logging.info("New user registered: @%s (%s)", username, tg_id)
            elif username and user.username != username:
                user.username = username
                self._save()
            return user

    def set_role(self, tg_id: int, role, actor_id: Optional[int] = None) -> bool:
        """改角色。找不到人、或別人想把機器擁有者降到最高一級以下 → False（擁有者改自己要把 actor_id 設成自己）。
        角色一變，待審的申請一併結案；之後在鎖外面通知 on_role_change 的聽眾。"""
        with self._lock:
            user = self._users.get(tg_id)
            if user is None:
                return False
            if (self.machine_owner_id is not None and tg_id == self.machine_owner_id
                    and role < self.top_role and actor_id != self.machine_owner_id):
                logging.warning("Blocked attempt to change protected owner %s -> %s", tg_id, getattr(role, "name", role))
                return False
            user.role = role
            _clear_pending(user)
            self._save()
        logging.info("Role updated: %s -> %s", tg_id, getattr(role, "name", role))
        for listener in list(self._role_listeners):
            try:
                listener(user)
            except Exception:
                logging.exception("role listener failed")
        return True

    def on_role_change(self, listener: Callable[[User], None]) -> None:
        self._role_listeners.append(listener)

    def mark_pending_promotion(self, tg_id: int, requested_to: Optional[int] = 0) -> None:
        """記下升級申請。requested_to：指定要哪一級（數值），0＝升一級。"""
        with self._lock:
            user = self.get_or_create(tg_id)
            user.pending_from = int(user.role)
            user.pending_requested_to = int(requested_to or 0)
            user.pending_ts = float(self._clock())
            self._save()

    def clear_pending_promotion(self, tg_id: int) -> None:
        with self._lock:
            u = self._users.get(tg_id)
            if u and _has_pending(u):
                _clear_pending(u)
                self._save()

    def has_pending_promotion(self, tg_id: int) -> bool:
        """有沒有還沒過期的申請（過期的順便清掉）。"""
        with self._lock:
            u = self._users.get(tg_id)
            if not u or not _has_pending(u):
                return False
            if self._clock() - float(u.pending_ts) > self.PENDING_EXPIRY_SECONDS:
                _clear_pending(u)
                self._save()
                return False
            return True

    def get_pending_promotion(self, tg_id: int) -> Tuple[int, int, float]:
        """(pending_from, pending_requested_to, pending_ts)；沒有就是 (0, 0, 0.0)。"""
        u = self._users.get(tg_id)
        if not u:
            return 0, 0, 0.0
        return int(u.pending_from), int(u.pending_requested_to), float(u.pending_ts)

    def pop_pending_promotion(self, tg_id: int) -> Tuple[int, int, float]:
        """原子地取出並清掉申請（兩個人同時按「接受」只有一個拿到）。沒有就是 (0, 0, 0.0)。"""
        with self._lock:
            u = self._users.get(tg_id)
            if not u or not _has_pending(u):
                return 0, 0, 0.0
            pending = int(u.pending_from), int(u.pending_requested_to), float(u.pending_ts)
            _clear_pending(u)
            self._save()
            return pending

    def list_all(self) -> List[User]:
        return list(self._users.values())

    def admins(self, admin_role=None) -> List[int]:
        """admin_role（預設最高一級）以上的人＋機器擁有者，順序固定、不重複——升級申請要通知的人。"""
        threshold = self.top_role if admin_role is None else admin_role
        ids = [u.tg_id for u in self._users.values() if u.role >= threshold]
        if self.machine_owner_id is not None:
            ids.append(self.machine_owner_id)
        return list(dict.fromkeys(ids))

    def bootstrap_admin(self, tg_id: int) -> None:
        """記住機器擁有者（之後別人不能把他降級）；他還不在名單上就以最高一級建立。
        已經在名單上的不改角色——擁有者可以自己調整（例如測試別的角色看到什麼）。"""
        with self._lock:
            self.machine_owner_id = tg_id
            if tg_id not in self._users:
                self._users[tg_id] = User(tg_id=tg_id, username="owner", role=self.top_role)
                self._save()

    # ---------- 內部 IO ----------

    def _load(self) -> None:
        raw = load_json(self.path, [])
        for entry in raw if isinstance(raw, list) else []:
            try:
                u = User.from_dict(entry, self.roles)
            except (KeyError, TypeError, ValueError) as exc:
                logging.error("Skipping unreadable user entry in %s: %r (%s)", self.path, entry, exc)
                continue
            self._users[u.tg_id] = u
        if self._users:
            logging.info("Loaded %d user(s) from %s", len(self._users), self.path)

    def _save(self) -> None:
        save_json(self.path, [u.to_dict() for u in self._users.values()])


def _has_pending(user: User) -> bool:
    return bool(user.pending_from or user.pending_requested_to or user.pending_ts)


def _clear_pending(user: User) -> None:
    user.pending_from = 0
    user.pending_requested_to = 0
    user.pending_ts = 0.0
