"""
Runtime：常駐的排程迴圈、心跳、常駐助理（母 session）、soul.md（docs/adr/0001；網頁 API docs/runtime-api.md）。

    rt = runtime.install(app, config, vault)     app.build 在 agent.install 之後、schedule.install 之前叫
    rt.loop        RuntimeLoop：登記任務、回報狀態、App.run 時啟動
    rt.heartbeat   Heartbeat：system.heartbeat
    rt.mother      MotherSession：只給擁有者、沒有工具
    rt.soul        SoulStore：soul.md（保管箱）
    rt.activator   Activator：連動規則（任務狀態一變就做下一件事；防無限連動，docs/adr/0004）
    rt.keep_awake  KeepAwake：system.keep_awake（電腦不睡著、螢幕可以熄；docs/adr/0006）
    rt.ledger      SoulLedger：助理筆記的來歷、等你確認的提議、整理與遺忘（docs/adr/0005；任務 system.soul_tidy）

pack 回報狀態：`runtime.report(app, pack_name, state, message, tag=)`（loader 收 cli 信封的 status、Pack.report_status 都走這裡）。
登記連動規則：`runtime.add_rule(app, rule)`（Pack.on_event 走這裡）；runtime 還沒裝上（pack 比 runtime 早載入）就先排著，install 時再登記。
這個檔不要在模組層 import 會 import config 的東西（config.py import runtime.settings）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Callable, Optional

RUNTIME_KEY = "synox_runtime"
RULE_QUEUE_KEY = "synox_activator_queue"
PEER_ENV = "SYNOX_PEER_STATUS"
PEER_MAX = 50


class Runtime:

    def __init__(self, loop, heartbeat, mother, soul, config_path: str = "", activator=None, ledger=None,
                 keep_awake=None):
        self.loop = loop
        self.heartbeat = heartbeat
        self.mother = mother
        self.soul = soul
        self.ledger = ledger
        self.config_path = config_path
        self.activator = activator
        self.keep_awake = keep_awake

    def use_fakes(self, *, clock: Optional[Callable[[], float]] = None, now: Optional[Callable[[], datetime]] = None,
                  spawn: Optional[Callable] = None) -> "Runtime":
        """測試用：換假時鐘（epoch 秒與 datetime 兩種）、同步執行（spawn=lambda fn, name: fn()）。"""
        if clock is not None:
            old_now, new_now = self.loop._clock(), clock()   # 已排好的下一次照新時鐘平移（取整秒）
            self.loop._clock = self.mother._clock = self.soul._clock = clock
            if self.ledger is not None:
                self.ledger._clock = clock
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
        out = {"heartbeat": self.heartbeat.view(),
               "mother": {"state": self.mother.state, "ai": self.mother.adapter is not None, "last_active_at": iso(self.mother_last_active()),
                          "soul_updated_at": iso(soul_at)},
               "tasks": self.loop.views()}
        if self.activator is not None:
            out["activator"] = self.activator.view()
        if self.keep_awake is not None:
            out["keep_awake"] = self.keep_awake.view()
        return out

    def mother_last_active(self) -> Optional[float]:
        self.mother.memory()                   # 第一次讀記憶時順便拿到上一次的時間（重開之後）
        return self.mother.last_active_at


def install(app, config, vault=None, *, config_path: str = "") -> Runtime:
    from synox.runtime import settings as rs
    from synox.runtime.activator import Activator, RuleError, rules_from_config
    from synox.runtime.heartbeat import Heartbeat
    from synox.runtime.keepawake import KeepAwake
    from synox.runtime.ledger import SoulLedger, SoulTidy
    from synox.runtime.loop import RuntimeLoop
    from synox.runtime.mother import MotherSession
    from synox.runtime.soul import SoulStore

    conf = getattr(config, "runtime", None) or rs.defaults()
    loop = RuntimeLoop(app)
    agent = app.extras.get("synox_agent")
    adapter = getattr(agent, "adapter", None)
    soul = SoulStore(vault)
    mother = MotherSession(app, adapter, soul, settings=conf["mother"], vault=vault)
    act_conf = conf.get("activator") or rs.defaults()["activator"]
    activator = Activator(loop, settings=act_conf)
    for rule in rules_from_config(act_conf.get("rules") or []):     # config.json 的（已在 settings.parse 檢查過循環）
        activator.add(rule)
    for rule in app.extras.pop(RULE_QUEUE_KEY, []):                   # pack 載入時排著的
        try:
            activator.add(rule, strict=False)
        except RuleError as e:
            activator.rejected[rule.id] = str(e)
            logging.warning("[RUNTIME] %s", e)
    ledger = SoulLedger(soul, vault, review=bool(conf["mother"].get("soul_review", False)), mother=mother)
    heartbeat = Heartbeat(app, loop, mother, settings=conf["heartbeat"], read_chat=conf["mother"]["read_chat"],
                          soul_append=conf["mother"]["soul_append"], ledger=ledger)
    heartbeat.activator = activator
    heartbeat.register()
    SoulTidy(app, ledger, quiet=heartbeat._in_quiet).register(loop)
    keep_awake = KeepAwake(loop, settings=conf.get("keep_awake") or rs.defaults()["keep_awake"])
    rt = Runtime(loop, heartbeat, mother, soul, config_path=config_path, activator=activator, ledger=ledger,
                 keep_awake=keep_awake)
    app.extras[RUNTIME_KEY] = rt
    app.on_start.append(lambda _app: keep_awake.register())     # 跑起來才請求（測試、doctor 只 build 不啟動，不會動到電腦的睡眠）
    app.on_start.append(lambda _app: loop.start())
    app.on_stop.append(lambda _app: loop.stop())
    app.on_stop.append(lambda _app: keep_awake.release())
    return rt


def of(app) -> Optional[Runtime]:
    return getattr(app, "extras", {}).get(RUNTIME_KEY) if app is not None else None


def report(app, pack_name: str, state: str, message: str = "", *, title: str = "", tag: str = "") -> bool:
    """pack 回報狀態 → 任務 pack.<pack_name>。沒有 runtime、state 不合法＝False（不丟例外：回報不能弄壞工具）。
    tag：選填的短標籤（連動規則可以只聽某個標籤，例如 "diary-image"）；不合格式＝當作沒有。"""
    rt = of(app)
    if rt is None:
        return False
    try:
        return rt.loop.report(f"pack.{pack_name}", state, message, name=title or pack_name, owner=pack_name,
                              tag=tag) is not None
    except Exception:
        logging.exception("[RUNTIME] report from %s failed", pack_name)
        return False


def add_rule(app, rule):
    """登記一條連動規則（Pack.on_event、系統程式）。形狀錯丟 RuleError（給寫的人看）；
    會繞回自己＝不收、記在主控面板的「沒收的規則」、回 None（不讓整個 pack 載入失敗）。
    runtime 還沒裝上＝先排著（pack 比 runtime 早載入），install 時再登記，回 None。"""
    rule.check()
    rt = of(app)
    if rt is None or rt.activator is None:
        app.extras.setdefault(RULE_QUEUE_KEY, []).append(rule)
        return None
    return rt.activator.add(rule, strict=False)


def ingest_envelope(app, pack_name: str, envelope, *, title: str = "") -> bool:
    """cli 工具的 JSON 信封有 "status": {"state", "message", "tag"?} → report。沒有或格式不對＝什麼都不做。"""
    status = envelope.get("status") if isinstance(envelope, dict) else None
    if not isinstance(status, dict):
        return False
    state = status.get("state")
    message = status.get("message", "")
    tag = status.get("tag", "")
    if not isinstance(state, str) or not isinstance(message, (str, type(None))):
        return False
    return report(app, pack_name, state, message or "", title=title, tag=tag if isinstance(tag, str) else "")


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


__all__ = ["PEER_ENV", "Runtime", "add_rule", "ingest_envelope", "install", "of", "peer_env", "peer_status", "report"]
