"""
把一支「會印 JSON 的命令列程式」（jobs/cli.py 的 JsonCli）的子指令，一行一個開通成 bot 指令。
範本 B（服務操作台）的核心：bot 是那個服務的第二個 CLI 入口。

    COMMANDS = [
        ServiceCommand("status", ["status"], "看服務狀態"),
        ServiceCommand("create", ["create", "{room}", "--size", "{size}"], "開一個房間", effect=WRITE,
                       fields=[Field("room", "房間名稱", required=True), Field("size", "幾個人", default="6")]),
        ServiceCommand("download", ["download", "{url}"], "下載影片", fields=[Field("url", "網址", required=True)],
                       background=True, timeout=1800, quota="downloads"),
    ]
    bridge = service.install(app, cli, COMMANDS, group="svc")      # → /svc_status、/svc_create、/svc_download

- 每個子指令變成一個表單指令（core/forms.py）：一次打齊就送出、缺必填就一題一題問、按鈕可以預填。
- argv 樣板裡的 {欄位} 換成值；選填欄位沒值 → 那一段拿掉（緊接在前面的 --旗標 一起拿掉）。
  值一律是單獨一個 argv 元素（不經 shell）；以 - 開頭的值直接拒絕，免得被服務當成旗標（例如 --delete-all）。
- user_args(user)：每次呼叫都附在最後（例如 ["--user", "123", "--name", "amy"]），服務才知道是誰在下令。
- 不會卡住收訊的執行緒：一般指令丟 app.tasks（host/app.py 的 TaskTracker）等結果再回覆——終端機模式會等它回完；
  background=True 的先回「⏳ 開始了」，做完再通知下令的人（跑多久都行，逾時由 JobRunner 收掉整棵程序樹）。
- 回覆：render(ctx) 自己決定（ctx 有 app、api、chat_id、user、values、reply；可以順便私訊別人，例如發牌）；
  沒給就用 default_render：data 的 message／text，或把簡單的欄位列成 key: value。失敗一律「❌ <服務說的原因>」。
- quota="downloads"：跑之前扣每日配額（limits/rate_limiter.py 的計數器；表上沒寫＝不能用）。
- raw=True：多一個 /<群組>_raw <子指令…>（只給擁有者、要先 /sudo、危險），直接呼叫任何子指令，除錯用。
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import threading
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

from isdtelekit.core.registry import DANGER, READ, Field
from isdtelekit.jobs.cli import CliReply, JsonCli

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@dataclass
class ServiceContext:
    """render() 拿到的東西。"""
    app: object
    api: object
    chat_id: int
    user: object
    values: dict
    reply: CliReply


@dataclass
class ServiceCommand:
    name: str                                   # 指令名：/<群組>_<name>
    argv: Sequence[str]                         # 子指令與參數的樣板："create", "{room}", "--size", "{size}"
    summary: str                                # /help 與選單上的說明
    fields: Sequence[Field] = ()                # 表單欄位（名字要跟樣板裡的 {…} 對上）
    effect: str = READ
    role: Optional[int] = None                  # 比群組下限更嚴才給
    owner_only: bool = False
    elevated: bool = False
    background: bool = False                    # 跑很久：先回「開始了」，做完通知
    timeout: Optional[float] = None             # 沒給就用 JsonCli 的預設
    quota: Optional[str] = None                 # 跑之前扣這個每日配額計數器
    render: Optional[Callable[[ServiceContext], Optional[str]]] = None
    usage: str = ""
    default: bool = False                       # /<群組> 就是它


def build_argv(template: Sequence[str], values: dict) -> List[str]:
    """樣板 → argv。{x} 換成 values["x"]；值是空的那一段拿掉，前面緊鄰的 --旗標 一起拿掉。"""
    out: List[str] = []
    for token in template:
        names = _PLACEHOLDER.findall(token)
        if names and any(not str(values.get(n, "") or "").strip() for n in names):
            if out and out[-1].startswith("-") and not _PLACEHOLDER.search(out[-1]):
                out.pop()
            continue
        out.append(_PLACEHOLDER.sub(lambda m: str(values[m.group(1)]).strip(), token))
    return out


def default_render(ctx: ServiceContext) -> str:
    data = ctx.reply.data
    for key in ("message", "text", "summary"):
        if data.get(key):
            return str(data[key])
    lines = [f"{k}: {v}" for k, v in data.items() if k != "ok" and not isinstance(v, (dict, list))]
    lines += [f"{k}: {len(v)} 筆" for k, v in data.items() if isinstance(v, (dict, list))]
    return "\n".join(lines) or "✅ 完成"


def _no_dash(fld: Field) -> Field:
    """值不能以 - 開頭（不然服務會把它當旗標）；原本的 check 照樣跑。"""
    original = fld.check

    def check(value: str) -> Optional[str]:
        if value.strip().startswith("-"):
            return "不能用 - 開頭"
        return original(value) if original else None

    return dataclasses.replace(fld, check=check)


class ServiceBridge:
    """install() 回傳的東西。每一次呼叫一個 Event，回覆送出之後才設好——測試用 wait() 等它們。"""

    def __init__(self):
        self._pending: List[threading.Event] = []
        self._lock = threading.Lock()

    def _started(self) -> threading.Event:
        done = threading.Event()
        with self._lock:
            self._pending = [e for e in self._pending if not e.is_set()] + [done]
        return done

    def wait(self, timeout: float = 30.0) -> bool:
        """等所有還在跑的呼叫結束、回覆送出（含背景工作做完的通知）。全部結束回 True。"""
        import time
        deadline = time.time() + timeout
        with self._lock:
            pending = list(self._pending)
        return all(e.wait(max(0.0, deadline - time.time())) for e in pending)


def install(app, cli: JsonCli, commands: Sequence[ServiceCommand], *, group: str = "svc",
            user_args: Optional[Callable[[object], List[str]]] = None, raw: bool = False,
            title: str = "🛠 服務", summary: str = "這支 bot 背後那個服務的指令") -> ServiceBridge:
    registry = app.registry
    bridge = ServiceBridge()
    ladder = sorted(set(registry.roles))
    default_role = ladder[1] if len(ladder) > 1 else ladder[0]
    registry.ensure_group(group, title, summary, role=default_role)
    g = registry.group(group)

    def say(api, chat_id: int, text: str) -> None:
        try:
            api.send_message(chat_id, text)
        except Exception:
            logging.exception("[SERVICE] reply to %s failed", chat_id)

    def respond(cmd: ServiceCommand, api, chat_id, user, values, reply: CliReply) -> None:
        if not reply.ok:
            say(api, chat_id, f"❌ {cmd.name}：{reply.error}")
            return
        ctx = ServiceContext(app, api, chat_id, user, values, reply)
        try:
            text = (cmd.render or default_render)(ctx)
        except Exception as e:
            logging.exception("[SERVICE] render %s failed", cmd.name)
            text = f"⚠️ 服務回了結果，但顯示的時候出錯：{e}"
        if text:
            say(api, chat_id, text)

    def make_submit(cmd: ServiceCommand):
        def submit(api, chat_id, user, values):
            if cmd.quota and app.limiter is not None and not app.limiter.try_consume(user.tg_id, user.role, cmd.quota):
                limit = app.limiter.limit(user.role, cmd.quota)
                api.send_message(chat_id, f"⚠️ 今天的 {cmd.name} 用完了（每天 {limit:g} 次），明天再來。")
                return
            argv = build_argv(cmd.argv, values) + (list(user_args(user)) if user_args else [])
            timeout = {"timeout": cmd.timeout} if cmd.timeout else {}
            done = bridge._started()

            def finish(reply: CliReply) -> None:
                try:
                    respond(cmd, api, chat_id, user, values, reply)
                finally:
                    done.set()

            if cmd.background:
                api.send_message(chat_id, f"⏳ {cmd.name} 開始了，做完通知你。")
                cli.start(*argv, on_done=finish, **timeout)        # 結束時在 JobRunner 的看守執行緒上 finish
                return
            typing = getattr(api, "typing", None)
            if callable(typing):
                typing(chat_id)
            # app.tasks：不卡收訊的執行緒，但終端機模式會等它回完才印下一個提示（host/app.py 的 TaskTracker）
            app.tasks.run(lambda: finish(cli.call(*argv, **timeout)), name=f"svc-{cmd.name}")
        return submit

    for cmd in commands:
        app.forms.leaf(g, cmd.name, make_submit(cmd), cmd.summary, fields=[_no_dash(f) for f in cmd.fields],
                       effect=cmd.effect, role=cmd.role, owner_only=cmd.owner_only, elevated=cmd.elevated,
                       default=cmd.default, **({"usage": cmd.usage} if cmd.usage else {}))

    if raw:
        def cmd_raw(api, chat_id, user, args):
            if not args:
                api.send_message(chat_id, f"用法：/{group}_raw <子指令> [參數…]")
                return

            done = bridge._started()

            def work():
                try:
                    reply = cli.call(*args)
                    body = json.dumps(reply.data, ensure_ascii=False, indent=1)
                    say(api, chat_id, f"{'✅' if reply.ok else '❌'} 結束碼 {reply.code}\n{body[:3500]}")
                finally:
                    done.set()

            app.tasks.run(work, name="svc-raw")

        g.leaf("raw", cmd_raw, "直接呼叫服務的任何子指令（除錯用）", usage="<子指令> [參數…]", effect=DANGER,
               owner_only=True, elevated=app.stepup is not None)
    return bridge
