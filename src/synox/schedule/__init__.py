"""排程（SDK 沒有，decisions.md D6）：/remind_*（系統指令「⏰ 提醒（系統）」，install_system_remind）、/schedule_*、背景的 ScheduleRunner。"""

from synox.schedule.commands import install_remind, install_schedule, install_system_remind, store_for
from synox.schedule.runner import CHECK_INTERVAL, ScheduleRunner


TASK_ID = "system.schedule"


def install(app) -> ScheduleRunner:
    """/schedule_* 群組＋排程器。/remind_*（⏰ 提醒（系統））由 install_system_remind 在 packs 載入之前掛（app.build）。
    有 runtime（synox/runtime，docs/adr/0001）：登記成任務 system.schedule（每 30 秒，逾時 120 秒、失敗退避、狀態看得到），
    不另開執行緒；沒有 runtime（舊的組法）：照舊自己開執行緒（App.run 開始收訊時啟動、停止時停）。"""
    install_schedule(app)
    runner = ScheduleRunner(app, store_for(app))
    app.extras["synox_schedule_runner"] = runner
    rt = app.extras.get("synox_runtime")
    if rt is not None:
        rt.loop.register(TASK_ID, "提醒與排程", fn=lambda ctx: _tick_text(runner.tick()), interval=CHECK_INTERVAL,
                         timeout=120.0, first_delay=0)
        return runner
    app.on_start.append(lambda _app: runner.start())
    app.on_stop.append(lambda _app: runner.stop())
    return runner


def _tick_text(fired) -> str:
    return f"做了 {len(fired)} 項" if fired else "沒有到點的項目"


__all__ = ["ScheduleRunner", "install", "install_remind", "install_schedule", "install_system_remind", "store_for"]
