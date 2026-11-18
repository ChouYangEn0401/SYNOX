"""
送達層接上主程式（或提醒哨兵）：佇列、電腦提醒視窗的設定與檔案往返、誰是提醒引擎（docs/adr/0029 §3.3–3.5）。

    notify.install_delivery(app, config, vault, config_path=…)     app.build 在 schedule.install 之後叫

- 佇列（FileOutbox）放 app.extras[delivery.OUTBOX_EXTRA]；runtime 任務 system.notify.outbox 每 15 秒 pump。
- runtime 任務 system.notify.desk 每 ≤5 秒：確認自己還是不是提醒引擎（engine.lock）、讀視窗的回覆（shown／按了什麼）。
- **只有真的跑起來（app.start 的 on_start）才「上膛」**：才會寫視窗檔、開視窗程式、拿 engine.lock、登記哨兵的啟動檔。
  測試只 build 不 start，所以不會開視窗、不會碰啟動資料夾。
- 電腦視窗的開關（data/remind/settings.json，設定頁可以改）：個人版 Windows 預設開；config.json 寫
  "notify": {"desktop": false} 一律關。哨兵的「登入時啟動」預設開（只在個人版 Windows）。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from typing import Any, Callable, Dict, Optional

from synox.notify import desk as deskmod
from synox.notify.channels import DesktopAdapter, HubAnchor, adapters_for, make_plan
from synox.notify.delivery import (ACTIONS_EXTRA, DESKTOP, OUTBOX_EXTRA, OUTBOX_FOLDER, PUMP_INTERVAL, PUMP_TASK_ID,
                                   DeliveryRecord, Message, message_key)
from synox.notify.outbox import FileOutbox
from synox.notify.store import FOLDER as NOTIFY_FOLDER

DESK_EXTRA = "synox_notify_desk"
GATE_EXTRA = "synox_remind_gate"
DESK_TASK_ID = "system.notify.desk"
DESK_TASK_INTERVAL = deskmod.POLL_ENGINE_S          # 每 5 秒讀一次視窗的回覆（runtime 睡到 next_due，不再被 5 秒一格吃掉）
SETTINGS_FILE = "settings.json"                     # data/remind/settings.json
YIELD_AGAIN_S = 30.0                                # 主程式拿不到鎖：多久再送一次讓位請求


def outbox_folder(data_dir: str) -> str:
    return os.path.join(data_dir, NOTIFY_FOLDER, OUTBOX_FOLDER)


# ── 電腦提醒視窗：設定、上膛、讀視窗的回覆 ───────────────────────────────

class DeskService:
    """電腦提醒視窗這一邊（主程式與哨兵共用）。"""

    def __init__(self, data_dir: str, *, owner_id: int, personal: bool = True, platform: Optional[str] = None,
                 config_off: bool = False, launcher: Optional[Callable[[], None]] = None,
                 clock: Callable[[], float] = time.time):
        self.data_dir = data_dir
        self.owner_id = int(owner_id)
        self.personal = personal
        self.platform = platform or sys.platform
        self.config_off = config_off
        self.launcher = launcher
        self.clock = clock
        self.armed = False                          # 真的跑起來才 True（app on_start／哨兵）
        self.spool = deskmod.spool_at(data_dir)
        self.startup_folder: Optional[str] = None   # None＝使用者的「啟動」資料夾（測試一律換成暫存資料夾）

    # 設定

    @property
    def supported(self) -> bool:
        """這台能有電腦視窗與哨兵嗎：Windows 個人版。"""
        return self.platform == "win32" and self.personal

    def _settings_path(self) -> str:
        return os.path.join(deskmod.remind_dir(self.data_dir), SETTINGS_FILE)

    def settings(self) -> Dict[str, bool]:
        data: Dict[str, Any] = {}
        try:
            with open(self._settings_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        window = bool(data.get("window", True)) and not self.config_off
        return {"window": window, "sentinel": bool(data.get("sentinel", True))}

    def save_settings(self, *, window: Optional[bool] = None, sentinel: Optional[bool] = None) -> Dict[str, bool]:
        current = self.settings()
        if window is not None:
            current["window"] = bool(window)
        if sentinel is not None:
            current["sentinel"] = bool(sentinel)
        deskmod._write_json(deskmod.remind_dir(self.data_dir), SETTINGS_FILE, current)
        return self.settings()

    def view(self) -> Dict[str, Any]:
        s = self.settings()
        return {"supported": self.supported, "window": self.supported and s["window"],
                "sentinel": self.supported and s["sentinel"], "locked_off": self.config_off,
                "sentinel_installed": self.sentinel_installed() if self.supported else False}

    def window_on(self) -> bool:
        return self.supported and self.settings()["window"]

    def available(self, uid: int) -> bool:
        return self.armed and int(uid) == self.owner_id and self.window_on()

    # 視窗程式

    def launch(self) -> None:
        """視窗程式沒開就開（popup.lock 沒人拿＝沒開）。沒上膛、沒給 launcher 就什麼都不做。"""
        if not self.armed or self.launcher is None:
            return
        if deskmod.popup_lock_at(self.data_dir).free():
            self.launcher()

    def adapter(self) -> DesktopAdapter:
        return DesktopAdapter(self.spool, available=self.available, launch=self.launch, clock=self.clock)

    # 哨兵的啟動檔

    def _folder(self) -> str:
        if self.startup_folder:
            return self.startup_folder
        from synox.wizard.shortcuts import startup_dir
        return startup_dir()

    def sentinel_installed(self) -> bool:
        try:
            return deskmod.autostart_installed(self._folder())
        except Exception:
            return False

    def sync_autostart(self, command, cwd: str = "") -> Optional[str]:
        """照設定放上／拿掉哨兵的啟動檔（只在 Windows 個人版）。回放好的路徑；拿掉或不支援回 None。"""
        if not self.supported:
            return None
        folder = self._folder()
        if self.settings()["sentinel"] and command:
            return deskmod.install_autostart(folder, list(command), cwd)
        deskmod.remove_autostart(folder)
        return None

    # 讀視窗的回覆

    def process(self, outbox, actions) -> list:
        """讀 from_win：shown → 佇列確認 desktop 送到了；act → ReminderActions.act，成功就讓其他管道收掉。回處理了哪些。"""
        done = []
        for obj in self.spool.take_from_win():
            try:
                uid = int(str(obj.token).split("-")[0])
            except ValueError:
                continue
            if isinstance(obj, deskmod.ShownAck):
                key = outbox.find(uid, DESKTOP, "token", obj.token) if outbox is not None else None
                if key:
                    outbox.confirm(uid, key, DESKTOP, {"shown_at": obj.at})
                done.append(("shown", obj.token, bool(key)))
                continue
            if not isinstance(obj, deskmod.DeskAction):
                continue
            if actions is None:
                logging.warning("[DESK] window action ignored: no reminder engine")
                done.append(("act", obj.token, False))
                continue
            try:
                outcome = actions.act(uid, int(obj.rid), obj.occurrence, obj.action, until=obj.until, typed=obj.typed,
                                      via=DESKTOP)
            except Exception as e:
                logging.warning("[DESK] reminder action failed: %s", type(e).__name__)
                done.append(("act", obj.token, False))
                continue
            if getattr(outcome, "ok", False):
                if obj.occurrence and outbox is not None:
                    key = outbox.find(uid, DESKTOP, "token", obj.token) or message_key(obj.rid, obj.occurrence, uid)
                    outbox.resolve(uid, key, note=getattr(outcome, "note", ""), via=DESKTOP)
                elif not obj.occurrence:
                    self._drop_todo(uid, int(obj.rid))
                self.spool.drop_show(obj.token)
            elif getattr(outcome, "reason", "") == "gone":
                self.spool.drop_show(obj.token)
            done.append(("act", obj.token, bool(getattr(outcome, "ok", False))))
        return done

    def _drop_todo(self, uid: int, rid: int) -> None:
        for todos in self.spool.todos_for_win(uid):
            items = [it for it in todos.items if int(it.get("rid", -1)) != rid]
            if len(items) != len(todos.items):
                self.spool.put_todos(deskmod.TodoList(uid=uid, items=items))

    def put_todos(self, uid: int, items) -> None:
        """待辦有變動時整份覆寫（W1 呼叫 delivery.publish_todos）。"""
        if int(uid) != self.owner_id or not self.supported:
            return
        clean = [{"rid": int(it["rid"]), "text": str(it.get("text", ""))} for it in items or [] if "rid" in it]
        self.spool.put_todos(deskmod.TodoList(uid=int(uid), items=clean))


# ── 誰是提醒引擎：主程式這一邊 ────────────────────────────────────────────

class EngineGate:
    """主程式拿 engine.lock：拿不到（哨兵在跑）→ 寫 yield.request，之後每一輪再試；拿到之前 mine＝False（引擎先不跑）。
    還沒 start（只 build、測試）＝mine＝True：沒有哨兵跟你搶。"""

    def __init__(self, data_dir: str, *, who: str = deskmod.WHO_APP, clock: Callable[[], float] = time.time):
        self.data_dir = data_dir
        self.who = who
        self.clock = clock
        self.lock = deskmod.engine_lock_at(data_dir)
        self.started = False
        self.asked_at: Optional[float] = None

    @property
    def mine(self) -> bool:
        return not self.started or self.lock.held

    def start(self) -> bool:
        self.started = True
        return self.check()

    def check(self, now: Optional[float] = None) -> bool:
        if not self.started:
            return True
        now = self.clock() if now is None else now
        if self.lock.held:
            self.lock.beat()
            return True
        if self.lock.try_acquire(self.who):
            if self.asked_at is not None or deskmod.yield_requested(self.data_dir) is not None:
                deskmod.clear_yield(self.data_dir)
            self.asked_at = None
            logging.info("[REMIND] this program runs the reminder engine")
            return True
        if self.asked_at is None or now - self.asked_at >= YIELD_AGAIN_S:
            deskmod.request_yield(self.data_dir, at=now)
            self.asked_at = now
            logging.info("[REMIND] reminder sentinel is running; asked it to step aside")
        return False

    def stop(self) -> None:
        self.lock.release()
        self.started = False

    def view(self) -> Dict[str, Any]:
        stamp = self.lock.holder()
        return {"mine": self.mine, "started": self.started,
                "holder": None if stamp is None else {"who": stamp.who, "since": stamp.since, "beat": stamp.beat}}


# ── 組起來 ───────────────────────────────────────────────────────────────

def make_outbox(hub, desk: Optional[DeskService], vault, data_dir: str, *, actions: Callable[[], Any],
                allow_chat: bool = True, clock: Callable[[], float] = time.time) -> FileOutbox:
    desktop = desk.adapter() if desk is not None else None
    desk_ok = desk.available if desk is not None else (lambda uid: False)

    def listener(msg: Message, rec: DeliveryRecord) -> None:
        handler = actions()
        if handler is not None and msg.ref is not None:
            handler.on_delivery(int(msg.uid), int(msg.ref.rid), msg.ref.occurrence, rec)

    return FileOutbox(outbox_folder(data_dir), vault, adapters=adapters_for(hub, desktop, allow_chat=allow_chat),
                      plan=make_plan(hub, desk_ok, allow_chat=allow_chat), anchor=HubAnchor(hub), listener=listener,
                      clock=clock)


def _config_off(config) -> bool:
    raw = getattr(config, "raw", None) or {}
    section = raw.get("notify") if isinstance(raw, dict) else None
    return isinstance(section, dict) and section.get("desktop") is False


def ensure(app, config=None, vault=None):
    """佇列＋電腦視窗服務（沒裝就裝，不登記 runtime 任務；deliver 比 install_delivery 早被叫也能用）。回 outbox 或 None。"""
    extras = getattr(app, "extras", None)
    if extras is None:
        return None
    if extras.get(OUTBOX_EXTRA) is not None:
        return extras[OUTBOX_EXTRA]
    from synox import notify
    hub = notify.of(app)
    if hub is None:
        return None
    config = config if config is not None else extras.get("synox_config")
    vault = vault if vault is not None else extras.get("vault")
    data_dir = getattr(config, "data_dir", None) or os.path.dirname(hub.store.folder)
    desk = extras.get(DESK_EXTRA)
    if desk is None:
        desk = DeskService(data_dir, owner_id=getattr(app, "owner_id", 0),
                           personal=getattr(config, "mode", "personal") != "server", config_off=_config_off(config))
        extras[DESK_EXTRA] = desk
    outbox = make_outbox(hub, desk, vault, data_dir, actions=lambda: extras.get(ACTIONS_EXTRA))
    extras[OUTBOX_EXTRA] = outbox
    return outbox


def install(app, config, vault=None, *, config_path: str = "") -> FileOutbox:
    """app.build：佇列、電腦視窗、引擎鎖；runtime 任務；on_start 上膛＋拿鎖＋哨兵啟動檔，on_stop 放鎖。"""
    outbox = ensure(app, config, vault)
    desk: DeskService = app.extras[DESK_EXTRA]
    gate = EngineGate(config.data_dir)
    app.extras[GATE_EXTRA] = gate

    def pump(_ctx=None):
        if gate.mine:
            outbox.pump()

    def desk_round(_ctx=None):
        gate.check()
        if gate.mine:
            desk.process(outbox, app.extras.get(ACTIONS_EXTRA))

    try:
        from synox import runtime
        rt = runtime.of(app)
        if rt is not None:
            rt.loop.register(PUMP_TASK_ID, "📮 通知重送", fn=pump, interval=float(PUMP_INTERVAL), timeout=120.0)
            rt.loop.register(DESK_TASK_ID, "🖥️ 電腦提醒視窗", fn=desk_round, interval=float(DESK_TASK_INTERVAL),
                             timeout=60.0)
    except Exception:
        logging.exception("[NOTIFY] cannot register delivery tasks")

    def on_start(_app):
        from synox.remindwin import launcher as remind_launcher
        desk.launcher = remind_launcher.popup_launcher(config.data_dir)
        desk.armed = True
        gate.start()
        if desk.supported:
            try:
                command, cwd = remind_launcher.sentinel_command(config_path)
                desk.sync_autostart(command, cwd)
            except Exception as e:
                logging.warning("[REMIND] cannot update the sentinel autostart: %s", type(e).__name__)

    def on_stop(_app):
        gate.stop()

    app.on_start.append(on_start)
    app.on_stop.append(on_stop)
    return outbox


__all__ = ["DESK_EXTRA", "DESK_TASK_ID", "DeskService", "EngineGate", "GATE_EXTRA", "ensure", "install", "make_outbox",
           "outbox_folder"]
