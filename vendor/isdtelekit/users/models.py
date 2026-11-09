"""User：一個認得的使用者。存進 users.json 的格式跟 ClawBot 一樣（tg_id、username、role、pending_*）。"""

from __future__ import annotations

from dataclasses import dataclass

from isdtelekit.users.roles import BasicRoles


@dataclass
class User:
    """tg_id 是內部使用者 id（就是 Telegram user id）；role 是角色階梯裡的一級（IntEnum）。"""
    tg_id: int
    username: str = ""
    role: int = 0
    # 待審的升級申請：從哪一級申請、要哪一級（0＝升一級）、什麼時候申請的（24 小時過期）
    pending_from: int = 0
    pending_requested_to: int = 0
    pending_ts: float = 0.0

    def to_dict(self) -> dict:
        return {
            "tg_id": self.tg_id,
            "username": self.username,
            "role": int(self.role),
            "pending_from": int(self.pending_from),
            "pending_requested_to": int(self.pending_requested_to),
            "pending_ts": float(self.pending_ts),
        }

    @classmethod
    def from_dict(cls, d: dict, roles=BasicRoles) -> "User":
        """roles：角色階梯（users.json 裡存的是數字）；沒寫 role 的拿最低那一級，數字不在階梯裡會丟 ValueError。"""
        return cls(
            tg_id=int(d["tg_id"]),
            username=d.get("username", ""),
            role=roles(int(d.get("role", min(roles)))),
            pending_from=int(d.get("pending_from", 0)),
            pending_requested_to=int(d.get("pending_requested_to", 0)),
            pending_ts=float(d.get("pending_ts", 0.0)),
        )
