"""
身分對應：(通道, 外部 id) → 內部使用者 id（整數）。資料在 data/identities.json。

SDK 的內部使用者 id 就是 Telegram user id。其他通道（Discord…）的人要先換成一個內部 id 才能進 dispatcher：

    ids = Identities(config.path("identities.json"))
    uid = ids.resolve("discord", "80351110224678912")   # 第一次見到 → 發一個新號碼；之後都同一個
    ids.bind("discord", "80351110224678912", config.owner_id)   # 配對：把這個 Discord 帳號接到擁有者身上
    ids.external("discord", uid)                          # → "80351110224678912"（回覆時找私訊對象）

安全規則（避免開到別人的資料）：
- BASE（10^15）**保留給擁有者**：只用 Discord、沒有 Telegram id 時 config 的 owner_id 預設就是 BASE
  （config.py）。發給陌生人的號碼一律從 BASE+1 往上，而且只增不減、永不重用：
  不會撞到真的 Telegram id（目前遠小於 10^15），不會撞到擁有者，刪掉的對應也不會讓下一個陌生人繼承舊號碼的資料。
- 只有 bind()（配對成功、擁有者在本機操作，或 config 的 owner_user_id）能把外部帳號接到既有的內部 id
  （例如擁有者的 Telegram id 或 BASE）。
- 一個內部 id 在同一個通道只接一個外部帳號；要換帳號得先 unbind。
- 檔案壞掉（不是 JSON、格式不對）**不會**被當成空的重新發號（那會讓下一個陌生人拿到別人的舊號碼）：
  建構時丟 IdentityFileError，呼叫的人（discord.install）拒絕開 Discord、說清楚原因。
- 舊檔遷移（version 2 以前）：舊版從 BASE 開始發號，第一個陌生人可能拿到 BASE＝擁有者。讀到舊檔時，
  所有對到 BASE 的連結標成「待確認」（suspect）並存回；擁有者重新配對（bind）或 config 的 owner_user_id
  對得上才解除。待確認期間 Discord 私訊一律拒收（discord.DiscordEntry），doctor 與啟動 log 會警告。

頻道（PERM-5）：Discord 伺服器頻道也要一個內部 id 當 chat_id，用 resolve_room：

    room = ids.resolve_room("discord-channel", "1234567890")   # → -(10^15)、-(10^15+1)…（負號，只增不減）

負號跟 Telegram 群組一致：SDK 的 private_only（chat_id ≠ user.tg_id）自然成立，群組裡的閒聊也自然不回。
頻道的號碼是負的，跟任何人（含擁有者 BASE）都不會相等，所以頻道號段不用另外保留 -BASE。
"""

from __future__ import annotations

import json
import os
import threading
from typing import List, Optional

from isdtelekit.core.jsonstore import save_json

BASE = 10 ** 15
FIRST_STRANGER = BASE + 1          # BASE 保留給擁有者（Discord-only 的 owner_id）
FORMAT = 2


class IdentityError(ValueError):
    pass


class IdentityFileError(IdentityError):
    """identities.json 讀不了（壞掉、格式不對）。不會自動重建：要人看過再處理。"""


def _read(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, UnicodeDecodeError, OSError) as e:
        raise IdentityFileError(
            f"{path} 壞掉了（{type(e).__name__}）。為了不把別人的號碼發給陌生人，Discord 先不開；"
            "從備份還原這個檔，或確定沒有人用過 Discord 再把它改名移開（會重新發號、所有 Discord 帳號要重新配對）。")
    if not isinstance(data, dict) or not isinstance(data.get("links", {}), dict):
        raise IdentityFileError(f"{path} 的格式不對（最外層要是物件、links 要是物件）。Discord 先不開；從備份還原這個檔。")
    try:
        {str(k): int(v) for k, v in (data.get("links") or {}).items()}
        int(data.get("next") or 0), int(data.get("next_room") or 0)
    except (TypeError, ValueError):
        raise IdentityFileError(f"{path} 裡有不是數字的號碼。Discord 先不開；從備份還原這個檔。")
    return data


class Identities:

    def __init__(self, path: str, *, readonly: bool = False):
        """readonly=True：只看不寫（doctor 用；舊檔也不遷移，存檔一律略過）。"""
        self.path = path
        self.readonly = readonly
        self._lock = threading.Lock()
        self._stamp = None
        self._load()

    def _load(self) -> None:
        data = _read(self.path)
        links = data.get("links") or {}
        self._links = {str(k): int(v) for k, v in links.items()}
        self._suspect = {str(k) for k in (data.get("suspect") or []) if str(k) in self._links}
        legacy = bool(data) and data.get("version") != FORMAT
        if legacy:                              # 舊版從 BASE 發號：對到 BASE 的不知道是配對來的還是陌生人
            self._suspect |= {k for k, v in self._links.items() if v == BASE}
        self._next = max([int(data.get("next") or FIRST_STRANGER), FIRST_STRANGER]
                         + [v + 1 for v in self._links.values() if v >= BASE])
        self._next_room = max([int(data.get("next_room") or BASE), BASE]
                              + [-v + 1 for v in self._links.values() if v <= -BASE])
        if legacy:
            self._save()                        # 遷移一次：寫成 version 2（含 suspect），之後不再重標
        self._stamp = self._mtime()

    def _mtime(self):
        try:
            return os.stat(self.path).st_mtime_ns
        except OSError:
            return None

    def reload_if_changed(self) -> bool:
        """檔案被別的程序改過（例如 `python -m synox discord pair`）就重讀。讀不了就維持記憶體裡的。"""
        stamp = self._mtime()
        if stamp is None or stamp == self._stamp:
            return False
        with self._lock:
            try:
                self._load()
            except IdentityFileError:
                return False
        return True

    @staticmethod
    def _key(channel: str, external) -> str:
        external = str(external).strip()
        if not channel or not external:
            raise IdentityError("通道和外部 id 都不能是空的")
        return f"{channel}:{external}"

    def _save(self) -> None:
        if self.readonly:
            return
        save_json(self.path, {"version": FORMAT, "next": self._next, "next_room": self._next_room,
                              "links": dict(self._links), "suspect": sorted(self._suspect)})
        self._stamp = self._mtime()

    def lookup(self, channel: str, external) -> Optional[int]:
        with self._lock:
            return self._links.get(self._key(channel, external))

    def resolve(self, channel: str, external) -> int:
        """沒見過的外部帳號 → 發一個新號碼（BASE+1 起的保留號段）並存檔。"""
        key = self._key(channel, external)
        with self._lock:
            if key in self._links:
                return self._links[key]
            uid = max(self._next, FIRST_STRANGER)
            self._next = uid + 1
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
        """把外部帳號接到指定的內部 id（配對用）。這個內部 id 在這個通道已經接了別的帳號就拒絕。
        配對＝擁有者在本機確認過，所以這個連結的「待確認」標記一併解除。"""
        key = self._key(channel, external)
        internal = int(internal)
        prefix = f"{channel}:"
        with self._lock:
            for other, uid in self._links.items():
                if uid == internal and other.startswith(prefix) and other != key:
                    raise IdentityError(f"這個使用者已經接了另一個 {channel} 帳號；先解除再配對")
            self._links[key] = internal
            self._suspect.discard(key)
            self._next = max(self._next, internal + 1) if internal > BASE else self._next
            self._save()

    def unbind(self, channel: str, external) -> bool:
        key = self._key(channel, external)
        with self._lock:
            if self._links.pop(key, None) is None:
                return False
            self._suspect.discard(key)
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

    # ── 舊檔遷移：對到 BASE、還沒確認的連結 ───────────────────────────────

    def is_suspect(self, channel: str, external) -> bool:
        with self._lock:
            return self._key(channel, external) in self._suspect

    def suspects(self, channel: Optional[str] = None) -> List[str]:
        """還沒確認的連結的外部 id（channel 沒給＝全部，回 "通道:外部 id"）。"""
        with self._lock:
            keys = sorted(self._suspect)
        if channel is None:
            return keys
        prefix = f"{channel}:"
        return [k[len(prefix):] for k in keys if k.startswith(prefix)]

    def confirm(self, channel: str, external) -> None:
        """解除「待確認」（擁有者有 Telegram id 時，BASE 只是一般號碼）。"""
        key = self._key(channel, external)
        with self._lock:
            if key in self._suspect:
                self._suspect.discard(key)
                self._save()

    def owner_bound(self, channel: str, owner_id: int) -> bool:
        """擁有者在這個通道有接好、已確認的帳號嗎。"""
        found = self.external(channel, owner_id)
        return found is not None and not self.is_suspect(channel, found)
