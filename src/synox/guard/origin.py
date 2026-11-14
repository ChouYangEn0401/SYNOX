"""來源：這個動作是誰引起的（ADR 0025 §2）。一張不可變的標籤放在 contextvar 裡。

    from synox.guard import origin
    with origin.using(origin.Origin("telegram", 42, surface="telegram")):
        ...                                   # 這段裡 origin.current().kind == "telegram"

- 沒人設＝`unknown`（最不可信：收緊過的地方一律拒；沒收緊的照舊）。
- contextvar 不會自己跟到別的執行緒：要帶過去用 `carry(fn)`（AI 那一輪、背景工作）。
- 這個檔不 import synox 的其他模組（之後要整包搬走不用拆）。
"""

from __future__ import annotations

import contextlib
import contextvars
from dataclasses import dataclass
from typing import Callable, Iterator, Optional

KINDS = ("telegram", "discord", "web", "console", "remote", "ai", "schedule", "system", "unknown")
HUMAN = ("telegram", "discord", "web", "console")

# inbound.channel → 來源。"test" 是 SDK BotHarness 的假通道（模擬 Telegram 私訊；正式環境不會出現）。
_CHANNELS = {"telegram": "telegram", "test": "telegram", "discord": "discord", "discord-channel": "discord",
             "console": "console", "routine": "schedule"}


@dataclass(frozen=True)
class Origin:
    kind: str = "unknown"
    user_id: int = 0
    surface: str = ""
    on_behalf: Optional["Origin"] = None

    def __post_init__(self):
        if self.kind not in KINDS:
            object.__setattr__(self, "kind", "unknown")

    @property
    def human(self) -> bool:
        return self.kind in HUMAN

    @property
    def caller(self) -> str:
        """範圍（scope）用的五類＋unknown：human／remote／ai／schedule／system／unknown。"""
        if self.kind in HUMAN:
            return "human"
        return self.kind


UNKNOWN = Origin()
_current: "contextvars.ContextVar[Origin]" = contextvars.ContextVar("synox_origin", default=UNKNOWN)


def current() -> Origin:
    return _current.get()


@contextlib.contextmanager
def using(o: Origin) -> Iterator[Origin]:
    """這段程式的來源是 o（可巢狀；離開時還原外面那一個）。"""
    if not isinstance(o, Origin):
        o = UNKNOWN
    token = _current.set(o)
    try:
        yield o
    finally:
        _current.reset(token)


def carry(fn: Callable) -> Callable:
    """把「現在的來源」帶到別的執行緒：回一個包好的函式，在哪裡執行都用建立時的來源。"""
    captured = current()

    def run(*args, **kw):
        with using(captured):
            return fn(*args, **kw)
    return run


def from_inbound(channel, via=None, user_id: int = 0) -> Origin:
    """SDK 的 inbound.channel（＋via）→ 來源。排程造的訊息（channel=routine 或 via=routine）＝schedule。"""
    if str(via or "") == "routine":
        kind = "schedule"
    else:
        kind = _CHANNELS.get(str(channel or "").lower(), "unknown")
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    return Origin(kind, uid, surface=kind)
