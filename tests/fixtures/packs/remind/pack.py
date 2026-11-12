"""⏰ 提醒：程式在 synox/schedule（排程器也替 /schedule_* 跑指令），這裡只把 /remind_* 掛到這個 pack 的群組。"""

from synox.schedule import commands


def install(app, pack):
    commands.install_remind(app, pack.group)
