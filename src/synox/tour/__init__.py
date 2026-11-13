"""
新手教學（tutorial）的引擎：在 SYNOX 核心，每一份安裝都有（ZIP、安裝程式、git、Docker 都一樣，因為它就是 src/synox 的一部分）。

    tour.install(app, config, vault)          # app.build 裡呼叫：/tutorial 指令、/help 那一行、「開始教學」這幾句話
    eng = tour.engine(app)
    eng.tours()                               # [Tour, …]：內建的（tour/tours/*.json）＋已載入的工具附的（<pack>/tours/*.json）
    eng.start(user, "basics")                 # → (Tour, 第幾步)：開始或接著上次
    eng.save(user, "basics", step="open-chat", state="paused")

分工（docs/tutorials-engine.md）：
- 引擎（這裡）：步驟檔的格式與檢查（schema.py）、畫面位置清單（anchors.py）、每人的進度、/tutorial（chat.py）、
  網頁的 /api/tour（web/server.py）。網頁上的聚光圈與小卡是 static/tour.js：**SYNOX 自己畫**，步驟檔只給字與位置名字。
- 內容：純資料的步驟檔。內建的那份在 synox/tour/tours/（跟著 SYNOX 同一版、出廠就有、刪不掉；**不是工具**，
  不算進「裝了幾個工具」，也不經 pack 的安裝流程）。工具（pack）也可以在自己的資料夾附 tours/*.json，載入了就會出現在 /tutorial list。
- 安全：教學不替使用者按任何東西、不送出、不呼叫會改東西的 API（只存自己的進度）；字一律純文字；教學的字不進 AI 的提示。

進度（每人一份，data/tour/<tg_id>.json(.enc)，有保管箱就加密）：
    {"tours": {"basics": {"version": "1.0.0", "step": "open-chat", "done": [...], "state": "active|paused|finished",
                          "updated": 1700000000, "finished": 1}},
     "offer": "later"}                        # 第一次打開網頁的「要不要我帶你走一遍？」按過「之後再說」
記的是步驟 id，不是第幾步：內容更新後做過的還是做過；version 的第一個數字變了才從頭來。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Dict, List, Optional, Tuple

from synox.tour import schema
from synox.tour.schema import Step, Tour

BUILTIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tours")
DEFAULT = "basics"
STATES = ("active", "paused", "finished")
MAX_DONE = 100
EXTRA_KEY = "synox_tour"


class Engine:

    def __init__(self, app, prefs, builtin_dir: str = BUILTIN_DIR, clock=time.time):
        self.app = app
        self.prefs = prefs
        self.builtin_dir = builtin_dir
        self._clock = clock
        self._cache: Dict[str, tuple] = {}
        self._lock = threading.Lock()

    # ── 內容 ─────────────────────────────────────────────────────────

    def _load(self, folder: str, source: str, inside: str = "") -> List[Tour]:
        """同一個資料夾、檔案沒變就不重讀（/tutorial、/api/tour 每次都會問）。"""
        try:
            names = sorted(n for n in os.listdir(folder) if n.endswith(".json"))
            stamp = tuple((n, os.path.getmtime(os.path.join(folder, n))) for n in names)
        except OSError:
            return []
        key = f"{source}|{folder}"
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] == stamp:
                return hit[1]
        tours = schema.load_dir(folder, source=source, inside=inside)
        with self._lock:
            self._cache[key] = (stamp, tours)
        return tours

    def lang(self) -> str:
        """SYNOX 資料夾的 lang.txt（安裝精靈選的語言）；沒有＝zh-TW。"""
        from synox.wizard import i18n
        root = getattr(self.app.extras.get("synox_config"), "root", "") or ""
        return (i18n.read_lang(i18n.lang_path(root)) if root else None) or schema.DEFAULT_LANG

    def tours(self) -> List[Tour]:
        """內建的在前（DEFAULT 第一個）；工具附的照工具名排。id 重複＝先來的贏（內建的永遠贏）。
        同一個來源、同一個 id 有好幾個語言：照 lang.txt 挑，沒有就退回 en、再退回 zh-TW（同安裝精靈的字串）。"""
        want = [self.lang(), "en", schema.DEFAULT_LANG]
        groups: List[List[Tour]] = []
        builtin = self._load(self.builtin_dir, "")
        builtin.sort(key=lambda t: (t.id != DEFAULT, t.id))
        groups.append(builtin)
        for pack in sorted(self.app.extras.get("synox_packs", []) or [], key=lambda p: p.manifest.name):
            folder = os.path.join(pack.manifest.folder, "tours")
            if os.path.isdir(folder):
                groups.append(self._load(folder, pack.manifest.name, inside=pack.manifest.folder))
        out: List[Tour] = []
        seen = set()
        for group in groups:
            for tid in dict.fromkeys(t.id for t in group):
                if tid in seen:
                    logging.warning("[TOUR] %s: id %s already used, skipped", group[0].source or "SYNOX", tid)
                    continue
                same = [t for t in group if t.id == tid]
                rank = lambda t: want.index(t.lang) if t.lang in want else len(want)   # noqa: E731
                out.append(min(same, key=rank))
                seen.add(tid)
        return out

    def get(self, tour_id: str) -> Optional[Tour]:
        return next((t for t in self.tours() if t.id == tour_id), None)

    def default(self) -> Optional[Tour]:
        return self.get(DEFAULT) or next(iter(self.tours()), None)

    def is_owner(self, user) -> bool:
        return bool(self.app.registry.is_owner(user))

    def steps(self, user, tour: Tour) -> List[Step]:
        return tour.steps_for(self.is_owner(user))

    # ── 進度 ─────────────────────────────────────────────────────────

    def progress(self, user) -> Dict[str, dict]:
        data = self.prefs.get(user.tg_id, "tours", {}) or {}
        return data if isinstance(data, dict) else {}

    def record(self, user, tour: Tour) -> dict:
        """這個人在這份教學的紀錄；版本的第一個數字變了＝當作沒走過。"""
        rec = self.progress(user).get(tour.id)
        if not isinstance(rec, dict):
            return {}
        try:
            major = int(str(rec.get("version", "0")).split(".")[0])
        except ValueError:
            major = -1
        return rec if major == tour.major else {}

    def position(self, user, tour: Tour, rec: Optional[dict] = None) -> int:
        """接著走要從第幾步（這個人看得到的步驟裡的索引）。走完了＝從頭（複習）。"""
        rec = self.record(user, tour) if rec is None else rec
        steps = self.steps(user, tour)
        if not rec or rec.get("state") == "finished":
            return 0
        ids = [s.id for s in steps]
        if rec.get("step") in ids:
            return ids.index(rec["step"])
        done = set(rec.get("done") or [])
        return next((i for i, s in enumerate(steps) if s.id not in done), 0)

    def save(self, user, tour_id: str, *, step: str = "", state: str = "", done: Optional[List[str]] = None) -> dict:
        tour = self.get(tour_id)
        if tour is None:
            raise KeyError(tour_id)
        ids = [s.id for s in tour.steps]
        rec = dict(self.record(user, tour))
        rec["version"] = tour.version
        if step:
            if step not in ids:
                raise ValueError(step)
            rec["step"] = step
        if done is not None:
            merged = list(dict.fromkeys(list(rec.get("done") or []) + [d for d in done if d in ids]))
            rec["done"] = merged[:MAX_DONE]
        if state:
            if state not in STATES:
                raise ValueError(state)
            if state == "finished" and rec.get("state") != "finished":
                rec["finished"] = int(rec.get("finished") or 0) + 1
            rec["state"] = state
        rec["updated"] = int(self._clock())
        all_tours = dict(self.progress(user))
        all_tours[tour.id] = rec
        self.prefs.set(user.tg_id, "tours", all_tours)
        return rec

    def start(self, user, tour_id: str = "", restart: bool = False) -> Tuple[Optional[Tour], int]:
        """開始（或接著上次）。restart＝從第一步、做過的清掉（複習用）。"""
        tour = self.get(tour_id) if tour_id else self.default()
        if tour is None or not self.steps(user, tour):
            return None, 0
        steps = self.steps(user, tour)
        if restart:
            all_tours = dict(self.progress(user))
            old = all_tours.get(tour.id) if isinstance(all_tours.get(tour.id), dict) else {}
            all_tours[tour.id] = {"version": tour.version, "finished": int(old.get("finished") or 0)}
            self.prefs.set(user.tg_id, "tours", all_tours)
            at = 0
        else:
            at = self.position(user, tour)
        self.save(user, tour.id, step=steps[at].id, state="active")
        return tour, at

    def finished(self, user, tour: Tour) -> int:
        return int(self.record(user, tour).get("finished") or 0)

    # ── 第一次打開網頁的邀請 ──────────────────────────────────────────

    def should_offer(self, user) -> bool:
        """還沒走過任何教學、也沒按過「之後再說」＝要問一次。"""
        if self.default() is None:
            return False
        if self.prefs.get(user.tg_id, "offer"):
            return False
        return not self.progress(user)

    def answer_offer(self, user, answer: str) -> None:
        self.prefs.set(user.tg_id, "offer", "later" if answer == "later" else "started")


def engine(app) -> Optional[Engine]:
    return app.extras.get(EXTRA_KEY)


def install(app, config, vault=None) -> Engine:
    from synox.tour import chat
    from synox.web.toolpage import UserPrefs
    prefs = UserPrefs(os.path.join(config.data_dir, "tour"), vault)
    eng = Engine(app, prefs)
    app.extras[EXTRA_KEY] = eng
    chat.install(app, eng)
    return eng
