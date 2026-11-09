"""
測試用的假東西：不連 Telegram 也能把整支 bot 跑過一遍。

    from isdtelekit.testing import BotHarness, FakeChannel, text_update, button_update

範本與用 SDK 寫的 bot，測試都用這裡的東西（SDK 自己的測試也是）。
"""

from isdtelekit.testing.fakes import FakeChannel, Sent, button_update, text_update
from isdtelekit.testing.harness import OWNER_ID, BotHarness

__all__ = ["OWNER_ID", "BotHarness", "FakeChannel", "Sent", "button_update", "text_update"]
