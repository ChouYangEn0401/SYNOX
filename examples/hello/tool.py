# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The SYNOX authors
"""👋 範例工具：算小費、打招呼（synox_sdk 的最小範例）。"""

import math
from typing import Literal

from synox_sdk import Ok, ToolError, serve, tool


@tool("READ", default=True)
def tip(amount: float, percent: int = 10, round_up: bool = False):
    """算含小費的總額。

    Args:
        amount: 帳單金額
        percent: 小費幾 %
        round_up: 要不要進位到整數
    """
    if amount <= 0:
        raise ToolError("bad_amount", "金額要大於 0")
    total = amount * (100 + percent) / 100
    if round_up:
        total = math.ceil(total)
    return Ok(f"含 {percent}% 小費共 {total:g} 元", {"total": total})


@tool("READ")
def greet(name: str, style: Literal["casual", "formal"] = "casual"):
    """跟某人打招呼。

    Args:
        name: 要打招呼的人
        style: casual（輕鬆）或 formal（正式）
    """
    return f"{name}，您好。" if style == "formal" else f"嗨 {name}！"


if __name__ == "__main__":
    serve()
