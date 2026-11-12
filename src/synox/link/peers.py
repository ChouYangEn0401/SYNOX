"""
名單（PeerStore）：這一台認得哪些 SYNOX（它們的名片）、跟每一台的 seq 計數，存保管箱 data/link_peers.json.enc。

    peers = PeerStore(vault)
    peers.add(card, role="worker")              # 配對成功、或 `synox link trust <名片>`
    peers.get(node_id) → NodeCard｜None          # open_envelope 的 lookup
    peers.next_seq(node_id)                     # 我寄給它的下一個 seq（持久化：重開程式不會倒退）
    peers.last_seen_seq(node_id) / peers.saw(node_id, seq)   # 它寄給我的最後一個 seq（重放防護）

放保管箱而不是明文 JSON：名片本身不是秘密，但被人改掉（換成攻擊者的公鑰）等於換掉對方。
data/ 本來就是信任邊界（.synox.key 也在裡面），保管箱多一層完整性檢查（Fernet 的 HMAC）。
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional

from synox.link.identity import IdentityError, NodeCard

VAULT_NAME = "link_peers"
ROLES = ("console", "worker")


class PeerStore:

    def __init__(self, vault):
        self._vault = vault
        self._lock = threading.RLock()
        self._data: Optional[dict] = None

    def _load(self) -> dict:
        if self._data is None:
            raw = self._vault.load_json(VAULT_NAME, None) or {}
            self._data = {"v": 1, "peers": dict(raw.get("peers") or {})}
        return self._data

    def _save(self) -> None:
        self._vault.save_json(VAULT_NAME, self._data)

    # ── 名單 ─────────────────────────────────────────────────────────

    def add(self, card: NodeCard, role: str, *, via: str = "pair") -> None:
        card.verify()
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        with self._lock:
            data = self._load()
            old = data["peers"].get(card.node_id) or {}
            data["peers"][card.node_id] = {"card": card.to_dict(), "role": role, "via": via,
                                           "added": old.get("added") or int(time.time()),
                                           "out_seq": int(old.get("out_seq") or 0),
                                           "in_seq": old.get("in_seq")}
            self._save()

    def remove(self, node_id: str) -> bool:
        with self._lock:
            data = self._load()
            if node_id not in data["peers"]:
                return False
            del data["peers"][node_id]
            self._save()
            return True

    def get(self, node_id: str) -> Optional[NodeCard]:
        with self._lock:
            entry = self._load()["peers"].get(node_id)
        if entry is None:
            return None
        try:
            return NodeCard.from_dict(entry["card"])
        except (IdentityError, KeyError, TypeError):
            return None                       # 壞掉的名片＝不認識（不拿來驗任何東西）

    def role_of(self, node_id: str) -> Optional[str]:
        with self._lock:
            entry = self._load()["peers"].get(node_id)
        return entry.get("role") if entry else None

    def ids(self, role: Optional[str] = None) -> List[str]:
        with self._lock:
            peers = self._load()["peers"]
            return sorted(n for n, e in peers.items() if role is None or e.get("role") == role)

    def entries(self) -> List[dict]:
        with self._lock:
            return [{"node_id": n, **e} for n, e in sorted(self._load()["peers"].items())]

    def find(self, text: str) -> Optional[str]:
        """用 node_id、前綴（3f2a 或 3f2a-9c1e）或名字找一台；對到兩台以上回 None。"""
        text = (text or "").strip().lower()
        if not text:
            return None
        with self._lock:
            peers = self._load()["peers"]
            hits = [n for n, e in peers.items()
                    if n == text or n.startswith(text) or (e.get("card") or {}).get("name", "").lower() == text]
        return hits[0] if len(hits) == 1 else None

    # ── seq ─────────────────────────────────────────────────────────

    def next_seq(self, node_id: str) -> int:
        with self._lock:
            data = self._load()
            entry = data["peers"].get(node_id)
            if entry is None:
                raise KeyError(node_id)
            entry["out_seq"] = int(entry.get("out_seq") or 0) + 1
            self._save()
            return entry["out_seq"]

    def last_seen_seq(self, node_id: str) -> Optional[int]:
        with self._lock:
            entry = self._load()["peers"].get(node_id)
        return None if entry is None or entry.get("in_seq") is None else int(entry["in_seq"])

    def saw(self, node_id: str, seq: int) -> None:
        with self._lock:
            data = self._load()
            entry = data["peers"].get(node_id)
            if entry is not None and (entry.get("in_seq") is None or int(seq) > int(entry["in_seq"])):
                entry["in_seq"] = int(seq)
                self._save()


__all__ = ["PeerStore", "ROLES", "VAULT_NAME"]
