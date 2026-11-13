"""給測試用的小工具（正式程式不要 import）。

    with as_origin("ai", user_id=42): ...      # 這段的來源是 AI
"""

from __future__ import annotations

import contextlib

from synox.guard.origin import Origin, using


@contextlib.contextmanager
def as_origin(kind: str, user_id: int = 0, surface: str = "", on_behalf=None):
    with using(Origin(kind, user_id, surface=surface or kind, on_behalf=on_behalf)) as o:
        yield o
