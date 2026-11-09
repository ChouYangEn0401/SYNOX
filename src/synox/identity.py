"""
身分對應：(通道, 外部 id) → 內部使用者 id（整數）。資料在 data/identities.json。

SDK 的內部使用者 id 就是 Telegram user id。其他通道（Discord…）的人要先換成一個內部 id 才能進 dispatcher：

    ids = Identities(config.path("identities.json"))
    uid = ids.resolve("discord", "80351110224678912")   # 第一次見到 → 發一個新號碼；之後都同一個
    ids.bind("discord", "80351110224678912", config.owner_id)   # 配對：把這個 Discord 帳號接到擁有者身上
    ids.external("discord", uid)                          # → "80351110224678912"（回覆時找私訊對象）

安全規則（避免開到別人的資料）：
- 新發的號碼一律從保留號段 BASE（10^15）往上，而且只增不減、永不重用：
  不會撞到真的 Telegram id（目前遠小於 10^15），刪掉的對應也不會讓下一個陌生人繼承舊號碼的資料。
- 只有 bind()（配對成功、擁有者在本機操作）能把外部帳號接到既有的內部 id（例如擁有者的 Telegram id）。
- 一個內部 id 在同一個通道只接一個外部帳號；要換帳號得先 unbind。

頻道（PERM-5）：Discord 伺服器頻道也要一個內部 id 當 chat_id，用 resolve_room：

    room = ids.resolve_room("discord-channel", "1234567890")   # → -(10^15)、-(10^15+1)…（負號，只增不減）

負號跟 Telegram 群組一致：SDK 的 private_only（chat_id ≠ user.tg_id）自然成立，群組裡的閒聊也自然不回。
"""

from __future__ import annotations

import threading
from typing import Optional

from isdtelekit.core.jsonstore import load_json, save_json

BASE = 10 ** 15


class IdentityError(ValueError):
    pass


class Identities:

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        data = load_json(path, {})
        if not isinstance(data, dict):
            data = {}
        links = data.get("links") if isinstance(data.get("links"), dict) else {}
        self._links = {str(k): int(v) for k, v in links.items()}
        self._next = max([int(data.get("next") or BASE), BASE] + [v + 1 for v in self._links.values() if v >= BASE])
        self._next_room = max([int(data.get("next_room") or BASE), BASE]
                              + [-v + 1 for v in self._links.values() if v <= -BASE])

    @staticmethod
    def _key(channel: str, external) -> str:
        external = str(external).strip()
        if not channel or not external:
            raise IdentityError("通道和外部 id 都不能是空的")
        return f"{channel}:{external}"

    def _save(self) -> None:
        save_json(self.path, {"next": self._next, "next_room": self._next_room, "links": dict(self._links)})

    def lookup(self, channel: str, external) -> Optional[int]:
        with self._lock:
            return self._links.get(self._key(channel, external))

    def resolve(self, channel: str, external) -> int:
        """沒見過的外部帳號 → 發一個新號碼（保留號段）並存檔。"""
        key = self._key(channel, external)
        with self._lock:
            if key in self._links:
                return self._links[key]
            uid = self._next
            self._next += 1
            self._links[key] = uid
            self._save()
            return uid

    def resolve_room(self, channel: str, external) -> int:
        """頻道（不是人）→ 負號的內部 id：-(10^15)、-(10^15+1)…，只增不減、永不重用。已經有就回原本那個。"""
        key = self._key(channel, external)
        with self._lock:
            if key in self._links:
                return self._links[key]
            room = -self._next_room
            self._next_room += 1
            self._links[key] = room
            self._save()
            return room

    def bind(self, channel: str, external, internal: int) -> None:
        """把外部帳號接到指定的內部 id（配對用）。這個內部 id 在這個通道已經接了別的帳號就拒絕。"""
        key = self._key(channel, external)
        internal = int(internal)
        prefix = f"{channel}:"
        with self._lock:
            for other, uid in self._links.items():
                if uid == internal and other.startswith(prefix) and other != key:
                    raise IdentityError(f"這個使用者已經接了另一個 {channel} 帳號；先解除再配對")
            self._links[key] = internal
            self._next = max(self._next, internal + 1) if internal >= BASE else self._next
            self._save()

    def unbind(self, channel: str, external) -> bool:
        key = self._key(channel, external)
        with self._lock:
            if self._links.pop(key, None) is None:
                return False
            self._save()            # _next 不退：號碼永不重用
            return True

    def external(self, channel: str, internal) -> Optional[str]:
        """內部 id → 這個通道的外部 id（沒有就 None）。"""
        try:
            internal = int(internal)
        except (TypeError, ValueError):
            return None
        prefix = f"{channel}:"
        with self._lock:
            for key, uid in self._links.items():
                if uid == internal and key.startswith(prefix):
                    return key[len(prefix):]
        return None
