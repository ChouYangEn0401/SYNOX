"""
JsonCli：把一支「會印 JSON 的命令列程式」包成 Python 呼叫。範本 B（服務操作台）的核心。

ClawBot 跟旁邊的 ISDInfoCollectorDeck、ClaudeTimerResetter 就是這樣接了好幾個月，分工很清楚：
  服務那邊只管做事：子指令＋--json，最後一行印一個 JSON 物件，結束碼 0＝成功；完全不碰 Telegram
                    （bot token 只存在 bot 這邊一份）。
  bot 這邊只管「誰能下令、能下多大的令」、送訊息、按鈕、排程。

    cli = JsonCli(jobs, [python, "-m", "myservice.cli"], cwd=SERVICE_DIR, name="svc")
    reply = cli.call("status")                          # 會阻塞，見下面
    if reply.ok:
        api.send_message(chat_id, f"線上人數：{reply.data['players']}")
    else:
        api.send_message(chat_id, f"❌ {reply.error}")

    cli.start("download", url, on_done=lambda reply: notify(reply))   # 背景跑，做完回呼

- 一律經 JobRunner：argv 陣列（不收 shell 字串）、不開視窗、輸出進 log、有逾時、取消會收掉整棵程序樹。
- call() 會阻塞到程式結束：不要在收訊的執行緒上呼叫（Telegram 那幾秒會收不到別的訊息）。指令 handler 裡要嘛用
  start(on_done=…)，要嘛自己丟背景執行緒（packs 與範本 B 的 service/ 都是這樣做）。
- 子程序的環境拿掉看起來像密鑰的變數（*_API_KEY、*_SECRET、*_PASSWORD、*_TOKEN…，keep 可以留幾個）：
  服務不該看得到 bot 的 token。
- 程式在 JSON 前面多印幾行（警告、資料庫升級訊息）沒關係：取最後一個 JSON 物件。沒有 JSON 就當失敗，
  錯誤訊息附上輸出的最後一段。
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

from isdtelekit.jobs.runner import Job, JobRunner, child_env, read_log

EXIT_OK, EXIT_UNAVAILABLE = 0, -1
_SECRET_NAME = re.compile(r"(API_?KEY|SECRET|PASSWORD|PASSWD|_TOKEN)$", re.IGNORECASE)


def clean_env(extra: Optional[Dict[str, str]] = None, keep: Sequence[str] = ()) -> Dict[str, str]:
    """子程序的環境：照目前的環境，但拿掉名字看起來像密鑰的變數（keep 裡的照留）；PYTHONIOENCODING=utf-8。"""
    keep_upper = {k.upper() for k in keep}
    env = child_env(extra)
    for name in list(env):
        if name.upper() not in keep_upper and _SECRET_NAME.search(name):
            env.pop(name, None)
    return env


def last_json(text: str) -> Optional[dict]:
    """輸出裡最後一個 JSON 物件（一整行的 {…}）；沒有就 None。"""
    for line in reversed([ln for ln in (text or "").strip().splitlines() if ln.strip()]):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if isinstance(data, dict):
                return data
    return None


@dataclass
class CliReply:
    """一次呼叫的結果。code：結束碼（-1＝這邊叫不起來）；data：最後一個 JSON 物件；raw：完整輸出。"""
    code: int
    data: dict = field(default_factory=dict)
    raw: str = ""
    job_id: str = ""

    @property
    def ok(self) -> bool:
        """結束碼 0，而且 JSON 沒有明說 "ok": false。"""
        return self.code == EXIT_OK and self.data.get("ok", True) is not False

    @property
    def error(self) -> str:
        """給人看的失敗原因：JSON 的 reason／error／message，都沒有就是結束碼。"""
        if self.ok:
            return ""
        return str(self.data.get("reason") or self.data.get("error") or self.data.get("message")
                   or f"結束碼 {self.code}")


class JsonCli:

    def __init__(self, jobs: JobRunner, argv_prefix: Sequence[str], *, cwd: Optional[str] = None,
                 name: str = "cli", timeout: float = 120.0, json_flag: Optional[str] = "--json",
                 env_extra: Optional[Dict[str, str]] = None, keep_env: Sequence[str] = ()):
        """argv_prefix：子指令前面固定的那幾段（例如 [venv 的 python, "-m", "myservice.cli"]）。
        json_flag：每次呼叫附在最後面的旗標（服務本來就只印 JSON 的話給 None）。"""
        self._jobs = jobs
        self.argv_prefix = [str(a) for a in argv_prefix]
        self.cwd = cwd
        self.name = name
        self.timeout = timeout
        self.json_flag = json_flag
        self._env_extra = env_extra
        self._keep_env = tuple(keep_env)

    def unavailable(self) -> Optional[str]:
        """叫不起來的原因（程式或工作資料夾不存在）；None＝看起來可以用。"""
        program = self.argv_prefix[0] if self.argv_prefix else ""
        if not program:
            return "沒有設定要呼叫的程式。"
        if (os.sep in program or "/" in program) and not os.path.isfile(program):
            return f"找不到 {program}。"
        if self.cwd and not os.path.isdir(self.cwd):
            return f"找不到服務的資料夾 {self.cwd}。"
        return None

    def argv(self, *args: str) -> List[str]:
        return self.argv_prefix + [str(a) for a in args] + ([self.json_flag] if self.json_flag else [])

    def _job_name(self, args: Sequence[str]) -> str:
        return f"{self.name}_{args[0]}" if args else self.name

    def call(self, *args: str, timeout: Optional[float] = None, stdin: Optional[str] = None) -> CliReply:
        """跑一個子指令，等它結束（會阻塞）。"""
        problem = self.unavailable()
        if problem:
            return CliReply(EXIT_UNAVAILABLE, {"reason": problem})
        try:
            job = self._jobs.run(self._job_name(args), self.argv(*args), cwd=self.cwd,
                                 timeout=self.timeout if timeout is None else timeout, env=self._env(),
                                 input_text=stdin)
        except OSError as e:
            return CliReply(EXIT_UNAVAILABLE, {"reason": f"叫不起來：{e}"})
        return self.reply_of(job)

    def start(self, *args: str, on_done: Callable[[CliReply], None], timeout: Optional[float] = None,
              stdin: Optional[str] = None) -> Optional[Job]:
        """在背景跑，結束時呼叫 on_done(reply)（在 JobRunner 的看守執行緒上）。叫不起來就立刻 on_done、回 None。"""
        problem = self.unavailable()
        if problem:
            on_done(CliReply(EXIT_UNAVAILABLE, {"reason": problem}))
            return None

        def finished(job: Job) -> None:
            try:
                on_done(self.reply_of(job))
            except Exception:
                logging.exception("[CLI] %s on_done failed", self.name)

        try:
            return self._jobs.start(self._job_name(args), self.argv(*args), cwd=self.cwd,
                                    timeout=self.timeout if timeout is None else timeout, env=self._env(),
                                    input_text=stdin, on_done=finished)
        except OSError as e:
            on_done(CliReply(EXIT_UNAVAILABLE, {"reason": f"叫不起來：{e}"}))
            return None

    @staticmethod
    def reply_of(job: Job) -> CliReply:
        raw = read_log(job.log_path)
        data = last_json(raw)
        code = job.returncode if job.returncode is not None else 1
        if data is None:
            tail = " ".join(raw.split())[-300:]
            return CliReply(code if code != EXIT_OK else 1,
                            {"reason": f"沒有回 JSON（{job.state}）：{tail or '沒有輸出'}"}, raw, job.id)
        return CliReply(code, data, raw, job.id)

    def _env(self) -> Dict[str, str]:
        return clean_env(self._env_extra, keep=self._keep_env)
