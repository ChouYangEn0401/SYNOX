"""
角色階梯：一個 IntEnum，數字越大權限越高。權限比較一律用 >=（registry.authorize）。

SDK 不規定有幾級。慣例只有兩條：
  - 最低那一級＝新來的人（任何人傳訊息就自動登記成這一級）
  - 最高那一級＝管理員；機器擁有者不能被別人降到這一級以下
沒給階梯的地方用 BasicRoles（訪客／成員／管理員）。範本 A（分級公開服務）用五級，自己定義一個 IntEnum 傳進去：

    class Role(IntEnum):
        GUEST = 0
        USER = 1
        VIP_I = 2
        VIP_II = 3
        ADMIN = 4

    registry = CommandRegistry(owner_id, roles=Role)
    users = UserManager("data/users.json", roles=Role)
"""

from __future__ import annotations

from enum import IntEnum
from typing import Optional, Type


class BasicRoles(IntEnum):
    """三級：訪客（誰都是）、成員（拿到通行證或被管理員加進來的）、管理員。"""
    GUEST = 0
    MEMBER = 1
    ADMIN = 2


def lowest(roles: Type[IntEnum]) -> IntEnum:
    return min(roles)


def highest(roles: Type[IntEnum]) -> IntEnum:
    return max(roles)


def by_name(roles: Type[IntEnum], text: str) -> Optional[IntEnum]:
    """'vip_i' / 'VIP_I' → Role.VIP_I；別名（例如 VIP = 2）也認得。不認識回 None。"""
    try:
        return roles[(text or "").strip().upper()]
    except KeyError:
        return None


def next_up(roles: Type[IntEnum], role: IntEnum) -> Optional[IntEnum]:
    """往上一級；已經最高回 None。別名不算一級（照數值排序、去掉重複）。"""
    ladder = sorted(set(roles))
    higher = [r for r in ladder if r > role]
    return higher[0] if higher else None


def choices(roles: Type[IntEnum]) -> str:
    """'guest|member|admin'：給用法說明用（不含別名）。"""
    return "|".join(r.name.lower() for r in sorted(set(roles)))
