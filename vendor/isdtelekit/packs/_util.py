"""packs 共用的小工具：盡力而為地通知別人、參數解析。"""

from __future__ import annotations

import logging
import re
from typing import Optional

DURATION_RE = re.compile(r"^(\d+)([smhd])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
NOTICE_START = "🔔🔔🔔【權限變更通知】🔔🔔🔔\n"
NOTICE_END = "\n────────────────────────"


def tell(api, chat_id: int, text, reply_markup: Optional[dict] = None, **kwargs) -> bool:
    """通知某個人（不是現在這個對話）。送不出去（對方封鎖了 bot、從沒開過對話）回 False、記 warning，不丟例外。"""
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup
    try:
        result = api.send_message(chat_id, text, **kwargs)
    except Exception as exc:
        logging.warning("Could not notify %s: %s", chat_id, exc)
        return False
    return not isinstance(result, dict) or result.get("ok", True) is not False


def parse_id(text) -> Optional[int]:
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def parse_duration(text: str) -> Optional[int]:
    """'15m' / '1h' / '2d' / '30s' → 秒數；格式不對 → None。"""
    m = DURATION_RE.match(text or "")
    return int(m.group(1)) * _UNIT_SECONDS[m.group(2)] if m else None


def role_name(role) -> str:
    return getattr(role, "name", str(role))
