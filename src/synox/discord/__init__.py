"""
Discord 通道（私訊收訊＋回覆＋按鈕；一個程序可以開好幾個 bot）。

config.json（兩種寫法，見 synox/discord/bots.py）：
    "channels": {"discord": {"enabled": true, "bot_token": "vault:discord_bot_token"}}          一個 bot（＝bots.default）
    "channels": {"discord": {"bots": {"synox": {"surface": "dm"}, "helper": {"surface": "dm", "packs": ["dict"]}}}}

- install(app, config, vault)：每個私訊型 bot 一個 DiscordChannel（回覆用「收到訊息的那個 bot」的 token）和一條 Gateway
  （on_start 登記到 app.hub：名字 "discord:<名字>"，舊寫法維持 "discord"；受監看、掛了自己退避重啟）；
  app.home 換成 MultiHome（主動通知依對象走 Telegram 或 Discord；Discord 走這個人最近私訊過的 bot，沒有就第一個私訊型）。
  終端機模式不呼叫 on_start，所以不會連 Discord。
- bot 範圍（PERM-4）：每個 bot 的收訊在 policy.using_bot(spec) 裡進 dispatcher，decide、/help、群組選單、按鈕、
  AI 工具清單都照那個 bot 的 packs／max_effect／ai 過濾（synox/policy.py）；/bot_status 列每個 bot 的有效 pack（scope.py）。
- surface=channel 的 bot（PERM-5）：RoomEntry 收 guilds[g].channels 列出的頻道裡 trigger 命中的訊息
  （events.parse_room_event），chat_id 是頻道的負號內部 id；回覆用收到訊息的那個 bot 送回那個頻道、引用發話者那則訊息；
  按鈕只有發話者能按；（頻道, 人）每分鐘 rate_per_minute 則，超過靜默略過；Discord 身分組照 role_map 給這次請求的有效角色
  （上限成員，不寫回 users.json）。頻道裡能用什麼由 policy.decide 決定（pack 的 surfaces／data、DANGER 永遠拒、WRITE 限 shared）。
  頻道型 bot 不加進 DiscordBots（主動通知只走私訊型 bot）。
- 身分：synox.identity（data/identities.json）。同一個 Discord 帳號對任何 bot 都是同一個內部 id。
  陌生的 Discord 帳號拿到保留號段的新 id（伺服器版＝訪客；個人版＝被拒）；
  擁有者用 `python -m synox discord pair`（私訊 bot 六位數配對碼）把自己的 Discord 帳號接到 owner_id。
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict, deque
from typing import Callable, Dict, List, Optional

from isdtelekit.core.jsonstore import load_json, save_json
from isdtelekit.host.app import telegram_api

from synox import policy
from synox.discord import bots as bot_specs
from synox.discord.bots import CHANNEL, BotSpec
from synox.discord.events import DISCORD, DISCORD_ROOM, pairing_sender, parse_event, parse_room_event
from synox.discord.gateway import CHANNEL_INTENTS, INTENTS, Gateway
from synox.discord.rest import DiscordChannel
from synox.identity import BASE, Identities

VAULT_NAME = bot_specs.VAULT_BASE
NO_GUILDS = "頻道型 bot 沒有列任何伺服器／頻道（guilds），不會收到訊息；見 docs/discord.md「頻道型 bot」"
ONLY_SPEAKER = "只有發這個指令的人能按這些按鈕。"
CHAT_IN_DM = "頻道裡只收指令（例如 @我 /help）；想聊天請私訊。"
_BY_MESSAGE = {"edit_message_text", "remove_buttons", "delete_message", "pin_message", "unpin_message"}


def settings(config) -> dict:
    raw = getattr(config, "raw", None) or {}
    d = (raw.get("channels") or {}).get("discord") or {}
    return d if isinstance(d, dict) else {}


def specs(config) -> List[BotSpec]:
    """要開的 bot（設定錯丟 ConfigError；SynoxConfig.from_dict 已先檢查過）。"""
    return bot_specs.active(settings(config))


def all_specs(config) -> List[BotSpec]:
    """設定裡寫的每個 bot（含關著的），給 /bot_status、doctor 列。"""
    return bot_specs.parse(settings(config))


def enabled(config) -> bool:
    return bool(specs(config))


def resolve_token(spec: BotSpec, vault) -> str:
    from synox.llm.factory import resolve_secret
    return resolve_secret(spec.token, vault).strip()


def find_spec(config, name: Optional[str] = None) -> Optional[BotSpec]:
    return bot_specs.find(bot_specs.parse(settings(config)), name)


def bot_token(config, vault, name: Optional[str] = None) -> str:
    """某個 bot 的 token（name 沒給＝default／第一個私訊型）。找不到這個 bot 丟 LookupError。"""
    spec = bot_specs.find(specs(config), name)
    if spec is None:
        raise LookupError(f"config.json 的 channels.discord 沒有開著、叫 {name} 的 bot" if name
                          else "config.json 的 channels.discord 沒有私訊型的 bot")
    return resolve_token(spec, vault)


class DiscordBots:
    """所有開著的私訊型 bot：名字 → DiscordChannel，記住「每個人最近私訊的是哪個 bot」（data/discord_last_bot.json）
    和「哪則訊息是哪個 bot 送的」（之後改訊息、拿掉按鈕要用同一個 bot），給 MultiHome 挑主動通知走哪個。"""

    MESSAGES_KEPT = 1000

    def __init__(self, path: Optional[str] = None):
        self.channels: "OrderedDict[str, DiscordChannel]" = OrderedDict()
        self.path = path
        self._lock = threading.Lock()
        data = load_json(path, {}) if path else {}
        self._last: Dict[int, str] = {}
        for k, v in (data.items() if isinstance(data, dict) else ()):
            try:
                self._last[int(k)] = str(v)
            except (TypeError, ValueError):
                continue
        self._sent: "OrderedDict[int, str]" = OrderedDict()

    def add(self, name: str, channel: DiscordChannel) -> None:
        self.channels[name] = channel

    def first(self) -> Optional[DiscordChannel]:
        return next(iter(self.channels.values()), None)

    def saw_dm(self, uid: int, name: str) -> None:
        with self._lock:
            if self._last.get(int(uid)) == name:
                return
            self._last[int(uid)] = name
            snapshot = {str(k): v for k, v in self._last.items()}
        if self.path:
            try:
                save_json(self.path, snapshot)
            except OSError:
                logging.warning("[DISCORD] could not save %s", self.path)

    def last_bot(self, uid) -> Optional[str]:
        try:
            return self._last.get(int(uid))
        except (TypeError, ValueError):
            return None

    def sent_by(self, message_id, name: str) -> None:
        try:
            mid = int(message_id)
        except (TypeError, ValueError):
            return
        if not mid:
            return
        with self._lock:
            self._sent[mid] = name
            while len(self._sent) > self.MESSAGES_KEPT:
                self._sent.popitem(last=False)

    def name_of(self, channel) -> Optional[str]:
        return next((n for n, c in self.channels.items() if c is channel), None)

    def pick(self, uid, message_id=None) -> Optional[DiscordChannel]:
        """送給 uid 用哪個 bot：這則訊息是誰送的 → 這個人最近私訊的 → 第一個（config 順序的第一個私訊型）。"""
        if message_id is not None:
            try:
                name = self._sent.get(int(message_id))
            except (TypeError, ValueError):
                name = None
            if name in self.channels:
                return self.channels[name]
        name = self.last_bot(uid)
        if name in self.channels:
            return self.channels[name]
        return self.first()

    def can_reach(self, uid) -> bool:
        return any(c.can_reach(uid) for c in self.channels.values())


class MultiHome:
    """主動通知的管子：依收件人走 Telegram 或 Discord。
    - 保留號段的 id（只有 Discord 的人）→ Discord；
    - 其他 id → Telegram（有 token 時）；沒有 Telegram 但這個 id 接了 Discord（例如擁有者只用 Discord）→ Discord；
    - 都不是 → 原本的 home（只記 log／測試的假管子）。
    走 Discord 時挑哪個 bot：DiscordBots.pick（這個人最近私訊過的私訊型 bot，沒有就第一個）。"""

    channel_name = "multi"

    def __init__(self, primary, discord):
        self.primary = primary
        if isinstance(discord, DiscordChannel):           # 舊用法：只有一個 bot
            one = DiscordBots()
            one.add(bot_specs.DEFAULT, discord)
            discord = one
        self.bots: DiscordBots = discord

    @property
    def discord(self) -> Optional[DiscordChannel]:
        return self.bots.first()

    @property
    def telegram_api(self):
        return telegram_api(self.primary)

    def _pick(self, chat_id, message_id=None):
        try:
            uid = int(chat_id)
        except (TypeError, ValueError):
            return self.primary
        if uid >= BASE:
            return self.bots.pick(uid, message_id) or self.primary
        if self.telegram_api is not None:
            return self.primary
        return (self.bots.pick(uid, message_id) or self.primary) if self.bots.can_reach(uid) else self.primary

    def _record(self, target, out):
        if isinstance(target, DiscordChannel) and isinstance(out, dict) and out.get("ok"):
            name = self.bots.name_of(target)
            if name:
                self.bots.sent_by((out.get("result") or {}).get("message_id"), name)
        return out

    def send_message(self, chat_id, text, reply_markup=None, **kw):
        target = self._pick(chat_id)
        return self._record(target, target.send_message(chat_id, text, reply_markup=reply_markup, **kw))

    def __getattr__(self, name):
        if name.startswith("_") or name in ("primary", "bots"):
            raise AttributeError(name)

        def call(chat_id=None, *a, **kw):
            message_id = a[0] if (a and name in _BY_MESSAGE) else kw.get("message_id")
            target = self._pick(chat_id, message_id) if chat_id is not None else self.primary
            fn = getattr(target, name, None)
            return self._record(target, fn(chat_id, *a, **kw)) if fn is not None else {"ok": False}
        return call


class DiscordEntry:
    """Gateway 事件 → Inbound → dispatcher.handle(DiscordChannel, …)。按鈕沒被回應的話自動默默確認（Discord 要 3 秒內回）。
    channel 是「收到這個事件的 bot」：回覆一律用它的 token。
    spec 是這個 bot 的設定（PERM-4）：dispatcher.handle 在 policy.using_bot(spec) 裡跑，所以 decide、/help、
    群組選單、按鈕、AI 工具清單都照這個 bot 的 packs／max_effect／ai 過濾。spec=None＝不限制。"""

    def __init__(self, dispatcher, identities: Identities, channel: DiscordChannel, *, name: str = bot_specs.DEFAULT,
                 bots: Optional[DiscordBots] = None, spec: Optional[BotSpec] = None):
        self.dispatcher = dispatcher
        self.identities = identities
        self.channel = channel
        self.name = name
        self.bots = bots
        self.spec = spec

    def _handle(self, inbound):
        with policy.using_bot(self.spec):
            return self.dispatcher.handle(self.channel, inbound)

    def on_dispatch(self, event: str, d: dict):
        parsed = parse_event(event, d, lambda ext: self.identities.resolve(DISCORD, ext))
        if parsed is None:
            return None
        inbound, channel_id = parsed
        self.channel.remember_dm(inbound.user_id, channel_id)
        if self.bots is not None:
            self.bots.saw_dm(inbound.user_id, self.name)
        if inbound.button is None:
            return self._handle(inbound)
        cq_id = inbound.button.cq_id
        try:
            return self._handle(inbound)
        finally:
            if not self.channel.take_answered(cq_id):
                self.channel.answer_callback_query(cq_id)
                self.channel.take_answered(cq_id)


class RoomReply:
    """頻道裡這一則訊息的回覆管子（包住收到訊息的那個 bot 的 DiscordChannel）：
    送到這個頻道的訊息都引用發話者那則訊息（提及他），並記下「這則 bot 的訊息是回給誰的」，按鈕只有那個人能按。
    送到別的地方（例如私訊某人）照原本的 channel。"""

    def __init__(self, channel: DiscordChannel, room: int, reply_to: str, speaker: int, record: Callable[[int, int], None]):
        self._channel = channel
        self._room = int(room)
        self._reply_to = reply_to
        self._speaker = int(speaker)
        self._record = record
        self.channel_name = channel.channel_name

    def _here(self, chat_id) -> bool:
        try:
            return int(chat_id) == self._room
        except (TypeError, ValueError):
            return False

    def _keep(self, chat_id, out, message_id=None):
        if self._here(chat_id) and isinstance(out, dict) and out.get("ok"):
            mid = message_id if message_id is not None else (out.get("result") or {}).get("message_id")
            try:
                if int(mid or 0):
                    self._record(int(mid), self._speaker)
            except (TypeError, ValueError):
                pass
        return out

    def send_message(self, chat_id, text, reply_markup=None, **kw):
        if self._here(chat_id) and self._reply_to:
            kw.setdefault("reply_to", self._reply_to)
        return self._keep(chat_id, self._channel.send_message(chat_id, text, reply_markup=reply_markup, **kw))

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None, **kw):
        return self._keep(chat_id, self._channel.edit_message_text(chat_id, message_id, text, reply_markup=reply_markup,
                                                                   **kw), message_id)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._channel, name)


class RoomThrottle:
    """（頻道, 人）每分鐘最多 limit 則；超過回 False（呼叫端靜默略過、記一行 log）。"""

    WINDOW = 60.0

    def __init__(self, limit: int, clock: Callable[[], float] = time.monotonic):
        self.limit = max(1, int(limit))
        self._clock = clock
        self._seen: Dict[tuple, deque] = {}
        self._lock = threading.Lock()

    def allow(self, room: int, uid: int) -> bool:
        now = self._clock()
        with self._lock:
            q = self._seen.setdefault((int(room), int(uid)), deque())
            while q and now - q[0] >= self.WINDOW:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            if len(self._seen) > 5000:                 # 很久沒講話的清掉
                for key in [k for k, v in self._seen.items() if not v or now - v[-1] >= self.WINDOW]:
                    self._seen.pop(key, None)
            return True


class RoomEntry:
    """頻道型 bot（PERM-5）：Gateway 事件 → parse_room_event → dispatcher.handle(RoomReply, …)。
    policy.using_bot(spec)（頻道規則、pack 範圍、max_effect）＋ policy.using_role_floor（role_map 來的角色）裡跑。"""

    SPEAKERS_KEPT = 1000

    def __init__(self, dispatcher, identities: Identities, channel: DiscordChannel, *, name: str, spec: BotSpec,
                 clock: Callable[[], float] = time.monotonic):
        self.dispatcher = dispatcher
        self.identities = identities
        self.channel = channel
        self.name = name
        self.spec = spec
        self.bot_id: Optional[str] = None
        self.throttle = RoomThrottle(spec.rate_per_minute, clock)
        self._speakers: "OrderedDict[int, int]" = OrderedDict()
        self._lock = threading.Lock()

    # ── 狀態 ─────────────────────────────────────────────────────────

    def on_ready(self, user: dict) -> None:
        bot_id = str((user or {}).get("id") or "")
        if bot_id:
            self.bot_id = bot_id

    def _record(self, message_id: int, speaker: int) -> None:
        with self._lock:
            self._speakers[int(message_id)] = int(speaker)
            self._speakers.move_to_end(int(message_id))
            while len(self._speakers) > self.SPEAKERS_KEPT:
                self._speakers.popitem(last=False)

    def speaker_of(self, message_id) -> Optional[int]:
        try:
            return self._speakers.get(int(message_id))
        except (TypeError, ValueError):
            return None

    def role_floor(self, guild_id: str, roles: List[str]):
        role_map = (self.spec.guild(guild_id) or {}).get("role_map") or {}
        names = [role_map[r] for r in roles if r in role_map]
        return policy.role_floor_from(self.dispatcher.registry.roles, names) if names else None

    # ── 收訊 ─────────────────────────────────────────────────────────

    def _handle(self, api, inbound, floor):
        with policy.using_bot(self.spec), policy.using_role_floor(floor):
            return self.dispatcher.handle(api, inbound)

    def _someone_elses_conversation(self, inbound) -> bool:
        """這個頻道有一段別人的問答進行中，而這則會被它吃掉（不是樹上的指令）→ 不讓別人插嘴。"""
        conv = getattr(self.dispatcher, "conv_manager", None)
        session = conv.get(inbound.chat_id) if conv is not None else None
        if session is None or int(session.user_tg_id) == int(inbound.user_id):
            return False
        text = inbound.text or ""
        return not text.startswith("/") or self.dispatcher.registry.resolve(text)[0] is None

    def on_dispatch(self, event: str, d: dict):
        ev = parse_room_event(event, d, spec=self.spec, bot_id=self.bot_id,
                              resolve=lambda ext: self.identities.resolve(DISCORD, ext),
                              resolve_room=lambda cid: self.identities.resolve_room(DISCORD_ROOM, cid))
        if ev is None:
            return None
        inbound = ev.inbound
        self.channel.remember_room(inbound.chat_id, ev.channel_id)
        floor = self.role_floor(ev.guild_id, ev.roles)
        if inbound.button is not None:
            return self._button(inbound, floor)
        if not self.throttle.allow(inbound.chat_id, inbound.user_id):
            logging.info("[DISCORD] %s throttled: room %s user %s (over %s/min)", self.name, inbound.chat_id,
                         inbound.user_id, self.throttle.limit)
            return None
        if self._someone_elses_conversation(inbound):
            logging.info("[DISCORD] %s ignored: room %s has another user's conversation", self.name, inbound.chat_id)
            return None
        api = RoomReply(self.channel, inbound.chat_id, ev.message_id, inbound.user_id, self._record)
        route = self._handle(api, inbound, floor)
        if getattr(route, "reason", None) == "group":            # 被 @ 了但不是指令：頻道 AI 還沒做（PERM-6）
            api.send_message(inbound.chat_id, CHAT_IN_DM)
        return route

    def _button(self, inbound, floor):
        cb = inbound.button
        try:
            if self.speaker_of(cb.message_id) != int(cb.clicker_id):     # 不是發話者（或不認得這則）：不給按
                self.channel.answer_callback_query(cb.cq_id, ONLY_SPEAKER)
                return None
            api = RoomReply(self.channel, inbound.chat_id, "", self.speaker_of(cb.message_id), self._record)
            return self._handle(api, inbound, floor)
        finally:
            if not self.channel.take_answered(cb.cq_id):
                self.channel.answer_callback_query(cb.cq_id)
                self.channel.take_answered(cb.cq_id)


def install(app, config, vault) -> Optional[DiscordChannel]:
    """開好每個 bot（私訊型、頻道型）；回第一個私訊型的 DiscordChannel（沒有回 None）。有設定 Discord 就掛 /bot_status。"""
    from synox.discord import scope
    scope.install(app, config)
    wanted = specs(config)
    if not wanted:
        return None
    identities = Identities(config.path("identities.json"))
    app.extras["identities"] = identities
    errors: Dict[str, str] = {}
    app.extras["discord_errors"] = errors
    bots = DiscordBots(config.path("discord_last_bot.json"))
    entries: Dict[str, object] = {}
    gateways = []
    for spec in wanted:
        if spec.surface == CHANNEL and not spec.channel_count():
            errors[spec.name] = NO_GUILDS
            logging.warning("[DISCORD] bot %s: %s", spec.name, NO_GUILDS)
            continue
        try:
            token = resolve_token(spec, vault)
        except Exception as e:                    # 保管箱沒有 token：其他 bot、其他通道照跑，doctor／log 說原因
            logging.error("[DISCORD] bot %s: %s", spec.name, e)
            errors[spec.name] = str(e)
            continue
        if not token:
            errors[spec.name] = ("channels.discord.bot_token 是空的" if spec.legacy
                                 else f"bots.{spec.name}.token（{spec.token}）是空的")
            continue
        if any(token == t for _, t, _ in gateways):
            errors[spec.name] = "跟另一個 bot 的 token 一樣（一個 bot 只能有一條連線）"
            continue
        channel = DiscordChannel(token, identities)
        if spec.surface == CHANNEL:                 # 不加進 bots：主動通知只走私訊型
            entry = RoomEntry(app.dispatcher, identities, channel, name=spec.name, spec=spec)
        else:
            bots.add(spec.name, channel)
            entry = DiscordEntry(app.dispatcher, identities, channel, name=spec.name, bots=bots, spec=spec)
        entries[spec.name] = entry
        gateways.append((spec, token, entry))
    app.extras["discord_bots"] = bots
    app.extras["discord_entries"] = entries
    app.extras["discord_specs"] = {s.name: s for s in wanted}
    if errors:
        legacy_only = len(errors) == 1 and wanted[0].legacy
        app.extras["discord_error"] = (next(iter(errors.values())) if legacy_only
                                       else "；".join(f"bot {n}：{e}" for n, e in errors.items()))
    if not gateways:
        return None
    owner_discord = str(settings(config).get("owner_user_id") or "").strip()
    if owner_discord and identities.lookup(DISCORD, owner_discord) is None:
        identities.bind(DISCORD, owner_discord, config.owner_id)
    first = bots.first()
    app.extras["discord"] = first
    app.extras["discord_entry"] = entries[gateways[0][0].name]
    if bots.channels:
        app.home = MultiHome(app.home, bots)

    def make(token, entry, label, spec):
        if spec.surface == CHANNEL:
            return Gateway(token, entry.on_dispatch, label=label, intents=CHANNEL_INTENTS, on_ready=entry.on_ready)
        return Gateway(token, entry.on_dispatch, label=label, intents=INTENTS)

    def start(a):
        for spec, token, entry in gateways:
            a.hub.add(spec.hub_name, lambda t=token, e=entry, n=spec.hub_name, s=spec: make(t, e, n, s))
            a.hub.get(spec.hub_name).start()
    app.on_start.insert(0, start)
    return first


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


def pair_owner(config, vault, *, code: Optional[str] = None, out=print, bot: Optional[str] = None, **kw) -> int:
    """python -m synox discord pair [--bot 名字]：印出配對碼 → 等私訊 → 把那個 Discord 帳號接到 owner_id。
    身分對所有 bot 共用，所以配對一次就好（用哪個私訊型 bot 都可以；沒指定＝default／第一個私訊型）。"""
    from synox.wizard.telegram_probe import new_pairing_code
    if not enabled(config):
        out("❌ config.json 還沒有開 Discord（channels.discord）。看 docs/discord.md。")
        return 2
    spec = bot_specs.find(specs(config), bot)
    if spec is None:
        out(f"❌ config.json 的 channels.discord 沒有開著、叫 {bot} 的 bot。" if bot else "❌ 沒有私訊型的 bot 可以配對。")
        return 2
    if spec.surface == CHANNEL:
        out(f"❌ bot {spec.name} 是頻道型的；配對要用私訊型的 bot（--bot 換一個）。")
        return 2
    try:
        token = resolve_token(spec, vault)
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
