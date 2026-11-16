"""
通知中心：一則「要告訴這個人」的事，同時送到他用的每一個地方（docs/notifications.md）。

    hub.notify(uid, "⏰ 提醒：吃藥", kind="alarm", level="alarm", key="alarm:3:2026-11-14 08:00",
               actions=[...])
    hub.notify_owner(text, kind="update")           # 也是 app.notify_owner（install 換掉的）

送到哪裡（每一條各自 try/except：一條壞掉不影響別條；log 只記例外的種類，不記內容）：
- web：存進這個人的通知清單（data/notifications，store.py）；網頁的 🔔 數字、跳出來的小卡都從這裡來。
- Telegram：有 Telegram（app.home 裡有 BotAPI），而且這個人接得到——真的 Telegram id，或擁有者在網頁配對過
  （telegram_link）。
- Discord：有私訊型 Discord bot，而且這個人接得到（DiscordBots.can_reach；擁有者要配對過）。
- 兩個聊天通道都沒有（只在終端機試、測試的假管子）：照舊交給 app.home（只記 log／測試收得到）。

同一件事不重送：給 key 的話，DEDUPE_S 之內同一個 key 只送一次。
每一類（kind）送到哪裡可以關（設定 → 電腦與備份 →「🔔 通知要送到哪裡」）；安全警告的網頁那一條關不掉。
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

from synox.identity import BASE
from synox.notify.store import FOLDER, NotifyStore

WEB, TELEGRAM, DISCORD = "web", "telegram", "discord"
CHANNELS = (WEB, TELEGRAM, DISCORD)
CHANNEL_LABELS = {WEB: "網頁", TELEGRAM: "Telegram", DISCORD: "Discord"}
DEDUPE_S = 12 * 3600
SNOOZE_MIN = 5

# 每一類：名字（設定頁顯示）、預設不送的地方
KINDS: Dict[str, dict] = {
    "alarm": {"label": "⏰ 鬧鐘與提醒", "off": []},
    "tool_idle": {"label": "🧩 工具畫面太久沒人用", "off": []},
    "update": {"label": "🆕 SYNOX 有新版", "off": []},
    "assistant": {"label": "🫀 常駐助理的消息", "off": []},
    "tools": {"label": "🧩 工具裝好了／出問題", "off": []},
    "safety": {"label": "⚠️ 安全警告", "off": [], "locked": [WEB]},
    "greeting": {"label": "👋 SYNOX 開起來了", "off": [WEB]},
    "general": {"label": "📣 其他", "off": []},
}

# 白話（docs/notifications.md 的「用字」）
T = {
    "ok": "知道了",
    "snooze": f"{SNOOZE_MIN} 分鐘後再提醒",
    "snoozed": "好，{hhmm} 再叫你一次。",
    "gone": "這則提醒已經處理過了。",
    "app_stop": "現在關掉",
    "app_keep": "再給我 {n} 分鐘",
    "app_stopped": "關掉了。",
    "app_kept": "好，再給你一段時間。",
    "test": "⏰ 試響一下：鬧鐘時間到的時候，就會像這樣叫你。",
}


def _log_fail(where: str, uid, e: BaseException) -> None:
    logging.warning("[NOTIFY] %s → %s failed: %s", where, uid, type(e).__name__)


class Hub:

    def __init__(self, app, data_dir: str, vault=None, *, clock: Callable[[], float] = time.time):
        self.app = app
        self.clock = clock
        self.store = NotifyStore(os.path.join(data_dir, FOLDER), vault, clock=clock)
        self.legacy_home = None          # install 時的 app.home 之外，沒有聊天通道時的退路（直接讀 app.home）

    # ── 誰接得到 ─────────────────────────────────────────────────────

    def _telegram_api(self):
        from isdtelekit.host.app import telegram_api
        try:
            return telegram_api(self.app.home)
        except Exception:
            return None

    def _discord_bots(self):
        bots = self.app.extras.get("discord_bots")
        return bots if bots is not None and getattr(bots, "channels", None) else None

    def telegram_ok(self, uid: int) -> bool:
        if self._telegram_api() is None:
            return False
        if int(uid) < BASE:
            return True
        link = self.app.extras.get("telegram_link")
        try:
            return link is not None and int(uid) == int(link.owner_id) and bool(link.external())
        except Exception:
            return False

    def discord_ok(self, uid: int) -> bool:
        bots = self._discord_bots()
        try:
            return bots is not None and bool(bots.can_reach(int(uid)))
        except Exception:
            return False

    def web_ok(self) -> bool:
        ui = self.app.extras.get("synox_web")
        return ui is None or bool(getattr(ui, "enabled", True))

    def active(self, uid: int) -> Dict[str, bool]:
        return {WEB: self.web_ok(), TELEGRAM: self.telegram_ok(uid), DISCORD: self.discord_ok(uid)}

    # ── 設定：哪一類送到哪裡 ─────────────────────────────────────────

    def off_for(self, uid: int, kind: str) -> set:
        prefs = self.store.prefs(uid)
        spec = KINDS.get(kind) or KINDS["general"]
        off = set(prefs["off"].get(kind, [])) if prefs["set"] else set(spec.get("off", []))
        return off - set(spec.get("locked", []))

    def prefs_view(self, uid: int) -> dict:
        active = self.active(uid)
        return {"channels": [{"id": c, "label": CHANNEL_LABELS[c], "active": active[c]} for c in CHANNELS],
                "kinds": [{"kind": k, "label": v["label"], "off": sorted(self.off_for(uid, k)),
                           "locked": list(v.get("locked", []))} for k, v in KINDS.items()]}

    def save_prefs(self, uid: int, off: dict) -> None:
        clean = {}
        for kind, chans in (off or {}).items():
            if kind in KINDS and isinstance(chans, list):
                locked = set(KINDS[kind].get("locked", []))
                clean[kind] = [c for c in chans if c in CHANNELS and c not in locked]
        self.store.save_prefs(uid, clean)

    def where(self, uid: int, kind: str = "alarm") -> List[str]:
        """這一類現在真的會送到哪裡（白話的名字）：網頁、Telegram、Discord。"""
        off = self.off_for(uid, kind)
        active = self.active(uid)
        return [CHANNEL_LABELS[c] for c in CHANNELS if active[c] and c not in off]

    # ── 送 ───────────────────────────────────────────────────────────

    def notify(self, uid, text, *, kind: str = "general", level: str = "info", key: Optional[str] = None,
               within: float = DEDUPE_S, actions: Optional[List[dict]] = None, data: Optional[dict] = None,
               markup: Optional[dict] = None) -> dict:
        """送給 uid。回 {"web": id 或 None, "telegram": bool, "discord": bool, "chat": bool}（測試、試響一下用）。"""
        uid = int(uid)
        out: dict = {WEB: None, TELEGRAM: False, DISCORD: False, "chat": False}
        if key:
            try:
                if self.store.seen_key(uid, key, within):
                    out["skipped"] = "dup"
                    return out
            except Exception as e:
                _log_fail("dedupe", uid, e)
        off = self.off_for(uid, kind)
        item = None
        try:                                           # 清單一定存（聊天通道的按鈕要找得回來）；網頁關了就藏起來
            hidden = WEB in off or not self.web_ok()
            item = self.store.add(uid, str(text), kind=kind, level=level, actions=actions,
                                  data={**(data or {}), **({"hidden": True} if hidden else {})})
            if hidden:
                self.store.update(uid, item["id"], read=True)
            else:
                out[WEB] = item["id"]
        except Exception as e:
            _log_fail("web", uid, e)
        if markup is None and item is not None:
            markup = self._chat_markup(actions or [], item["id"])
        plain = str(text)
        api = self._telegram_api()
        bots = self._discord_bots()
        if TELEGRAM not in off and api is not None and self.telegram_ok(uid):
            try:
                res = api.send_message(uid, plain, reply_markup=markup) if markup else api.send_message(uid, plain)
                out[TELEGRAM] = not isinstance(res, dict) or bool(res.get("ok", True))
            except Exception as e:
                _log_fail("telegram", uid, e)
        if DISCORD not in off and bots is not None and self.discord_ok(uid):
            try:
                target = bots.pick(uid)
                res = target.send_message(uid, plain, reply_markup=markup) if markup else target.send_message(uid, plain)
                record = getattr(self.app.home, "_record", None)
                if record is not None:
                    record(target, res)
                out[DISCORD] = not isinstance(res, dict) or bool(res.get("ok", True))
            except Exception as e:
                _log_fail("discord", uid, e)
        if api is None and bots is None and TELEGRAM not in off:
            try:                                       # 沒有聊天通道：照舊交給 app.home（只記 log／測試的假管子）
                home = self.app.home
                home.send_message(uid, plain, reply_markup=markup) if markup else home.send_message(uid, plain)
                out["chat"] = True
            except Exception as e:
                _log_fail("home", uid, e)
        if key:
            try:
                self.store.remember_key(uid, key)
            except Exception as e:
                _log_fail("dedupe", uid, e)
        return out

    def notify_owner(self, text, markup: Optional[dict] = None, *, kind: str = "general", level: str = "info",
                     key: Optional[str] = None, actions: Optional[List[dict]] = None, data: Optional[dict] = None,
                     within: float = DEDUPE_S) -> dict:
        return self.notify(self.app.owner_id, text, kind=kind, level=level, key=key, actions=actions, data=data,
                           markup=markup, within=within)

    @staticmethod
    def _chat_markup(actions: List[dict], nid: int) -> Optional[dict]:
        """網頁的按鈕 → Telegram／Discord 的按鈕（只有聊天通道也做得到的那幾種）。"""
        row = []
        for a in actions:
            if a.get("id") == "ok":
                row.append({"text": a.get("label") or T["ok"], "callback_data": f"ntf:ok:{nid}"})
            elif a.get("id") == "snooze":
                row.append({"text": a.get("label") or T["snooze"], "callback_data": f"ntf:s5:{nid}"})
            elif a.get("id") in ("app_stop", "app_keep") and a.get("app"):
                what = "stop" if a["id"] == "app_stop" else "keep"
                row.append({"text": a.get("label") or "", "callback_data": f"ntfa:{what}:{a['app']}"[:64]})
        return {"inline_keyboard": [row]} if row else None

    # ── 鬧鐘 ─────────────────────────────────────────────────────────

    def alarm(self, uid: int, text: str, *, key: Optional[str] = None, late_min: int = 0, item_id=None) -> dict:
        """鬧鐘時間到：⏰ 提醒：…（晚了就多說一句為什麼），帶「知道了」「5 分鐘後再提醒」。"""
        body = f"⏰ 提醒：{text}"
        if late_min > 0:
            body += f"\n（晚了 {late_min} 分鐘才叫你：剛剛電腦可能睡著了，或 SYNOX 沒在跑。）"
        return self.notify(uid, body, kind="alarm", level="alarm", key=key,
                           actions=[{"id": "ok", "label": T["ok"]}, {"id": "snooze", "label": T["snooze"]}],
                           data={"text": text, "alarm": item_id})

    def missed(self, uid: int, when: str, text: str, *, key: Optional[str] = None) -> dict:
        return self.notify(uid, f"⏰ 你錯過了 1 個鬧鐘：{when} {text}\n"
                                "（那時候 SYNOX 沒在跑，或電腦睡著了，所以沒叫到你。）",
                           kind="alarm", level="alarm", key=key, actions=[{"id": "ok", "label": T["ok"]}],
                           data={"text": text, "missed": True})

    def snooze(self, uid: int, nid: int, minutes: int = SNOOZE_MIN) -> Optional[str]:
        """「5 分鐘後再提醒」：用原本的提醒清單加一個只響一次的（date＝那一天）。回 HH:MM；找不到回 None。"""
        item = self.store.get(uid, nid)
        if item is None or item.get("kind") != "alarm" or not (item.get("data") or {}).get("text") \
                or (item.get("data") or {}).get("snoozed"):
            return None
        from synox.schedule.commands import store_for
        at = datetime.fromtimestamp(self.clock()) + timedelta(minutes=minutes)
        hhmm = at.strftime("%H:%M")
        store_for(self.app).of(uid).add("remind", hhmm, uid, text=item["data"]["text"], date=at.strftime("%Y-%m-%d"))
        self.store.update(uid, nid, actions=[], read=True, snoozed=hhmm)
        return hhmm

    def dismiss(self, uid: int, nid: int) -> bool:
        item = self.store.get(uid, nid)
        if item is None:
            return False
        acts = [a for a in item.get("actions") or [] if a.get("id") not in ("ok", "snooze")]
        self.store.update(uid, nid, actions=acts, read=True)
        return True


def install_buttons(app, hub: Hub) -> None:
    """Telegram／Discord 上的通知按鈕：ntf:（提醒的「知道了」「5 分鐘後再提醒」，綁在 remind.add：按的人要能加提醒）、
    ntfa:（工具畫面的「現在關掉」「再給我 N 分鐘」，綁在 apps.app_close：只有擁有者）。按的人一律先過 authorize。"""
    registry = app.registry

    def on_reminder(api, cb):
        parts = cb.data.split(":")
        what, nid = (parts + ["", ""])[1:3]
        try:
            nid = int(nid)
        except ValueError:
            api.answer_callback_query(cb.cq_id, text=T["gone"])
            return
        uid = int(cb.clicker_id)
        if what == "s5":
            hhmm = hub.snooze(uid, nid)
            answer = T["snoozed"].format(hhmm=hhmm) if hhmm else T["gone"]
        else:
            answer = T["ok"] if hub.dismiss(uid, nid) else T["gone"]
        try:
            api.remove_buttons(cb.chat_id, cb.message_id)
        except Exception:
            pass
        api.answer_callback_query(cb.cq_id, text=answer)

    def on_app(api, cb):
        parts = cb.data.split(":")
        what, name = (parts + ["", ""])[1:3]
        manager = app.extras.get("synox_apps")
        answer = T["gone"]
        if manager is not None and name:
            try:
                if what == "stop":
                    manager.stop(name, by=cb.clicker_id, via="telegram", reason="owner")
                    answer = T["app_stopped"]
                elif what == "keep":
                    manager.keep(name, by=cb.clicker_id, via="telegram")
                    answer = T["app_kept"]
            except Exception as e:
                answer = getattr(e, "message", "") or T["gone"]
        try:
            api.remove_buttons(cb.chat_id, cb.message_id)
        except Exception:
            pass
        api.answer_callback_query(cb.cq_id, text=answer)

    if registry.node("remind.add") is not None:
        try:
            registry.bind_callback("ntf:", "remind.add", on_reminder)
        except ValueError:
            pass
    if registry.node("apps.app_close") is not None:
        try:
            registry.bind_callback("ntfa:", "apps.app_close", on_app)
        except ValueError:
            pass
