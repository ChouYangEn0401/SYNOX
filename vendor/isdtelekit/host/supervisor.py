"""
ChannelSupervisor：「自己跑一個迴圈」的 channel（例如 Telegram 的收訊）各自一條受監看的執行緒。
從 ClawBot 的 channels/supervisor.py 原封搬過來。

bot 本身（指令樹、排程、JobRunner）才是核心；channel 只是其中一扇門。所以：
- 掛了（例外）就退避重啟：1、2、4…最多 60 秒；重啟次數和最後的錯誤記在狀態裡（status()）。
- 可以單獨 stop / start / restart，不會把整支 bot 帶走。
- 同一個 channel 永遠只有一條迴圈：Telegram 同時兩個 getUpdates 會互相踢掉（409 Conflict），
  所以 restart 一定先等舊的那條結束才開新的。
- 從那個 channel 自己的執行緒裡（例如在 Telegram 下指令要重啟 Telegram 收訊）要停它時，不能 join 自己：
  stop/start/restart 都可以丟到背景做（background=True）。
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional, Protocol

STOPPED, RUNNING, BACKOFF, STOPPING = "stopped", "running", "backoff", "stopping"
STATE_LABELS = {STOPPED: "停止", RUNNING: "執行中", BACKOFF: "出錯，等一下自動重試", STOPPING: "停止中"}


class Loop(Protocol):
    def run_forever(self) -> None: ...      # 一直跑，直到 stop() 被呼叫才回來
    def stop(self) -> None: ...


class SupervisedChannel:

    def __init__(self, name: str, factory: Callable[[], Loop], backoff_max: float = 60.0,
                 healthy_after: float = 60.0):
        self.name = name
        self._factory = factory
        self._backoff_max = backoff_max
        self._healthy_after = healthy_after      # 跑超過這麼久才掛，退避從頭算
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[Loop] = None
        self._stop = threading.Event()
        self._state = STOPPED
        self._since = datetime.now()
        self.restarts = 0
        self.last_error = ""

    @property
    def state(self) -> str:
        return self._state

    def _set(self, state: str) -> None:
        self._state, self._since = state, datetime.now()

    def status(self) -> dict:
        with self._lock:
            return {"state": self._state, "since": self._since.isoformat(timespec="seconds"),
                    "restarts": self.restarts, "last_error": self.last_error}

    def start(self) -> bool:
        """開始跑；已經在跑就回 False。"""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, args=(self._stop,), daemon=True,
                                            name=f"Channel-{self.name}")
            self._set(RUNNING)
            self._thread.start()
        logging.info("[CHANNEL] %s started", self.name)
        return True

    def stop(self, timeout: float = 40.0) -> bool:
        """停下來並等迴圈結束（Telegram 長輪詢最多 25 秒）。回傳是否真的停了。"""
        with self._lock:
            thread, loop = self._thread, self._loop
            if thread is None or not thread.is_alive():
                self._set(STOPPED)
                return True
            self._stop.set()
            self._set(STOPPING)
        if loop is not None:
            try:
                loop.stop()
            except Exception:
                logging.exception("[CHANNEL] %s: stop() failed", self.name)
        if thread is threading.current_thread():
            return False                         # 呼叫者就是這條迴圈：它處理完這一則就會自己結束
        thread.join(timeout)
        stopped = not thread.is_alive()
        if stopped:
            logging.info("[CHANNEL] %s stopped", self.name)
        else:
            logging.warning("[CHANNEL] %s did not stop within %ss", self.name, timeout)
        return stopped

    def restart(self) -> bool:
        return self.stop() and self.start()

    def _run(self, stop: threading.Event) -> None:
        delay = 1.0
        while not stop.is_set():
            started = time.monotonic()
            try:
                loop = self._factory()
                # stop() 跟這裡用同一把鎖：要嘛它看到 loop（呼叫 loop.stop()），要嘛這裡看到 stop 已經設了
                # （就不跑）。不然 stop() 剛好落在「執行緒開了、loop 還沒建好」之間，這條迴圈就沒人停得掉。
                with self._lock:
                    cancelled = stop.is_set()
                    if not cancelled:
                        self._loop = loop
                        self._set(RUNNING)
                if cancelled:
                    break
                loop.run_forever()
                if stop.is_set():
                    break
                raise RuntimeError("迴圈自己結束了")
            except Exception as exc:
                if stop.is_set():
                    break
                if time.monotonic() - started > self._healthy_after:
                    delay = 1.0
                with self._lock:
                    self.restarts += 1
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    self._set(BACKOFF)
                logging.exception("[CHANNEL] %s crashed; restarting in %.0fs", self.name, delay)
                if stop.wait(delay):
                    break
                delay = min(delay * 2, self._backoff_max)
        with self._lock:
            self._loop = None
            self._set(STOPPED)


class ChannelHub:
    """所有受監看的 channel。host/app.py 的 App.run() 照設定登記、開；要開關的指令從這裡做。"""

    def __init__(self):
        self._channels: Dict[str, SupervisedChannel] = {}

    def add(self, name: str, factory: Callable[[], Loop], **kwargs) -> SupervisedChannel:
        channel = self._channels[name] = SupervisedChannel(name, factory, **kwargs)
        return channel

    def get(self, name: str) -> Optional[SupervisedChannel]:
        return self._channels.get(name)

    def names(self) -> List[str]:
        return list(self._channels)

    def status(self) -> dict:
        return {name: ch.status() for name, ch in self._channels.items()}

    def act(self, name: str, action: str, background: bool = False) -> bool:
        """action 是 start / stop / restart。background=True：丟到背景做（從那個 channel 自己的執行緒呼叫時）。"""
        channel = self._channels.get(name)
        if channel is None or action not in ("start", "stop", "restart"):
            return False
        if background:
            threading.Thread(target=getattr(channel, action), daemon=True,
                             name=f"Channel-{name}-{action}").start()
            return True
        return bool(getattr(channel, action)())

    def stop_all(self) -> None:
        for channel in self._channels.values():
            channel.stop()
