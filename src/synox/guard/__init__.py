"""門禁核心（ADR 0025）：誰做的（origin）、能不能做（scope、stepup）、輸入乾不乾淨（inputs）、次數（limits）、紀錄（audit）。

    guard = install(app, config, vault)      # app.build 裡呼叫（保管箱設好之後、basics.install 之前）
    of(app) -> Guard                         # app.extras["synox_guard"]

install 做的事（ADR 0025 §5.6、計畫 K3）：
- 建 `Audit`（`data/security_audit.jsonl`）、`Scope`（範圍對照表）、`StepUp`（驗證器；金鑰在保管箱，打不開就永遠沒設定）。
- `registry.stepup`、`forms._stepup` 換成 SYNOX 的轉接物件；`app.stepup` 在擁有者設定好之前是 None
  （SDK 的帳號指令看到 None 就不多擋，所以伺服器版沒設定也給得了管理員，ADR 0025 G5）。
- 裝 🔐 解鎖指令（guard/commands.py）。
- 包一層 `app.dispatcher.handle`：外面已經有來源就沿用；沒有就照 `inbound.channel` 設（telegram／discord／console；
  排程造的訊息＝schedule；其他＝unknown）。SDK 的入口都用 `app.dispatcher.handle(...)` 呼叫，所以蓋實例屬性就蓋得到
  （跟 policy.install 蓋 `_hidden_from` 同一招；vendor 不改）。

origin、inputs、limits、audit 這幾個檔不 import synox 的其他模組；這個檔是接到 SYNOX 的那一層。
"""

from __future__ import annotations

import os
from typing import Optional

from synox.guard import origin as origin_mod
from synox.guard.audit import FILE as AUDIT_FILE, Audit
from synox.guard.scope import Scope
from synox.guard.stepup import StepUp
from synox.guard.store import NullStore, VaultStore

EXTRA = "synox_guard"


class Guard:
    def __init__(self, audit: Audit, stepup=None, scope=None):
        self.audit = audit
        self.stepup = stepup
        self.scope = scope


def of(app) -> Optional[Guard]:
    extras = getattr(app, "extras", None) or {}
    return extras.get(EXTRA)


def _wrap_dispatcher(app) -> None:
    dispatcher = getattr(app, "dispatcher", None)
    if dispatcher is None or getattr(dispatcher, "_synox_origin", False):
        return
    original = dispatcher.handle

    def handle(api, inbound, via="typed"):
        if origin_mod.current().kind != "unknown":
            return original(api, inbound, via)
        o = origin_mod.from_inbound(getattr(inbound, "channel", ""), via, getattr(inbound, "user_id", 0))
        with origin_mod.using(o):
            return original(api, inbound, via)

    dispatcher.handle = handle
    dispatcher._synox_origin = True


def _wrap_tasks(app) -> None:
    """丟到背景的工作（AI 那一輪、網頁的母對話…）帶著丟的那一刻的來源（contextvar 不會自己跟到新執行緒）。"""
    tasks = getattr(app, "tasks", None)
    if tasks is None or getattr(tasks, "_synox_origin", False):
        return
    original = tasks.run

    def run(fn, name="task"):
        return original(origin_mod.carry(fn), name=name)

    tasks.run = run
    tasks._synox_origin = True


def install(app, config, vault) -> Guard:
    existing = of(app)
    if existing is not None:
        return existing
    data_dir = getattr(config, "data_dir", "") or getattr(getattr(app, "config", None), "data_dir", "") or "."
    audit = Audit(os.path.join(str(data_dir), AUDIT_FILE))
    server = getattr(config, "mode", "personal") == "server"
    store = VaultStore(vault, server) if vault is not None else NullStore()
    owner_id = int(getattr(config, "owner_id", 0) or 0)

    def notify(uid: int, text: str) -> None:
        app.notify(uid, text)

    hub = StepUp(store, owner_id=owner_id, minutes=int(getattr(config, "stepup_minutes", 15) or 15),
                 audit=audit, notify=notify)
    guard = Guard(audit, stepup=hub, scope=Scope())
    app.extras[EXTRA] = guard
    _wrap_dispatcher(app)
    _wrap_tasks(app)
    adapter = hub.sdk()
    app.registry.stepup = adapter
    forms = getattr(app, "forms", None)
    if forms is not None:
        forms._stepup = adapter

    def refresh(_uid: int = 0) -> None:
        app.stepup = adapter if hub.enrolled(owner_id) else None
    refresh()
    hub.on_change(refresh)
    from synox.guard import commands
    commands.install(app, hub, guard.scope)
    return guard
