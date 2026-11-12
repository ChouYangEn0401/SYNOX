"""Telegram 擁有者配對（身分對應）：讓「只用網頁／Discord 安裝」的擁有者之後也能從 Telegram 用，而且**資料不用搬**。

背景（QuestionToUser.md Q14）：SDK 直接用 Telegram 的數字 id 當內部使用者 id；只用網頁時擁有者的內部 id 是保留的 BASE（10^15）。
你從 Telegram 傳訊息，進來的是你的 Telegram 編號，SYNOX 會當成陌生人（guest）。這裡做跟 Discord 一樣的對照表：
`data/identities.json` 記「telegram:<你的 Telegram 編號> ＝ 擁有者（BASE）」。

做法（不改 SDK、不改擁有者 id、不搬任何資料）：
- 進來：TelegramEntry 換成 LinkedEntry——對得上對照表的人，user_id／chat_id（私訊）換成擁有者的內部 id 再交給 dispatcher。
- 出去：BotAPI 這個物件的「送給某個 chat_id」那幾個方法換成會翻譯的版本——chat_id 是擁有者的內部 id 就換回 Telegram 編號。
  （不包一層新物件：host 要認得 home 是 BotAPI 才會啟動收訊。）
- 配對：網頁產生六位數字（discord/pairing.py 的 WebPairing）→ 在 Telegram 私訊 bot 傳它 → 對照表多一行。或直接在網頁貼 Telegram 編號。
- 還沒配對時：擁有者是 BASE 的安裝，Telegram 上的任何人一律不收（回一句「還沒配對」），不登記成使用者、不讓陌生人碰到資料。

只有擁有者的內部 id 是 BASE（沒有真的 Telegram id）而且有 Telegram token 的安裝才會啟用；其他安裝（擁有者本來就是 Telegram id）完全不經過這一層。
"""

from __future__ import annotations

import dataclasses
import logging
import threading
from typing import Callable, Dict, List, Optional

from isdtelekit.core.dispatcher import TYPED
from isdtelekit.telegram.updates import parse_update

from synox.identity import BASE, Identities, IdentityError, IdentityFileError

TELEGRAM = "telegram"
UNPAIRED = ("🔒 這個 SYNOX 的擁有者還沒把 Telegram 帳號配對好，暫時不收任何訊息。\n"
            "擁有者：打開 SYNOX 網頁 → 設定 → 聊天通道 → Telegram →「配對我的 Telegram 帳號」，照畫面把六個數字私訊給我就好。")
PAIRED_OK = "✅ 配對好了！你的 Telegram 帳號現在是這個 SYNOX 的擁有者。可以直接跟我說話，或打 /help。"
CHAT_METHODS = ("send_message", "edit_message_text", "send_photo", "send_document", "send_media_group",
                "remove_buttons", "delete_message", "typing")        # 第一個參數是 chat_id 的那幾個（bot_api.py）
TOLD_KEPT = 500


def bind_owner(identities: Identities, external_id, owner_id: int) -> List[str]:
    """把 Telegram 帳號接到擁有者 owner_id（配對）。之前接的是別的帳號就解除舊的；這個帳號之前拿過別的號碼也改接。"""
    external_id = str(external_id)
    notes: List[str] = []
    old = identities.lookup(TELEGRAM, external_id)
    if old is not None and old != owner_id:
        identities.unbind(TELEGRAM, external_id)
    previous = identities.external(TELEGRAM, owner_id)
    if previous and previous != external_id:
        identities.unbind(TELEGRAM, previous)
        notes.append(f"（原本配對的 Telegram 帳號 {previous} 已解除。）")
    identities.bind(TELEGRAM, external_id, owner_id)
    return notes


class TelegramLink:

    def __init__(self, identities: Identities, owner_id: int, pairing):
        self.identities = identities
        self.owner_id = int(owner_id)
        self.pairing = pairing                       # discord/pairing.py 的 WebPairing（兩個通道各一個）
        self._told: Dict[int, None] = {}
        self._lock = threading.Lock()

    # ── 對照表 ───────────────────────────────────────────────────────

    def external(self) -> Optional[str]:
        """擁有者配對好的 Telegram 編號（沒有＝None）。對照表被別的程序改過（例如網頁剛配對）會重讀。"""
        try:
            self.identities.reload_if_changed()
        except Exception:
            pass
        return self.identities.external(TELEGRAM, self.owner_id)

    def real(self, chat_id):
        """內部 chat_id → Telegram 的 chat_id（擁有者的內部 id 換回他的 Telegram 編號；其他原樣）。"""
        if chat_id == self.owner_id:
            ext = self.external()
            if ext and ext.isdigit():
                return int(ext)
        return chat_id

    # ── 出去：BotAPI 的方法換成會翻譯的 ─────────────────────────────

    def patch_api(self, api) -> None:
        for name in CHAT_METHODS:
            orig = getattr(api, name, None)
            if orig is None or getattr(orig, "_linked", False):
                continue

            def make(orig=orig):
                def call(chat_id, *a, **kw):
                    return orig(self.real(chat_id), *a, **kw)
                call._linked = True
                return call
            setattr(api, name, make())

    # ── 進來 ────────────────────────────────────────────────────────

    def handle(self, dispatcher, api, inbound, via):
        uid = inbound.user_id
        private = inbound.chat_id == uid
        if inbound.button is None and private and self._try_pair(api, inbound):
            return None
        ext = self.external()
        if ext is not None and str(uid) == ext:                       # 配對好的擁有者：換成內部 id
            cb = inbound.button
            if cb is not None:
                cb = dataclasses.replace(cb, clicker_id=self.owner_id,
                                         chat_id=self.owner_id if cb.chat_id == uid else cb.chat_id)
            inbound = dataclasses.replace(inbound, user_id=self.owner_id,
                                          chat_id=self.owner_id if private else inbound.chat_id, button=cb)
            return dispatcher.handle(api, inbound, via)
        if ext is None:                                                # 還沒配對：誰的訊息都不收
            self._refuse(api, inbound)
            return None
        return dispatcher.handle(api, inbound, via)                    # 已配對，這是別人（成員／陌生人）：照舊

    def _try_pair(self, api, inbound) -> bool:
        code = self.pairing.code() if self.pairing is not None else ""
        if not code:
            return False
        text = "".join(str(inbound.text or "").split())
        if text != code:
            if text.isdigit() and len(text) == len(code):
                self.pairing.wrong_guess()                             # 猜六位數字：記一次，太多次作廢
            return False
        if not self.pairing.matches(text):
            return False
        try:
            notes = bind_owner(self.identities, inbound.user_id, self.owner_id)
        except (IdentityError, IdentityFileError, ValueError) as e:
            logging.warning("[TELEGRAM] web pairing failed: %s", e)
            api.send_message(inbound.chat_id, f"❌ 配對失敗：{e}")
            return True
        self.pairing.done({"id": inbound.user_id, "username": inbound.username})
        logging.info("[TELEGRAM] owner paired from the web page (telegram user %s)", inbound.user_id)
        api.send_message(inbound.chat_id, PAIRED_OK + ("\n" + "\n".join(notes) if notes else ""))
        return True

    def _refuse(self, api, inbound) -> None:
        cb = inbound.button
        if cb is not None:
            try:
                api.answer_callback_query(cb.cq_id, UNPAIRED)
            except Exception:
                pass
            return
        if inbound.chat_id != inbound.user_id:                        # 群組裡不回（不洗版）
            return
        with self._lock:
            if inbound.user_id in self._told:
                return
            self._told[inbound.user_id] = None
            while len(self._told) > TOLD_KEPT:
                self._told.pop(next(iter(self._told)))
        api.send_message(inbound.chat_id, UNPAIRED)


class LinkedEntry:
    """換掉 app.telegram：update → Inbound →（配對／換成內部 id）→ dispatcher.handle()。"""

    def __init__(self, inner, link: TelegramLink):
        self.inner = inner
        self.link = link
        self.dispatcher = inner.dispatcher

    def dispatch(self, api, update: dict, via: str = TYPED):
        inbound = parse_update(update)
        if inbound is None:
            return None
        return self.link.handle(self.dispatcher, api, inbound, via)


def install(app, config) -> Optional[TelegramLink]:
    """擁有者是保留號段（沒有真的 Telegram id）而且有 Telegram token 才啟用；其他安裝什麼都不改。"""
    from isdtelekit.host.app import telegram_api
    from synox.discord.pairing import WebPairing
    if not getattr(config, "has_token", False) or int(getattr(config, "owner_id", 0) or 0) < BASE:
        return None
    api = telegram_api(app.home)
    if api is None:
        return None
    try:
        identities = Identities(config.path("identities.json"))
    except IdentityFileError as e:
        logging.error("[TELEGRAM] %s", e)
        return None
    pairing = WebPairing()
    link = TelegramLink(identities, config.owner_id, pairing)
    link.patch_api(api)
    app.telegram = LinkedEntry(app.telegram, link)
    app.extras["telegram_link"] = link
    app.extras["telegram_pairing"] = pairing
    return link
