"""
/sys_jobs、/sys_job_cancel：看 bot 啟動的外部程式（jobs/runner.py 的 JobRunner），必要時停掉（連同子程序）。
只給機器擁有者：停掉的東西都跑在擁有者的電腦上。停掉是 🔐（有接 /sudo 的話要先解鎖）。
"""

from __future__ import annotations

from isdtelekit.core.registry import DANGER
from isdtelekit.jobs.runner import RUNNING


def install(app, *, group: str = "sys") -> None:
    jobs = app.jobs
    app.registry.ensure_group(group, "🖥 這台電腦", "看與停止 bot 啟動的外部程式", owner_only=True)

    def cmd_jobs(api, chat_id, user, args):
        listed = jobs.list()[:20]
        if not listed:
            api.send_message(chat_id, "目前沒有任何工作紀錄（bot 重啟後從零開始記）。")
            return
        running = [j for j in listed if j.state == RUNNING]
        lines = [f"🧰 工作（執行中 {len(running)}）"]
        for j in listed:
            icon = "⏳" if j.state == RUNNING else ("✅" if j.returncode == 0 else "❌")
            until = f"，到期 {j.deadline:%m/%d %H:%M}" if j.state == RUNNING and j.deadline else ""
            lines.append(f"{icon} {j.summary()}  {j.started_at:%m/%d %H:%M}{until}")
        if running:
            lines.append(f"\n停掉：/{group}_job_cancel <編號>")
        api.send_message(chat_id, "\n".join(lines))

    def cmd_job_cancel(api, chat_id, user, args):
        if not args:
            api.send_message(chat_id, f"用法：/{group}_job_cancel <編號>（編號看 /{group}_jobs）")
            return
        job_id = args[0].lstrip("#")
        job = jobs.get(job_id)
        if job is None or job.state != RUNNING:
            api.send_message(chat_id, f"❌ 沒有執行中的工作 #{job_id}。")
            return
        jobs.cancel(job_id)
        api.send_message(chat_id, f"🛑 已停掉 #{job_id} {job.name}（連同它開的子程序）。")

    g = app.registry.group(group)
    g.leaf("jobs", cmd_jobs, "看 bot 啟動的外部程式與結果")
    g.leaf("job_cancel", cmd_job_cancel, "停掉執行中的工作（連同子程序）", usage="<編號>", effect=DANGER,
           elevated=app.stepup is not None)
