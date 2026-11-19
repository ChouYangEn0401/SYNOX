"""
網頁的「🔄 重新啟動 SYNOX」（左下角的使用者選單、聊天通道的黃色提示）。只有擁有者。

    GET  /api/settings/restart      現況：能不能自己重開（看 SYNOX 是怎麼開的）、要不要重開（改了要重開才生效的設定）
    POST /api/settings/restart      {"confirm": true}：重新啟動（CSRF、Origin 在 server._route 驗過；手機驗證器照
                                    guard/stepup.py 的 /api/settings/ 規則）
    GET  /alive                     （不用登入）{"ok": true, "boot": "<這次開機的隨機代號>"}：網頁等 SYNOX 回來用的；
                                    代號換了＝已經是新開的那一支，網頁才重新整理

怎麼重開（跟 Update.bat、桌面捷徑同一套，不另外發明）：
- **launcher**：Windows、由 Start.bat 開的（桌面捷徑 → Open-SYNOX.bat → Start.bat、開機自動啟動 → Start.bat --no-browser；
  Start.bat 在跑 SYNOX 之前設 SYNOX_LAUNCHER=start.bat）。
  1. 先用 `cmd /c start "" /b python -m synox restart --after-pid <自己> ...` 開一支小幫手。經過 `start`，它的父行程是
     那個馬上結束的 cmd，不是 SYNOX：等一下萬一要 `taskkill /T` SYNOX 的整棵行程樹，不會連它一起砍掉
     （跟 update/web_api.launch 開 Update.bat 是同一招）。
  2. 回應送出去之後，SYNOX 自己正常結束（App 的 _stop：主迴圈跑 on_stop、放掉 host.lock、Start.bat 的視窗自己關）。
  3. 小幫手（__main__.cmd_restart）等舊的那支真的結束（最多 STOP_WAIT 秒；沒結束就用跟 `synox stop`／Stop.bat 一樣的
     taskkill），等網頁的埠放掉，確認沒有別的 SYNOX 拿著 host.lock，**才**用跟 Open-SYNOX.bat 一樣的方式開 Start.bat
     （不開瀏覽器：原本的網頁會自己接回來）。所以永遠不會同時有兩支。
- **docker**：容器裡。要不要重開、怎麼重開是 Docker 管的（restart 規則可能沒設），所以不自己重開，照實說用
  `docker compose restart synox`。
- **manual**：其他（終端機裡直接 `python -m synox run`、不是 Windows…）。自己結束之後沒有人會再把它開起來，
  所以不做，照實說：在那個視窗按 Ctrl+C 再開一次，或 Stop.bat → 桌面捷徑。

防止一直重開：一次只能有一個重開在進行；兩次之間至少 MIN_GAP 秒；一小時最多 MAX_PER_HOUR 次（記在 data/restart.json，
重開之後還記得）。每一次（成功、被擋）都寫一行安全紀錄（guard/audit.py，event＝restart）。
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import subprocess
import sys
import threading
import time
from typing import Callable, Dict, List, Optional

from synox import __version__

STATE_FILE = "restart.json"
MIN_GAP = 90                 # 秒：兩次重開之間至少隔這麼久（剛開好又被叫重開＝擋）
MAX_PER_HOUR = 5
STOP_DELAY = 0.8             # 秒：回應送出去之後才開始關
STOP_WAIT = 25               # 秒：小幫手等舊的那支自己結束；超過就 taskkill（跟 Stop.bat 一樣）
LAUNCHER_ENV = "SYNOX_LAUNCHER"

TEXT = {
    "how_launcher": "會先關掉 SYNOX，再用跟桌面捷徑一樣的方式自己開起來（大約 10～30 秒）。這段時間 bot 不會回訊息。",
    "how_docker": "SYNOX 在 Docker 容器裡跑，重開要由 Docker 來做：在電腦上執行 docker compose restart synox。",
    "how_manual": "這個 SYNOX 是直接在終端機（或不是用桌面捷徑）開的，沒辦法自己重開："
                  "在跑 SYNOX 的那個視窗按 Ctrl+C，再執行一次；或先雙擊 Stop.bat，再雙擊桌面的 SYNOX 捷徑。",
    "busy": "已經在重新啟動了，等它回來就好。",
    "too_soon": "剛剛才重新啟動過，為了避免一直重開，請 {s} 秒後再試。",
    "too_many": "這一個小時已經重新啟動 {n} 次了，先停一下（{m} 分鐘後才能再按）。一直出問題的話，到「遇到問題？」回報。",
    "confirm": "要重新啟動，請先確認。",
    "spawn_failed": "沒辦法開始重新啟動（{e}）。請手動：先雙擊 Stop.bat，再雙擊桌面的 SYNOX 捷徑。",
    "started": "重新啟動中：SYNOX 會先關掉再自己開起來，網頁好了會自動重新整理。",
    "reason_telegram": "Telegram 的設定改了",
    "reason_discord": "Discord 的設定改了",
}


def start_mode(environ=None, platform: Optional[str] = None) -> str:
    """launcher｜docker｜manual（說明見檔頭）。"""
    env = os.environ if environ is None else environ
    plat = os.name if platform is None else platform
    if env.get("SYNOX_IN_DOCKER") == "1" or env.get("SYNOX_IN_CONTAINER") == "1":
        return "docker"
    if plat == "nt" and str(env.get(LAUNCHER_ENV, "")).lower() == "start.bat":
        return "launcher"
    return "manual"


def helper_command(python: str, pid: int, created, config_path: str) -> List[str]:
    """小幫手的命令列：經過 cmd 的 start（/b：不另開視窗），父行程不是 SYNOX（見檔頭 1.）。"""
    cmd = [python, "-m", "synox"] + (["--config", config_path] if config_path else [])
    cmd += ["restart", "--after-pid", str(int(pid))]
    if created is not None:
        cmd += ["--created", str(created)]
    return ["cmd", "/c", "start", "", "/b"] + cmd


def _default_spawn(argv: List[str], cwd: str) -> None:
    subprocess.Popen(argv, cwd=cwd, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _process_created(pid: int):
    try:
        from isdtelekit.jobs.runner import process_created
        return process_created(pid)
    except Exception:
        return None


class Restarter:
    """重開這件事本身。測試把 spawn（開小幫手）、stop（讓 SYNOX 自己結束）換成假的，什麼都不會真的重開。"""

    def __init__(self, data_dir: str, root: str, *, config_path: str = "", stop: Optional[Callable[[], None]] = None,
                 spawn: Optional[Callable[[List[str], str], None]] = None, mode: Optional[str] = None,
                 clock: Callable[[], float] = time.time, python: str = sys.executable, pid: Optional[int] = None,
                 delay: float = STOP_DELAY, timer=threading.Timer):
        self.path = os.path.join(data_dir, STATE_FILE)
        self.root = root
        self.config_path = config_path
        self.stop = stop
        self.spawn = spawn or _default_spawn
        self.mode = mode or start_mode()
        self.clock = clock
        self.python = python
        self.pid = int(pid if pid is not None else os.getpid())
        self.delay = delay
        self.timer = timer
        self.busy = False
        self._mu = threading.Lock()

    # ── 記錄（data/restart.json）──────────────────────────────────────
    def _times(self) -> List[float]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [float(t) for t in (data.get("times") or []) if isinstance(t, (int, float))]
        except (OSError, ValueError, AttributeError, TypeError):
            return []

    def _save(self, times: List[float]) -> None:
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"times": times[-MAX_PER_HOUR * 2:]}, f)
            os.replace(tmp, self.path)
        except OSError:
            logging.warning("[WEB] cannot save %s", STATE_FILE, exc_info=True)

    def wait_seconds(self) -> int:
        """還要等幾秒才能再重開（0＝現在可以）。"""
        now = self.clock()
        times = [t for t in self._times() if now - t < 3600]
        wait = 0.0
        if times:
            wait = max(wait, MIN_GAP - (now - max(times)))
        if len(times) >= MAX_PER_HOUR:
            wait = max(wait, 3600 - (now - sorted(times)[-MAX_PER_HOUR]))
        return int(max(0.0, wait) + 0.999)

    # ── 狀態 ─────────────────────────────────────────────────────────
    def status(self, reasons: List[str]) -> dict:
        can = self.mode == "launcher"
        return {"mode": self.mode, "can": can, "how": TEXT["how_" + self.mode], "busy": self.busy,
                "pending": bool(reasons), "reasons": list(reasons), "wait_s": self.wait_seconds() if can else 0}

    # ── 重開 ─────────────────────────────────────────────────────────
    def request(self) -> tuple:
        """回 (HTTP 狀態碼, 內容, 安全紀錄的原因代碼)。"""
        with self._mu:
            if self.mode != "launcher":
                return 409, {"error": TEXT["how_" + self.mode], "mode": self.mode, "can": False}, "unsupported"
            if self.busy:
                return 409, {"error": TEXT["busy"], "busy": True}, "busy"
            now = self.clock()
            times = [t for t in self._times() if now - t < 3600]
            if times and now - max(times) < MIN_GAP:
                return 429, {"error": TEXT["too_soon"].format(s=self.wait_seconds()),
                             "wait_s": self.wait_seconds()}, "too_soon"
            if len(times) >= MAX_PER_HOUR:
                wait = self.wait_seconds()
                return 429, {"error": TEXT["too_many"].format(n=len(times), m=max(1, (wait + 59) // 60)),
                             "wait_s": wait}, "too_many"
            argv = helper_command(self.python, self.pid, _process_created(self.pid), self.config_path)
            try:
                self.spawn(argv, self.root)
            except OSError as e:
                return 500, {"error": TEXT["spawn_failed"].format(e=type(e).__name__)}, "spawn_failed"
            self.busy = True
            self._save(times + [now])
        if self.stop is not None:
            t = self.timer(self.delay, self.stop)          # 先讓回應送出去，再自己結束
            t.daemon = True
            t.start()
        return 202, {"ok": True, "message": TEXT["started"]}, "ok"


# ── 接到網頁（server.py 的 WebUI 叫這些）────────────────────────────────

def new_boot_id() -> str:
    return secrets.token_hex(8)


def app_stopper(app) -> Callable[[], None]:
    """讓 SYNOX 正常結束：叫醒 App.run 的主迴圈（它自己在主執行緒跑 stop()、放掉 host.lock）。
    沒有那個旗子（舊版的 App、測試的假 App）才直接 stop()。"""
    def stop():
        flag = getattr(app, "_stop", None)
        if flag is not None and hasattr(flag, "set"):
            logging.info("[WEB] restart requested: stopping SYNOX (the restart helper starts it again)")
            flag.set()
        else:
            app.stop()
    return stop


def reasons_of(web) -> List[str]:
    """要重開才生效的事（白話）：目前是聊天通道的設定。"""
    out = []
    for name in sorted(getattr(web, "_channels_changed", ()) or ()):
        out.append(TEXT.get("reason_" + name, name))
    return out


def _json(code: int, data) -> tuple:
    from synox.web.server import _json as server_json      # 同一套安全標頭（server 會 import 這個檔，所以在這裡才 import）
    return server_json(code, data)


def alive(web) -> tuple:
    return _json(200, {"ok": True, "boot": web.boot_id})


def route(web, user, method: str, path: str, body: bytes) -> tuple:
    denied = web._owner_only(user)
    if denied:
        return denied
    r = web.restarter
    if method == "GET":
        return _json(200, {**r.status(reasons_of(web)), "boot": web.boot_id, "version": __version__})
    if method != "POST":
        return _json(405, {"error": "只收 GET、POST。"})
    try:
        data = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (ValueError, UnicodeDecodeError):
        return _json(400, {"error": "送來的不是 JSON。"})
    audit = _audit(web)
    if not isinstance(data, dict) or data.get("confirm") is not True:
        return _json(400, {"error": TEXT["confirm"]})
    code, out, why = r.request()
    if audit is not None:
        audit.write("restart", by=user.tg_id, origin="web", target=r.mode, ok=code == 202, code=why)
    logging.info("[WEB] %s asked to restart SYNOX (%s): %s", user.tg_id, r.mode, why)
    if code == 202:
        out = {**out, "boot": web.boot_id}
    return _json(code, out)


def _audit(web):
    try:
        from synox import guard
        g = guard.of(web.app)
        return g.audit if g is not None else None
    except Exception:
        return None


def status_for_me(web, user) -> Optional[Dict[str, object]]:
    """/api/me 帶的那一小段（只有擁有者）：選單上的小點要不要亮、能不能按。"""
    if not web.is_owner(user):
        return None
    r = web.restarter
    reasons = reasons_of(web)
    return {"can": r.mode == "launcher", "pending": bool(reasons), "reasons": reasons, "mode": r.mode}
