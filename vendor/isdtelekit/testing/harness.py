"""
BotHarness：整支 bot 不連 Telegram 跑一遍（範本的測試都用它）。

    def test_upgrade_request(tmp_path):
        bot = BotHarness.create(tmp_path, roles=Role, quotas=QUOTAS, install=myapp.install)
        bot.make(5, Role.USER)
        bot.say(5, "/me_upgrade")
        assert "已送出" in bot.last(5)
        assert bot.buttons(OWNER)[0].startswith("promote:accept:")
        bot.press(OWNER, bot.buttons(OWNER)[0])

回覆和主動通知（app.home）都記在同一個 FakeChannel（bot.api），所以「通知管理員」也看得到。
"""

from __future__ import annotations

import time
from typing import Callable, List, Optional

from isdtelekit.core.channel import CallbackInfo, Inbound
from isdtelekit.core.dispatcher import Route
from isdtelekit.host.app import App, build_app
from isdtelekit.host.config import BotConfig
from isdtelekit.testing.fakes import FakeChannel

OWNER_ID = 100


class BotHarness:

    def __init__(self, app: App, api: FakeChannel):
        self.app = app
        self.api = api

    @classmethod
    def create(cls, tmp_path, *, owner_id: int = OWNER_ID, install: Optional[Callable[[App], None]] = None,
               config: Optional[dict] = None, **build_kwargs) -> "BotHarness":
        """在 tmp_path 底下建一支 bot：data_dir 在那裡、沒有 token、home 是 FakeChannel。
        install(app)：掛上要測的指令（範本的 bot.install）。其他參數交給 build_app（roles、quotas…）。"""
        raw = {"owner_id": owner_id, "data_dir": str(tmp_path / "data"), **(config or {})}
        api = FakeChannel()
        app = build_app(BotConfig.from_dict(raw, require_token=False), home=api, **build_kwargs)
        if install is not None:
            install(app)
        return cls(app, api)

    # ── 動作 ─────────────────────────────────────────────────────────

    def make(self, user_id: int, role, username: str = "") -> None:
        """先登記一個人、給他角色（測試前置）。"""
        self.app.users.get_or_create(user_id, username or f"u{user_id}")
        self.app.users.set_role(user_id, role, actor_id=self.app.owner_id)

    def say(self, user_id: int, text: str, *, chat_id: Optional[int] = None, ago: float = 0.0,
            via: str = "typed") -> Route:
        """user_id 在 chat_id（沒給＝私訊）打了 text；ago：幾秒前送的（測「bot 離線時累積的舊訊息」）。"""
        inbound = Inbound("test", user_id, chat_id if chat_id is not None else user_id, text,
                          username=f"u{user_id}", sent_at=time.time() - ago)
        return self.app.dispatcher.handle(self.api, inbound, via)

    def press(self, user_id: int, data: str, *, message_id: Optional[int] = None, chat_id: Optional[int] = None,
              ago: float = 0.0) -> Route:
        """按下 callback_data 是 data 的按鈕。message_id 沒給＝最後一則有這顆按鈕的訊息（沒有就 0）。"""
        if message_id is None:
            message_id = next((m.message_id for m in reversed(self.api.sent)
                               if data in self.api.buttons_of(m.message_id)), 0)
        chat = chat_id if chat_id is not None else user_id
        cb = CallbackInfo(chat_id=chat, message_id=message_id, cq_id="cq", clicker_id=user_id, data=data,
                          text=self.api.text_of(message_id), message_date=time.time() - ago)
        return self.app.dispatcher.handle(self.api, Inbound("test", user_id, chat, button=cb))

    # ── 看結果 ───────────────────────────────────────────────────────

    def last(self, chat_id: Optional[int] = None) -> str:
        return self.api.last(chat_id)

    def texts(self, chat_id: Optional[int] = None) -> List[str]:
        return self.api.texts(chat_id)

    def buttons(self, chat_id: Optional[int] = None) -> List[str]:
        return self.api.buttons(chat_id)

    def answers(self) -> List[Optional[str]]:
        return self.api.answers

    def clear(self) -> None:
        self.api.clear()
