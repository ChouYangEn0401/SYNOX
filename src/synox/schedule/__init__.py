"""排程（SDK 沒有，decisions.md D6）：/remind_*（系統指令「⏰ 提醒（系統）」，install_system_remind）、/schedule_*、背景的 ScheduleRunner。
提醒引擎（engine.py）、延後與完成（actions.py）、時間用語（timeparse.py）：docs/adr/0029。"""

from synox.schedule.commands import install_remind, install_schedule, install_system_remind, store_for
from synox.schedule.runner import CHECK_INTERVAL, MAX_BACKOFF, ScheduleRunner


TASK_ID = "system.schedule"


def install(app) -> ScheduleRunner:
    """/schedule_* 群組＋排程器。/remind_*（⏰ 提醒（系統））由 install_system_remind 在 packs 載入之前掛（app.build）。
    有 runtime（synox/runtime，docs/adr/0001）：登記成任務 system.schedule（睡到下一件事的時間、最多 CHECK_INTERVAL 秒
    一定看一次；清單有寫入就 poke 馬上重看；逾時 120 秒、失敗退避最多 1 分鐘、狀態看得到），不另開執行緒；
    沒有 runtime（舊的組法）：照舊自己開執行緒（App.run 開始收訊時啟動、停止時停），一樣睡到下一件事。
    延後與完成（ReminderActions）登記在 app.extras["synox_reminder_actions"]，送達層的按鈕回頭叫它。"""
    from synox.notify import delivery
    from synox.schedule.actions import Actions
    from synox.schedule.engine import app_resolve
    install_schedule(app)
    store = store_for(app)
    runner = ScheduleRunner(app, store)
    app.extras["synox_schedule_runner"] = runner
    actions = Actions(store, resolve=lambda uid, key, **kw: app_resolve(app, uid, key, **kw),
                      todos=lambda uid, items: delivery.publish_todos(app, uid, items))
    app.extras[delivery.ACTIONS_EXTRA] = actions
    owner = getattr(app, "owner_id", None)
    if owner:                                          # 開起來時把待辦交給電腦視窗一次（哨兵那段時間可能改過）
        app.on_start.append(lambda _app: actions.publish_todos(int(owner)))
    rt = app.extras.get("synox_runtime")
    if rt is not None:
        rt.loop.register(TASK_ID, "提醒與排程", fn=lambda ctx: _tick_text(runner.tick()), interval=CHECK_INTERVAL,
                         timeout=120.0, first_delay=0, max_backoff=MAX_BACKOFF,
                         next_hint=lambda _now: runner.next_wake_ts(),
                         schedule=f"到點就跑（最多每 {CHECK_INTERVAL} 秒看一次）")
        store.add_listener(lambda: rt.loop.poke(TASK_ID))
        return runner
    store.add_listener(runner.poke)
    app.on_start.append(lambda _app: runner.start())
    app.on_stop.append(lambda _app: runner.stop())
    return runner


def _tick_text(fired) -> str:
    return f"做了 {len(fired)} 項" if fired else "沒有到點的項目"


__all__ = ["ScheduleRunner", "install", "install_remind", "install_schedule", "install_system_remind", "store_for"]
