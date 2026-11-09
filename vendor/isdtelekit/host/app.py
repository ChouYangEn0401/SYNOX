"""
build_app() 把 SDK 的每一層接好，回傳一個 App；App.run() 開始收 Telegram、App.run_console() 在終端機講話。

    config = BotConfig.load("config.json")
    app = build_app(config, roles=Role, quotas=QUOTAS)
    layout.define(app.registry)            # bot 自己的群組（樹的形狀）
    packs.basics.install(app)              # /start、/exit、舊訊息先問
    packs.help.install(app)                # /help、打群組名列出那組
    my_feature.install(app)                # bot 自己的指令
    app.run()                              # Ctrl+C 停

接好的東西（都是 App 的屬性，功能從這裡拿）：
  registry（指令樹＋authorize）、users（UserManager）、limiter（RateLimiter，可關）、conversations、forms、
  timing、stepup（/sudo；沒設定時 elevated 指令一律拒絕）、jobs（JobRunner）、dispatcher、telegram（TelegramEntry）、
  hub（受監看的 channel）、home（主動通知用的管子：有 token 就是 BotAPI，沒有就只記 log）。

主動通知（排程、背景工作做完、升級申請）走 app.home；回覆一律走 handler 拿到的那個 api（從哪來就回哪去）。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

from isdtelekit.core.conversation import ConversationManager
from isdtelekit.core.dispatcher import Dispatcher, DispatcherTexts
from isdtelekit.core.forms import Forms
from isdtelekit.core.registry import CommandRegistry
from isdtelekit.core.richtext import plain
from isdtelekit.core.timing import Timing
from isdtelekit.host.config import BotConfig
from isdtelekit.host.lock import claim_lock, release_lock
from isdtelekit.host.supervisor import ChannelHub
from isdtelekit.jobs.runner import JobRunner
from isdtelekit.limits.rate_limiter import RateLimiter
from isdtelekit.security.stepup import StepUp
from isdtelekit.telegram import menu as telegram_menu
from isdtelekit.telegram.bot_api import BotAPI
from isdtelekit.telegram.poller import Poller
from isdtelekit.telegram.updates import TelegramEntry
from isdtelekit.users.manager import UserManager
from isdtelekit.users.roles import BasicRoles

TELEGRAM = "telegram"


class LogOnlyChannel:
    """沒有 token（只在終端機試、或測試）時的 home：主動通知只記 log，不會丟例外。"""

    channel_name = "log"

    def send_message(self, chat_id, text, reply_markup=None, **kw):
        logging.info("[HOME → %s] %s", chat_id, plain(text))
        return {"ok": True, "result": {"message_id": 0}}

    def __getattr__(self, name):
        return lambda *a, **kw: {"ok": True}


def telegram_api(home) -> Optional[BotAPI]:
    """home 裡的 Telegram BotAPI：home 本身是 BotAPI，或是包了好幾個通道的 home（屬性 telegram_api）。都不是回 None。"""
    if isinstance(home, BotAPI):
        return home
    inner = getattr(home, "telegram_api", None)
    return inner if isinstance(inner, BotAPI) else None


class TaskTracker:
    """handler 丟到背景做、但「馬上就會回覆」的工作（例如呼叫服務的 CLI）：

        app.tasks.run(lambda: reply(cli.call("status")), name="svc-status")

    不卡住收訊的執行緒，同時讓在乎「做完了沒」的人等得到：終端機模式每打一句就等它們做完再印提示
    （不然下一句會搶在上一句的回覆之前），測試也可以 app.tasks.wait()。
    跑很久、做完才通知的（JsonCli.start 的背景工作）不要用這個——那些本來就不該讓人等。"""

    def __init__(self):
        self._pending: List[threading.Event] = []
        self._lock = threading.Lock()

    def run(self, fn: Callable[[], None], name: str = "task") -> threading.Thread:
        done = threading.Event()

        def wrapper():
            try:
                fn()
            except Exception:
                logging.exception("[TASK] %s failed", name)
            finally:
                done.set()

        with self._lock:
            self._pending = [e for e in self._pending if not e.is_set()] + [done]
        thread = threading.Thread(target=wrapper, daemon=True, name=f"Task-{name}")
        thread.start()
        return thread

    @property
    def pending(self) -> int:
        with self._lock:
            return sum(1 for e in self._pending if not e.is_set())

    def wait(self, timeout: float = 30.0) -> bool:
        """等現在還沒做完的那些（做的時候又開的新工作也算）。全部做完回 True。"""
        deadline = time.time() + timeout
        while True:
            with self._lock:
                pending = [e for e in self._pending if not e.is_set()]
            if not pending:
                return True
            if not pending[0].wait(max(0.0, deadline - time.time())):
                return False


@dataclass
class App:
    config: BotConfig
    registry: CommandRegistry
    users: UserManager
    limiter: Optional[RateLimiter]
    conversations: ConversationManager
    forms: Forms
    timing: Timing
    stepup: Optional[StepUp]
    jobs: JobRunner
    dispatcher: Dispatcher
    telegram: TelegramEntry
    hub: ChannelHub
    home: object                                  # 主動通知的管子（Channel）
    on_start: List[Callable[["App"], None]] = field(default_factory=list)   # run() 開始收訊之後呼叫
    on_stop: List[Callable[["App"], None]] = field(default_factory=list)
    extras: Dict[str, object] = field(default_factory=dict)   # packs 放自己的東西（例如 passes 的通行證存放處）
    tasks: TaskTracker = field(default_factory=TaskTracker)    # 丟到背景、馬上就會回覆的工作（見 TaskTracker）
    _stop: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def owner_id(self) -> int:
        return self.config.owner_id

    def notify_owner(self, text, markup: Optional[dict] = None) -> None:
        """送給機器擁有者（背景工作做完、有人申請…）。送不出去只記 log。"""
        self.notify(self.owner_id, text, markup)

    def notify(self, chat_id: int, text, markup: Optional[dict] = None) -> None:
        try:
            if markup is not None:
                self.home.send_message(chat_id, text, reply_markup=markup)
            else:
                self.home.send_message(chat_id, text)
        except Exception:
            logging.exception("[HOME] notify %s failed", chat_id)

    # ── 跑起來 ───────────────────────────────────────────────────────

    def run(self, channels: Sequence[str] = (TELEGRAM,)) -> None:
        """開始收訊，直到 Ctrl+C（或 stop()）。一個 data_dir 只能跑一支（host.lock）。"""
        lock = self.config.path("host.lock")
        other = claim_lock(lock)
        if other:
            raise SystemExit(f"已經有一支 bot 用這個資料夾在跑（pid {other}）；先把它關掉。")
        try:
            self.start(channels)
            try:
                while not self._stop.wait(1.0):
                    pass
            except KeyboardInterrupt:
                logging.info("[HOST] stopped by user.")
        finally:
            self.stop()
            release_lock(lock)

    def start(self, channels: Sequence[str] = (TELEGRAM,)) -> None:
        """開始收訊但不等（run() 用它；測試或要自己管主迴圈的程式也可以直接用）。"""
        if TELEGRAM in channels:
            api = telegram_api(self.home)
            if api is None:
                raise SystemExit("要收 Telegram 需要 config.json 的 bot_token。")
            self.hub.add(TELEGRAM, lambda: Poller(api, self.telegram, offset_path=self.config.path("last_update_id"),
                                                  poll_interval_seconds=self.config.poll_interval_seconds))
            self.hub.get(TELEGRAM).start()
            # 指令選單：網路呼叫，丟背景；有人的角色改變時只重設那個人的
            threading.Thread(target=self.sync_menus, daemon=True, name="MenuSync").start()
            self.users.on_role_change(lambda user: threading.Thread(
                target=telegram_menu.sync_user, args=(api, self.registry, user), daemon=True,
                name="MenuSync").start())
        for hook in list(self.on_start):
            try:
                hook(self)
            except Exception:
                logging.exception("[HOST] on_start hook failed")
        logging.info("[HOST] running with channels: %s", ", ".join(channels) or "（沒有）")

    def stop(self) -> None:
        self._stop.set()
        for hook in list(self.on_stop):
            try:
                hook(self)
            except Exception:
                logging.exception("[HOST] on_stop hook failed")
        self.hub.stop_all()

    def sync_menus(self) -> dict:
        """重設每個人的 Telegram 指令選單（有 token 時）。"""
        api = telegram_api(self.home)
        if api is None:
            return {"default": 0, "users": 0, "failed": 0}
        return telegram_menu.sync_menus(api, self.registry, self.users, self.owner_id)

    def run_console(self, user_id: Optional[int] = None) -> None:
        """在終端機直接跟 bot 講話（不用 Telegram、不用 token）。見 host/console.py。"""
        from isdtelekit.host.console import run_console
        run_console(self, user_id)


def build_app(config: BotConfig, *, roles=BasicRoles, quotas: Optional[dict] = None, use_limiter: bool = True,
              use_stepup: bool = True, texts: Optional[DispatcherTexts] = None, home=None) -> App:
    """組裝整支 bot（不連 Telegram、不啟動任何執行緒）；測試也用這個。

    roles：角色階梯（IntEnum）；quotas：每日配額表（limits/rate_limiter.py；None＝BasicRoles 的預設表，
    換了 roles 就要自己給）；use_limiter=False：完全不算配額；use_stepup=False：沒有 /sudo，elevated 指令一律拒絕；
    home：主動通知的管子（None＝有 token 就 BotAPI，沒有就只記 log；測試給 FakeChannel）。"""
    if quotas is None and roles is not BasicRoles and use_limiter:
        raise ValueError("換了角色階梯就要給 quotas（每個角色每天能傳幾則…），或 use_limiter=False。")
    timing = Timing.from_config(config.raw)
    users = UserManager(config.path("users.json"), roles=roles)
    users.bootstrap_admin(config.owner_id)
    limiter = RateLimiter(config.data_dir, quotas=quotas) if use_limiter else None
    stepup = StepUp(config.path("stepup_totp.json"), minutes=config.stepup_minutes) if use_stepup else None
    registry = CommandRegistry(owner_id=config.owner_id, stepup=stepup, roles=roles)
    conversations = ConversationManager(timing)
    forms = Forms(conversations, stepup)
    jobs = JobRunner(log_root=config.path("job_logs"))
    dispatcher = Dispatcher(registry, users, limiter, conversations, timing=timing, texts=texts)
    if home is None:
        home = BotAPI(config.bot_token) if config.has_token else LogOnlyChannel()
    return App(config=config, registry=registry, users=users, limiter=limiter, conversations=conversations,
               forms=forms, timing=timing, stepup=stepup, jobs=jobs, dispatcher=dispatcher,
               telegram=TelegramEntry(dispatcher), hub=ChannelHub(), home=home)
