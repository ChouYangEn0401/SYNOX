"""
Runtime：常駐的排程迴圈、心跳、常駐助理（母 session）、soul.md（docs/adr/0001；網頁 API docs/runtime-api.md）。

    rt = runtime.install(app, config, vault)     app.build 在 agent.install 之後、schedule.install 之前叫
    rt.loop        RuntimeLoop：登記任務、回報狀態、App.run 時啟動
    rt.heartbeat   Heartbeat：system.heartbeat
    rt.mother      MotherSession：只給擁有者、沒有工具
    rt.soul        SoulStore：soul.md（保管箱）

pack 回報狀態：`runtime.report(app, pack_name, state, message)`（loader 收 cli 信封的 status、Pack.report_status 都走這裡）。
這個檔不要在模組層 import 會 import config 的東西（config.py import runtime.settings）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Callable, Optional

RUNTIME_KEY = "synox_runtime"
PEER_ENV = "SYNOX_PEER_STATUS"
PEER_MAX = 50


class Runtime:

    def __init__(self, loop, heartbeat, mother, soul, config_path: str = ""):
        self.loop = loop
        self.heartbeat = heartbeat
        self.mother = mother
        self.soul = soul
        self.config_path = config_path

    def use_fakes(self, *, clock: Optional[Callable[[], float]] = None, now: Optional[Callable[[], datetime]] = None,
                  spawn: Optional[Callable] = None) -> "Runtime":
        """測試用：換假時鐘（epoch 秒與 datetime 兩種）、同步執行（spawn=lambda fn, name: fn()）。"""
        if clock is not None:
            old_now, new_now = self.loop._clock(), clock()   # 已排好的下一次照新時鐘平移（取整秒）
            self.loop._clock = self.mother._clock = self.soul._clock = clock
            for task in self.loop.tasks.values():
                task._clock = clock
                if task.next_due is not None:
                    task.next_due = new_now + round(task.next_due - old_now)
        if now is not None:
            self.heartbeat._now = now
        if spawn is not None:
            self.loop._spawn = spawn
        return self

    def status(self) -> dict:
        try:
            soul_at = self.soul.updated_at() if self.soul.available else None
        except Exception:
            soul_at = None
        from synox.runtime.loop import iso
        return {"heartbeat": self.heartbeat.view(),
                "mother": {"state": self.mother.state, "last_active_at": iso(self.mother_last_active()),
                           "soul_updated_at": iso(soul_at)},
                "tasks": self.loop.views()}

    def mother_last_active(self) -> Optional[float]:
        self.mother.memory()                   # 第一次讀記憶時順便拿到上一次的時間（重開之後）
        return self.mother.last_active_at


def install(app, config, vault=None, *, config_path: str = "") -> Runtime:
    from synox.runtime import settings as rs
    from synox.runtime.heartbeat import Heartbeat
    from synox.runtime.loop import RuntimeLoop
    from synox.runtime.mother import MotherSession
    from synox.runtime.soul import SoulStore

    conf = getattr(config, "runtime", None) or rs.defaults()
    loop = RuntimeLoop(app)
    agent = app.extras.get("synox_agent")
    adapter = getattr(agent, "adapter", None)
    soul = SoulStore(vault)
    mother = MotherSession(app, adapter, soul, settings=conf["mother"], vault=vault)
    heartbeat = Heartbeat(app, loop, mother, settings=conf["heartbeat"], read_chat=conf["mother"]["read_chat"],
                          soul_append=conf["mother"]["soul_append"])
    heartbeat.register()
    rt = Runtime(loop, heartbeat, mother, soul, config_path=config_path)
    app.extras[RUNTIME_KEY] = rt
    app.on_start.append(lambda _app: loop.start())
    app.on_stop.append(lambda _app: loop.stop())
    return rt


def of(app) -> Optional[Runtime]:
    return getattr(app, "extras", {}).get(RUNTIME_KEY) if app is not None else None


def report(app, pack_name: str, state: str, message: str = "", *, title: str = "") -> bool:
    """pack 回報狀態 → 任務 pack.<pack_name>。沒有 runtime、state 不合法＝False（不丟例外：回報不能弄壞工具）。"""
    rt = of(app)
    if rt is None:
        return False
    try:
        return rt.loop.report(f"pack.{pack_name}", state, message, name=title or pack_name, owner=pack_name) is not None
    except Exception:
        logging.exception("[RUNTIME] report from %s failed", pack_name)
        return False


def ingest_envelope(app, pack_name: str, envelope, *, title: str = "") -> bool:
    """cli 工具的 JSON 信封有 "status": {"state", "message"} → report。沒有或格式不對＝什麼都不做。"""
    status = envelope.get("status") if isinstance(envelope, dict) else None
    if not isinstance(status, dict):
        return False
    state = status.get("state")
    message = status.get("message", "")
    if not isinstance(state, str) or not isinstance(message, (str, type(None))):
        return False
    return report(app, pack_name, state, message or "", title=title)


def peer_status(app) -> dict:
    """別人的狀態（只有 state 與時間）。"""
    rt = of(app)
    return rt.loop.peer_states() if rt is not None else {}


def peer_env(app) -> dict:
    """給 cli 子程序的環境變數 SYNOX_PEER_STATUS（最多 PEER_MAX 個任務）；沒有 runtime＝{}。"""
    peers = peer_status(app)
    if not peers:
        return {}
    items = dict(sorted(peers.items())[:PEER_MAX])
    return {PEER_ENV: json.dumps(items, ensure_ascii=True, separators=(",", ":"))}


__all__ = ["PEER_ENV", "Runtime", "ingest_envelope", "install", "of", "peer_env", "peer_status", "report"]
