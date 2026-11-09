"""
Discord 通道（最小版：私訊收訊＋回覆＋按鈕）。

config.json：
    "channels": {"discord": {"enabled": true, "bot_token": "vault:discord_bot_token"}}

- install(app, config, vault)：有開 Discord 就做出 DiscordChannel、把 app.home 換成 MultiHome（主動通知依對象走
  Telegram 或 Discord）、在 on_start 登記 Gateway 迴圈到 app.hub（名字 "discord"，受監看、掛了自己退避重啟）。
  終端機模式不呼叫 on_start，所以不會連 Discord。
- 身分：synox.identity（data/identities.json）。陌生的 Discord 帳號拿到保留號段的新 id（伺服器版＝訪客；個人版＝被拒）；
  擁有者用 `python -m synox pair-discord`（私訊 bot 六位數配對碼）把自己的 Discord 帳號接到 owner_id。
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from isdtelekit.host.app import telegram_api

from synox.discord.events import DISCORD, pairing_sender, parse_event
from synox.discord.gateway import Gateway
from synox.discord.rest import DiscordChannel
from synox.identity import BASE, Identities

VAULT_NAME = "discord_bot_token"


def settings(config) -> dict:
    raw = getattr(config, "raw", None) or {}
    d = (raw.get("channels") or {}).get("discord") or {}
    return d if isinstance(d, dict) else {}


def enabled(config) -> bool:
    d = settings(config)
    return bool(d.get("enabled", bool(d.get("bot_token"))))


def bot_token(config, vault) -> str:
    from synox.llm.factory import resolve_secret
    return resolve_secret(settings(config).get("bot_token") or f"vault:{VAULT_NAME}", vault).strip()


class MultiHome:
    """主動通知的管子：依收件人走 Telegram 或 Discord。
    - 保留號段的 id（只有 Discord 的人）→ Discord；
    - 其他 id → Telegram（有 token 時）；沒有 Telegram 但這個 id 接了 Discord（例如擁有者只用 Discord）→ Discord；
    - 都不是 → 原本的 home（只記 log／測試的假管子）。"""

    channel_name = "multi"

    def __init__(self, primary, discord: DiscordChannel):
        self.primary = primary
        self.discord = discord

    @property
    def telegram_api(self):
        return telegram_api(self.primary)

    def _pick(self, chat_id):
        try:
            uid = int(chat_id)
        except (TypeError, ValueError):
            return self.primary
        if uid >= BASE:
            return self.discord
        if self.telegram_api is not None:
            return self.primary
        return self.discord if self.discord.can_reach(uid) else self.primary

    def send_message(self, chat_id, text, reply_markup=None, **kw):
        return self._pick(chat_id).send_message(chat_id, text, reply_markup=reply_markup, **kw)

    def __getattr__(self, name):
        if name.startswith("_") or name in ("primary", "discord"):
            raise AttributeError(name)

        def call(chat_id=None, *a, **kw):
            target = self._pick(chat_id) if chat_id is not None else self.primary
            fn = getattr(target, name, None)
            return fn(chat_id, *a, **kw) if fn is not None else {"ok": False}
        return call


class DiscordEntry:
    """Gateway 事件 → Inbound → dispatcher.handle(DiscordChannel, …)。按鈕沒被回應的話自動默默確認（Discord 要 3 秒內回）。"""

    def __init__(self, dispatcher, identities: Identities, channel: DiscordChannel):
        self.dispatcher = dispatcher
        self.identities = identities
        self.channel = channel

    def on_dispatch(self, event: str, d: dict):
        parsed = parse_event(event, d, lambda ext: self.identities.resolve(DISCORD, ext))
        if parsed is None:
            return None
        inbound, channel_id = parsed
        self.channel.remember_dm(inbound.user_id, channel_id)
        if inbound.button is None:
            return self.dispatcher.handle(self.channel, inbound)
        cq_id = inbound.button.cq_id
        try:
            return self.dispatcher.handle(self.channel, inbound)
        finally:
            if not self.channel.take_answered(cq_id):
                self.channel.answer_callback_query(cq_id)
                self.channel.take_answered(cq_id)


def install(app, config, vault) -> Optional[DiscordChannel]:
    if not enabled(config):
        return None
    identities = Identities(config.path("identities.json"))
    app.extras["identities"] = identities
    try:
        token = bot_token(config, vault)
    except Exception as e:                        # 保管箱沒有 token：其他通道照跑，doctor／log 說原因
        logging.error("[DISCORD] %s", e)
        app.extras["discord_error"] = str(e)
        return None
    if not token:
        app.extras["discord_error"] = "channels.discord.bot_token 是空的"
        return None
    channel = DiscordChannel(token, identities)
    owner_discord = str(settings(config).get("owner_user_id") or "").strip()
    if owner_discord and identities.lookup(DISCORD, owner_discord) is None:
        identities.bind(DISCORD, owner_discord, config.owner_id)
    app.extras["discord"] = channel
    app.home = MultiHome(app.home, channel)
    entry = DiscordEntry(app.dispatcher, identities, channel)
    app.extras["discord_entry"] = entry

    def start(a):
        a.hub.add(DISCORD, lambda: Gateway(token, entry.on_dispatch))
        a.hub.get(DISCORD).start()
    app.on_start.insert(0, start)
    return channel


# ── 擁有者配對（照 wizard/telegram_probe 的流程：私訊 bot 六位數字）────────────

def wait_for_pairing(token: str, code: str, *, timeout: float = 900.0, connect=None, http=None,
                     stop: Optional[threading.Event] = None) -> Optional[dict]:
    """開一條 Gateway 連線，等「私訊傳了配對碼」的人；認到回 {"id", "username", "channel_id"}，逾時回 None。"""
    found: dict = {}
    kw = {"connect": connect} if connect is not None else {}
    gw: Gateway

    def on_dispatch(event, d):
        who = pairing_sender(event, d, code)
        if who and not found:
            found.update(who)
            gw.stop()
    gw = Gateway(token, on_dispatch, **kw)
    stop = stop or threading.Event()
    timer = threading.Timer(timeout, gw.stop)
    timer.daemon = True
    timer.start()
    watcher = threading.Thread(target=lambda: (stop.wait(), gw.stop()), daemon=True)
    watcher.start()
    try:
        gw.run_forever()
    finally:
        timer.cancel()
    if not found:
        return None
    if found.get("channel_id"):
        api = DiscordChannel(token, identities=None, http=http)
        api.remember_dm(0, found["channel_id"])
        api.send_message(0, "✅ 配對成功！之後直接私訊我就可以了。")
    return found


def pair_owner(config, vault, *, code: Optional[str] = None, out=print, **kw) -> int:
    """python -m synox pair-discord：印出配對碼 → 等私訊 → 把那個 Discord 帳號接到 owner_id。"""
    from synox.wizard.telegram_probe import new_pairing_code
    if not enabled(config):
        out("❌ config.json 還沒有開 Discord（channels.discord）。看 docs/discord.md。")
        return 2
    try:
        token = bot_token(config, vault)
    except Exception as e:
        out(f"❌ {e}")
        return 2
    code = code or new_pairing_code()
    out(f"在 Discord 私訊你的 bot，傳這六個數字：{code}　（15 分鐘內有效；先把正在跑的 SYNOX 關掉比較不會搶訊息）")
    who = wait_for_pairing(token, code, **kw)
    if not who:
        out("⌛ 沒有收到配對碼，沒有改任何東西。")
        return 1
    identities = Identities(config.path("identities.json"))
    old = identities.lookup(DISCORD, who["id"])
    if old is not None and old != config.owner_id:
        identities.unbind(DISCORD, who["id"])     # 這個帳號之前當陌生人拿過號碼：改接到擁有者
    previous = identities.external(DISCORD, config.owner_id)
    if previous and previous != who["id"]:
        identities.unbind(DISCORD, previous)
    identities.bind(DISCORD, who["id"], config.owner_id)
    out(f"✅ 已把 Discord 帳號 {who.get('username') or who['id']} 接到擁有者（id {config.owner_id}）。")
    return 0
