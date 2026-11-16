"""
送達層的四個管道（docs/adr/0028 §3.3 的 ChannelAdapter 實作）＋網頁通知清單那一則（anchor）＋「這一則送哪裡」。

**包住 hub 現有的送法，不另寫一套**：誰接得到（hub.telegram_ok／discord_ok／web_ok）、哪一類關掉了哪裡（hub.off_for）、
按鈕長什麼樣子（hub._chat_markup）都直接用 Hub 的。差別只在：這裡看每一條送出去的「結果」，分成
SENT／FAILED（種類）／SKIPPED，讓 Outbox 決定要不要重試。

- web：通知清單一定存一則（anchor；聊天通道的按鈕 ntf:<動作>:<id> 要找得回來），網頁關掉的就藏起來（跟 hub.notify 一樣）。
- telegram／discord：送訊息帶按鈕；回 {"ok": false} 依 status 分類（429＝rate_limited 照 retry_after、403＝blocked、
  401／404＝bad_token、重複的字＝duplicate_text，重試時字尾加「（第 N 次）」）。
- chat：兩個聊天通道都沒有時交給 app.home（終端機、測試的假管子），跟 hub.notify 的退路一樣。
- desktop：寫 ShowCard 到 data/remind/desk/to_win，必要時開視窗程式；回 QUEUED，等視窗寫 shown 才算 SENT。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from synox.notify import desk as deskmod
from synox.notify.delivery import (CHAT, DESKTOP, DISCORD, FAILED, QUEUED, SENT, SKIPPED, TELEGRAM, WEB,
                                   DeliveryRecord, DeliveryResult, Message)

HUB_CHANNELS = (WEB, TELEGRAM, DISCORD)


def classify(channel: str, res, chat_id) -> DeliveryResult:
    """聊天通道 send_message 的回傳 → DeliveryResult（不是 dict＝沒有回報格式的假管子，當作成功）。"""
    if not isinstance(res, dict):
        return DeliveryResult(channel, SENT)
    if res.get("ok", True):
        mid = (res.get("result") or {}).get("message_id") if isinstance(res.get("result"), dict) else None
        return DeliveryResult(channel, SENT, ref={"chat_id": chat_id, "message_id": mid} if mid is not None else {})
    status = res.get("status")
    retry_after = res.get("retry_after")
    if res.get("error") == "duplicate":
        return DeliveryResult(channel, FAILED, error="duplicate_text")
    if retry_after or status == 429:
        return DeliveryResult(channel, FAILED, error="rate_limited",
                              retry_after=float(retry_after) if retry_after else None)
    if status == 403:
        return DeliveryResult(channel, FAILED, error="blocked")
    if status in (401, 404):
        return DeliveryResult(channel, FAILED, error="bad_token")
    if status is None or (isinstance(status, int) and status >= 500):
        return DeliveryResult(channel, FAILED, error="network")
    return DeliveryResult(channel, FAILED, error="unknown")


def retry_text(msg: Message) -> str:
    """上一次被當成重複的字擋掉：這次字尾加「（第 N 次）」。"""
    if (msg.data or {}).get("_last_error") == "duplicate_text":
        return f"{msg.text}（第 {int(msg.data.get('_try') or 2)} 次）"
    return msg.text


def _markup(hub, msg: Message) -> Optional[dict]:
    nid = (msg.data or {}).get("nid")
    return hub._chat_markup(msg.actions or [], nid) if nid is not None else None


def _send(target, uid, text, markup):
    return target.send_message(uid, text, reply_markup=markup) if markup else target.send_message(uid, text)


def _edit(target, rec: DeliveryRecord, note: str) -> bool:
    cid, mid = rec.ref.get("chat_id"), rec.ref.get("message_id")
    if target is None or mid is None:
        return False
    if note and hasattr(target, "edit_message_text"):
        target.edit_message_text(cid, mid, note)
    if hasattr(target, "remove_buttons"):
        target.remove_buttons(cid, mid)
    return True


# ── 網頁通知清單那一則（anchor）──────────────────────────────────────────

class HubAnchor:
    """每一則 deliver 都在通知清單存一則（跟 hub.notify 一樣：網頁關了就藏起來、標已讀）。
    data["remind"] = {"rid", "occurrence", "key"}：按鈕回頭找得到是哪一個提醒的哪一次。"""

    def __init__(self, hub):
        self.hub = hub

    def prepare(self, msg: Message, channels: List[str]) -> Dict[str, Any]:
        hub, uid = self.hub, int(msg.uid)
        hidden = WEB not in channels or not hub.web_ok()
        data = dict(msg.data or {})
        if msg.ref is not None:
            data["remind"] = {"rid": int(msg.ref.rid), "occurrence": msg.ref.occurrence, "key": msg.key}
        if hidden:
            data["hidden"] = True
        item = hub.store.add(uid, str(msg.text), kind=msg.kind, level=msg.level, actions=msg.actions, data=data)
        if hidden:
            hub.store.update(uid, item["id"], read=True)
        try:
            hub.store.remember_key(uid, msg.key)          # 別處用 hub.notify(key=同一個) 也會被去重擋下
        except Exception as e:
            logging.warning("[NOTIFY] remember key failed: %s", type(e).__name__)
        return {"nid": item["id"]}

    def finish(self, uid: int, extra: Dict[str, Any], note: str) -> None:
        nid = extra.get("nid")
        if nid is not None:
            more = {"resolved": note} if note else {}
            self.hub.store.update(int(uid), int(nid), actions=[], read=True, **more)


# ── 管道 ─────────────────────────────────────────────────────────────────

class WebAdapter:
    name = WEB

    def __init__(self, hub):
        self.hub = hub

    def available(self, uid: int) -> bool:
        return self.hub.web_ok()

    def send(self, msg: Message) -> DeliveryResult:
        nid = (msg.data or {}).get("nid")
        if nid is None:                                   # 清單那一則沒存成（磁碟、保管箱）：等下一次
            return DeliveryResult(WEB, FAILED, error="unknown")
        return DeliveryResult(WEB, SENT, ref={"nid": nid})

    def retract(self, record: DeliveryRecord, note: str) -> bool:
        return True                                       # 清單那一則由 HubAnchor.finish 收（按鈕拿掉、標已讀）


class TelegramAdapter:
    name = TELEGRAM

    def __init__(self, hub):
        self.hub = hub

    def available(self, uid: int) -> bool:
        return self.hub.telegram_ok(uid)

    def send(self, msg: Message) -> DeliveryResult:
        api = self.hub._telegram_api()
        if api is None:
            return DeliveryResult(TELEGRAM, SKIPPED)
        return classify(TELEGRAM, _send(api, int(msg.uid), retry_text(msg), _markup(self.hub, msg)), int(msg.uid))

    def retract(self, record: DeliveryRecord, note: str) -> bool:
        return _edit(self.hub._telegram_api(), record, note)


class DiscordAdapter:
    name = DISCORD

    def __init__(self, hub):
        self.hub = hub

    def available(self, uid: int) -> bool:
        return self.hub.discord_ok(uid)

    def send(self, msg: Message) -> DeliveryResult:
        bots = self.hub._discord_bots()
        if bots is None:
            return DeliveryResult(DISCORD, SKIPPED)
        uid = int(msg.uid)
        target = bots.pick(uid)
        res = _send(target, uid, retry_text(msg), _markup(self.hub, msg))
        record = getattr(getattr(self.hub.app, "home", None), "_record", None)
        if record is not None:
            try:
                record(target, res)
            except Exception:
                pass
        return classify(DISCORD, res, uid)

    def retract(self, record: DeliveryRecord, note: str) -> bool:
        bots = self.hub._discord_bots()
        if bots is None:
            return False
        try:
            target = bots.pick(int(record.ref.get("chat_id") or 0), message_id=record.ref.get("message_id"))
        except TypeError:
            target = bots.pick(int(record.ref.get("chat_id") or 0))
        return _edit(target, record, note)


class ChatAdapter:
    """兩個聊天通道都沒有時的退路：app.home（只記 log 的管子、終端機、測試的假管子）。"""
    name = CHAT

    def __init__(self, hub):
        self.hub = hub

    def available(self, uid: int) -> bool:
        return getattr(self.hub.app, "home", None) is not None

    def send(self, msg: Message) -> DeliveryResult:
        home = self.hub.app.home
        return classify(CHAT, _send(home, int(msg.uid), retry_text(msg), _markup(self.hub, msg)), int(msg.uid))

    def retract(self, record: DeliveryRecord, note: str) -> bool:
        return _edit(getattr(self.hub.app, "home", None), record, note)


class DesktopAdapter:
    """電腦提醒視窗：寫 show 檔（同一次提醒同一個 token，重寫＝同一張卡），必要時開視窗程式；等視窗回 shown。"""
    name = DESKTOP

    def __init__(self, spool, *, available: Callable[[int], bool], launch: Optional[Callable[[], None]] = None,
                 clock: Callable[[], float] = time.time):
        self.spool = spool
        self._available = available
        self.launch = launch
        self.clock = clock

    def available(self, uid: int) -> bool:
        return bool(self._available(int(uid)))

    def send(self, msg: Message) -> DeliveryResult:
        if msg.ref is None:                               # 只有提醒才跳視窗
            return DeliveryResult(DESKTOP, SKIPPED)
        extra = dict(msg.desktop or {})
        token = deskmod.make_token(msg.uid, msg.ref.rid, msg.ref.occurrence)
        card = deskmod.ShowCard(token=token, uid=int(msg.uid), rid=int(msg.ref.rid), occurrence=msg.ref.occurrence,
                                text=str(extra.get("text") or (msg.data or {}).get("text") or msg.text),
                                when=str(extra.get("when") or ""), late_min=int(extra.get("late_min") or 0),
                                snooze_count=int(extra.get("snooze_count") or 0),
                                buttons=list(extra.get("buttons") or deskmod.DEFAULT_BUTTONS), written_at=self.clock())
        self.spool.put_show(card)
        if self.launch is not None:
            try:
                self.launch()
            except Exception as e:                        # 開不起來：等確認逾時（no_window）再重試
                logging.warning("[DESK] cannot start the reminder window: %s", type(e).__name__)
        return DeliveryResult(DESKTOP, QUEUED, ref={"token": token}, retry_after=deskmod.SHOWN_TIMEOUT_S)

    def retract(self, record: DeliveryRecord, note: str) -> bool:
        token = record.ref.get("token")
        if not token or not deskmod.token_ok(token):
            return False
        self.spool.drop_show(token)
        self.spool.put_close(deskmod.CloseCard(token=token, reason="done_elsewhere", note=note))
        return True


# ── 這一則送哪裡 ─────────────────────────────────────────────────────────

def planned(hub, uid: int, kind: str, desk_ok: Callable[[int], bool]) -> List[str]:
    """跟 hub.where 同一套判斷（接上了、這一類沒關掉），多一個 desktop。"""
    if hub is None:
        return []
    off = hub.off_for(uid, kind)
    active = hub.active(uid)
    out = [c for c in HUB_CHANNELS if active.get(c) and c not in off]
    try:
        if desk_ok(int(uid)) and DESKTOP not in off:
            out.append(DESKTOP)
    except Exception:
        pass
    return out


def make_plan(hub, desk_ok: Callable[[int], bool], *, allow_chat: bool = True) -> Callable[[Message], List[str]]:
    def plan(msg: Message) -> List[str]:
        if msg.channels is not None:
            return [c for c in msg.channels if c in HUB_CHANNELS + (DESKTOP, CHAT)]
        chans = planned(hub, int(msg.uid), msg.kind, desk_ok)
        if allow_chat and hub._telegram_api() is None and hub._discord_bots() is None \
                and TELEGRAM not in hub.off_for(int(msg.uid), msg.kind):
            chans.append(CHAT)                            # 跟 hub.notify 一樣：沒有聊天通道就交給 app.home
        return chans
    return plan


def adapters_for(hub, desktop: Optional[DesktopAdapter] = None, *, allow_chat: bool = True) -> Dict[str, Any]:
    out: Dict[str, Any] = {WEB: WebAdapter(hub), TELEGRAM: TelegramAdapter(hub), DISCORD: DiscordAdapter(hub)}
    if allow_chat:
        out[CHAT] = ChatAdapter(hub)
    if desktop is not None:
        out[DESKTOP] = desktop
    return out


__all__ = ["ChatAdapter", "DesktopAdapter", "DiscordAdapter", "HUB_CHANNELS", "HubAnchor", "TelegramAdapter",
           "WebAdapter", "adapters_for", "classify", "make_plan", "planned", "retry_text"]
