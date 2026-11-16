"""
提醒哨兵（docs/adr/0028 §3.5）：`python -m synox sentinel`，登入 Windows 時自動啟動（使用者的「啟動」資料夾，不用管理員）。

只做一件事：**SYNOX 主程式沒開的時候**，照同一份提醒資料到點就跳電腦視窗＋送 Telegram。

- sentinel.lock：哨兵只能有一個（第二個直接結束）。
- 每 30 秒試拿 engine.lock（主程式開著時拿不到 → 只等）。拿到 → 每一輪：提醒引擎（reminder.headless_engine）到點檢查、
  佇列重送、讀視窗的回覆（每 2 秒）。
- 看到 yield.request（主程式開起來了）→ 做完這一輪 → 放鎖 → 刪掉 request → 回到只等。
- 每次拿到鎖都重新組一份（佇列、通知清單的快取都重讀）：主程式剛剛可能改過同一份檔。

測試用 Sentinel(data_dir, build=假的) 一步一步叫 step()，不開視窗、不連網。
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable, Optional

from synox.notify import desk as deskmod

LOCK_TRY_S = 30.0          # 沒拿到 engine.lock 時多久再試
ENGINE_TICK_S = 15.0       # 拿到時：提醒引擎到點檢查、佇列重送的間隔
STEP_S = 2.0               # 主迴圈：讀視窗回覆的間隔（≤ POLL_ENGINE_S）
SENTINEL_EXTRA = "synox_remind_sentinel"   # 哨兵組的 app.extras 裡設 True（W1 的回執看這個）
STALE_YIELD_S = 90.0      # yield.request 放了這麼久主程式都沒來拿：當作主程式沒開成，刪掉


@dataclass
class Round:
    """拿到鎖之後的一套東西：engine.tick()、outbox.pump()、desk.process(outbox, actions)。"""
    engine: Any
    outbox: Any
    desk: Any
    actions: Any = None


class Sentinel:

    def __init__(self, data_dir: str, *, build: Callable[[], Round], clock: Callable[[], float] = time.time):
        self.data_dir = data_dir
        self.build = build
        self.clock = clock
        self.lock = deskmod.engine_lock_at(data_dir)
        self.round: Optional[Round] = None
        self.next_lock_try = 0.0
        self.last_tick: Optional[float] = None

    @property
    def is_engine(self) -> bool:
        return self.lock.held

    def step(self, now: Optional[float] = None) -> str:
        """走一步。回現在的狀態：waiting（沒拿到鎖）｜engine（我在跑引擎）｜yielded（剛讓出去）｜error。"""
        now = self.clock() if now is None else now
        if not self.lock.held:
            if now < self.next_lock_try:
                return "waiting"
            self.next_lock_try = now + LOCK_TRY_S
            req = deskmod.yield_requested(self.data_dir)
            if req is not None:
                if req.at and now - float(req.at) < STALE_YIELD_S:
                    return "waiting"                         # 主程式正要拿：不搶
                deskmod.clear_yield(self.data_dir)
            if not self.lock.try_acquire(deskmod.WHO_SENTINEL):
                return "waiting"
            try:
                self.round = self.build()
            except Exception as e:
                logging.warning("[SENTINEL] cannot start the reminder engine: %s", type(e).__name__)
                self.lock.release()
                self.round = None
                return "error"
            self.last_tick = None
            logging.info("[SENTINEL] running the reminder engine (SYNOX is not open)")
        self.lock.beat()
        self._round(now)
        if deskmod.yield_requested(self.data_dir) is not None:
            self.release()
            deskmod.clear_yield(self.data_dir)
            self.next_lock_try = now + LOCK_TRY_S
            logging.info("[SENTINEL] SYNOX opened: handed the reminder engine back")
            return "yielded"
        return "engine"

    def _round(self, now: float) -> None:
        r = self.round
        if r is None:
            return
        if self.last_tick is None or now - self.last_tick >= ENGINE_TICK_S:
            self.last_tick = now
            for name, fn in (("engine", lambda: r.engine.tick()), ("outbox", lambda: r.outbox.pump(now))):
                try:
                    fn()
                except Exception as e:
                    logging.warning("[SENTINEL] %s round failed: %s", name, type(e).__name__)
        try:
            r.desk.process(r.outbox, r.actions)
        except Exception as e:
            logging.warning("[SENTINEL] window replies failed: %s", type(e).__name__)

    def release(self) -> None:
        self.lock.release()
        self.round = None

    def run(self, stop: Optional[threading.Event] = None, step_s: float = STEP_S) -> None:
        stop = stop or threading.Event()
        try:
            while not stop.is_set():
                try:
                    self.step()
                except Exception:
                    logging.exception("[SENTINEL] step failed")
                stop.wait(step_s)
        finally:
            self.release()


# ── 真的跑：組一套跟主程式一樣的送法（沒有網頁、沒有 Discord）───────────────

def build_round(config, vault, *, launcher=None) -> Round:
    """哨兵拿到鎖時組一套：通知中心（同一份通知清單）、佇列、電腦視窗、W1 的 headless_engine。"""
    from synox import notify
    from synox.notify import delivery
    from synox.notify.deskapp import DESK_EXTRA, DeskService, _config_off, make_outbox
    from synox.notify.hub import Hub
    from synox.schedule import reminder
    home = None
    if getattr(config, "has_token", False):
        from isdtelekit.telegram.bot_api import BotAPI
        home = BotAPI(config.bot_token)
    app = SimpleNamespace(home=home, extras={}, owner_id=int(config.owner_id), config=config)
    hub = Hub(app, config.data_dir, vault)
    desk = DeskService(config.data_dir, owner_id=int(config.owner_id), personal=True, config_off=_config_off(config),
                       launcher=launcher)
    desk.armed = True
    outbox = make_outbox(hub, desk, vault, config.data_dir, actions=lambda: app.extras.get(delivery.ACTIONS_EXTRA),
                         allow_chat=False)
    app.extras.update({notify.EXTRA: hub, delivery.OUTBOX_EXTRA: outbox, DESK_EXTRA: desk, "synox_config": config,
                       "vault": vault, SENTINEL_EXTRA: True})
    engine = reminder.headless_engine(config.data_dir, vault, outbox.submit)
    actions = engine if hasattr(engine, "act") else None
    if actions is not None:
        app.extras[delivery.ACTIONS_EXTRA] = actions
    return Round(engine=engine, outbox=outbox, desk=desk, actions=actions)


def _log_to_file(data_dir: str) -> None:
    from logging.handlers import RotatingFileHandler
    folder = deskmod.remind_dir(data_dir)
    os.makedirs(folder, exist_ok=True)
    handler = RotatingFileHandler(os.path.join(folder, "sentinel.log"), maxBytes=256 * 1024, backupCount=2,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def main(config_path: str = "") -> int:
    from isdtelekit.host.config import ConfigError
    from synox.config import SynoxConfig
    try:
        config = SynoxConfig.load(config_path or None, require_token=False)
    except ConfigError as e:
        print(f"❌ {e}")
        return 2
    if sys.platform != "win32" or config.mode == "server":
        print("提醒哨兵只在 Windows 的個人版跑（伺服器版請讓 SYNOX 一直開著）。")
        return 1
    _log_to_file(config.data_dir)
    single = deskmod.sentinel_lock_at(config.data_dir)
    if not single.try_acquire():
        logging.info("[SENTINEL] another sentinel is already running")
        return 0
    try:
        from synox.remindwin.launcher import popup_launcher
        from synox.vault import open_vault
        try:
            vault = open_vault(config)
        except Exception as e:                            # 打不開就不跑：寫成明文會跟主程式的加密檔對不上
            logging.error("[SENTINEL] cannot open the vault: %s", type(e).__name__)
            return 2
        sentinel = Sentinel(config.data_dir,
                            build=lambda: build_round(config, vault, launcher=popup_launcher(config.data_dir)))
        logging.info("[SENTINEL] started")
        sentinel.run()
    finally:
        single.release()
    return 0


__all__ = ["ENGINE_TICK_S", "LOCK_TRY_S", "Round", "STEP_S", "Sentinel", "build_round", "main"]
