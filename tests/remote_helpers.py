"""手機入口測試共用的準備（不開埠、不開子程序）：counter 宣告了 remote、驗證器設定好（假時鐘）、總開關與「可以從手機用」都打開、
假 listener、假通道、通道程式當作已核准。"""

from synox import guard
from synox.guard.origin import Origin
from synox.guard.testing import Clock, code_for, enroll
from synox.web import remote
from synox.web.apps.testing import FakeListen
from synox.web.remote.testing import FakeTunnel, RemoteClient


class Phone:
    def __init__(self, bot, owner, clock, secret, tunnel, listen):
        self.bot, self.owner, self.clock, self.secret = bot, owner, clock, secret
        self.tunnel, self.listen = tunnel, listen
        self.manager = remote.of(bot.app)
        self.apps = self.manager.apps
        self.tg = Origin("telegram", owner, surface="telegram")

    def code(self, step: bool = True) -> str:
        if step:
            self.clock.t += 30
        return code_for(self.secret, self.clock)

    def open(self, name="counter", **kw):
        user = self.bot.app.users.get_or_create(self.owner)
        return self.manager.open(name, user, self.code(), origin=kw.pop("origin", self.tg), **kw)

    def client(self, ua="PhoneBrowser/1.0"):
        return RemoteClient(self.manager, user_agent=ua)


def make_phone(counter, owner, *, tunnel=None, raw=None, allow=True, enrolled=True):
    cfg = {"web": {"remote": {"enabled": True}}}
    if raw:
        cfg["web"].update(raw.get("web", {}))
        cfg.update({k: v for k, v in raw.items() if k != "web"})
    bot, apps = counter(raw=cfg)
    clock = Clock()
    g = guard.of(bot.app)
    secret = enroll(g, owner, clock) if enrolled else None
    if not enrolled:
        from synox.guard.testing import use_clock
        use_clock(g, clock)
    apps.clock = clock
    apps.audit.clock = clock
    apps.tickets.clock = clock
    manager = remote.of(bot.app)
    manager.clock = clock
    manager.enter_attempts.clock = clock
    manager.rate_in.clock = manager.rate_out.clock = clock
    listen = FakeListen()
    manager.listen = listen
    apps.listen = FakeListen()
    tunnel = tunnel or FakeTunnel()
    manager.tunnel_factory = tunnel
    manager.binary_check = lambda: ""
    if allow:
        data = manager.data()
        data["tools"]["counter"] = True
        manager._save(data)
    return Phone(bot, owner, clock, secret, tunnel, listen)
