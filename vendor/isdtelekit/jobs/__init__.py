"""
外部程式一律經這裡：runner.py 的 JobRunner（argv 陣列、不開視窗、逾時、取消會收掉整棵程序樹、bot 結束時子程序
跟著結束——除非 survive_bot），以及 cli.py 的 JsonCli（把一支會印 JSON 的命令列程式包成 Python 呼叫）。
"""

from isdtelekit.jobs.cli import CliReply, JsonCli, clean_env, last_json
from isdtelekit.jobs.runner import CANCELLED, FAILED, RUNNING, SUCCEEDED, TIMED_OUT, Job, JobRunner, read_log

__all__ = ["CANCELLED", "FAILED", "RUNNING", "SUCCEEDED", "TIMED_OUT", "CliReply", "Job", "JobRunner", "JsonCli",
           "clean_env", "last_json", "read_log"]
