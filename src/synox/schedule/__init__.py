"""排程（SDK 沒有，decisions.md D6）：/remind_*（掛在 packs/remind）、/schedule_*、背景的 ScheduleRunner。"""

from synox.schedule.commands import install_remind, install_schedule, store_for
from synox.schedule.runner import ScheduleRunner


def install(app) -> ScheduleRunner:
    """/schedule_* 群組＋排程器（App.run 開始收訊時啟動、停止時停）。/remind_* 由 packs/remind 掛。"""
    install_schedule(app)
    runner = ScheduleRunner(app, store_for(app))
    app.extras["synox_schedule_runner"] = runner
    app.on_start.append(lambda _app: runner.start())
    app.on_stop.append(lambda _app: runner.stop())
    return runner


__all__ = ["ScheduleRunner", "install", "install_remind", "install_schedule", "store_for"]
