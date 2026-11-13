"""
教學的步驟檔（`synox-steps` 第 1 版）：讀檔＋檢查。不合格＝**整個檔不載入**（log 一行原因），不會半套。

    {
      "schema": 1, "id": "basics", "title": "SYNOX 新手教學", "version": "1.0.0", "minutes": 5,
      "summary": "一句話說這份教學在教什麼",
      "steps": [
        {"id": "open-chat", "title": "這裡是「對話」",
         "body": "網頁上那張小卡的字（純文字）",
         "chat": "Telegram／Discord 用的字（沒寫就用 body）",
         "where": {"anchor": "nav.chat"},              # 或 ["settings.packs.review", "settings.packs.catalog"]（第一個看得到的）
         "go": {"view": "settings", "tab": "packs"},   # 卡片上的「帶我去」（只換頁，不按任何東西）
         "try": {"text": "/help"},                     # 卡片上的「幫我填好」（只填進輸入框，不送出）
         "done_when": {"event": "command", "value": "help"},
         "audience": "all"}                            # all｜owner（只給擁有者）｜member（不是擁有者的人）
      ]
    }

規則（docs/tutorials-engine.md）：位置只能寫 anchors.ANCHORS 的名字、事件只能是 anchors.EVENTS、go 只能是 GO_VIEWS；
字一律純文字（畫面用 textContent），不准連結、HTML、CSS 選擇器、程式。
語言：`"lang"`（沒寫＝zh-TW，代號同安裝精靈）。同一個 id 可以有好幾個語言的檔（basics.json、basics.en.json…），
引擎照 SYNOX 資料夾的 lang.txt 挑，沒有那個語言就退回 en、再退回 zh-TW（跟精靈的字串一樣，Engine.tours）。
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from synox.tour import anchors

SCHEMA = 1
ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
VERSION_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}$")
MAX_STEPS = 40
MAX_TITLE = 30
MAX_BODY = 200
MAX_CHAT = 300
MAX_TRY = 200
MAX_FILE = 64 * 1024
MAX_ANCHORS = 3
AUDIENCES = ("all", "owner", "member")
STEP_KEYS = {"id", "title", "body", "chat", "where", "go", "try", "done_when", "audience", "stage"}
TOUR_KEYS = {"schema", "id", "title", "version", "minutes", "summary", "steps", "requires", "lang"}
DEFAULT_LANG = "zh-TW"                     # 跟安裝精靈的語言代號一樣（synox/wizard/i18n.py 的 LANGS）
STAGES = ("in-app",)                       # 線上教學頁之後會多 before-install／wizard；app 裡只收 in-app
LINK_RE = re.compile(r"(https?://|www\.|<[a-z/!])", re.I)


class StepsError(ValueError):
    """步驟檔不合（訊息給寫教學的人看）。"""


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    body: str
    chat: str = ""
    anchors: Tuple[str, ...] = ()
    go: Optional[Dict[str, str]] = None
    try_text: str = ""
    done_event: str = ""
    done_value: str = ""
    audience: str = "all"

    def for_user(self, is_owner: bool) -> bool:
        return self.audience == "all" or (self.audience == "owner") == bool(is_owner)

    def to_web(self) -> dict:
        out = {"id": self.id, "title": self.title, "body": self.body, "anchors": list(self.anchors)}
        if self.go:
            out["go"] = dict(self.go)
        if self.try_text:
            out["try"] = self.try_text
        if self.done_event:
            out["done_when"] = {"event": self.done_event, "value": self.done_value}
        return out


@dataclass(frozen=True)
class Tour:
    id: str
    title: str
    version: str
    minutes: int
    summary: str
    steps: Tuple[Step, ...]
    source: str = ""                # ""＝SYNOX 內建；否則是附這份教學的工具（pack）名字
    path: str = field(default="", compare=False)
    lang: str = DEFAULT_LANG

    @property
    def major(self) -> int:
        return int(self.version.split(".")[0])

    def steps_for(self, is_owner: bool) -> List[Step]:
        return [s for s in self.steps if s.for_user(is_owner)]

    def step(self, step_id: str) -> Optional[Step]:
        return next((s for s in self.steps if s.id == step_id), None)


def _text(raw, where: str, limit: int, required: bool = True) -> str:
    if raw is None and not required:
        return ""
    if not isinstance(raw, str) or (required and not raw.strip()):
        raise StepsError(f"{where} 要是一段字")
    text = raw.strip()
    if len(text) > limit:
        raise StepsError(f"{where} 太長了（最多 {limit} 字，現在 {len(text)}）")
    if LINK_RE.search(text):
        raise StepsError(f"{where} 不能放連結或 HTML（教學的字一律純文字）")
    return text


def parse_step(raw, where: str) -> Step:
    if not isinstance(raw, dict):
        raise StepsError(f"{where} 要是一個 {{…}} 物件")
    extra = set(raw) - STEP_KEYS
    if extra:
        raise StepsError(f"{where} 不認得 {'、'.join(sorted(extra))}")
    sid = raw.get("id")
    if not isinstance(sid, str) or not ID_RE.match(sid):
        raise StepsError(f"{where}.id 只能用小寫英數與 -（{sid!r}）")
    where = f"{where}（{sid}）"
    stage = raw.get("stage", "in-app")
    if stage not in STAGES:
        raise StepsError(f"{where}.stage 只能是 {'／'.join(STAGES)}")
    names: List[str] = []
    w = raw.get("where")
    if w is not None:
        if not isinstance(w, dict) or set(w) - {"anchor"}:
            raise StepsError(f"{where}.where 只能寫 {{\"anchor\": 位置名}}")
        a = w.get("anchor")
        names = [a] if isinstance(a, str) else a if isinstance(a, list) else []
        if not names or len(names) > MAX_ANCHORS or not all(isinstance(n, str) for n in names):
            raise StepsError(f"{where}.where.anchor 要是一個位置名，或最多 {MAX_ANCHORS} 個的清單")
        bad = [n for n in names if not anchors.known(n)]
        if bad:
            raise StepsError(f"{where} 指到不認得的位置：{'、'.join(bad)}（只能用 synox/tour/anchors.py 的名字）")
    go = raw.get("go")
    if go is not None:
        if not isinstance(go, dict) or set(go) - {"view", "tab"} or go.get("view") not in anchors.GO_VIEWS:
            raise StepsError(f"{where}.go 只能寫 {{\"view\": {'｜'.join(anchors.GO_VIEWS)}, \"tab\": …}}")
        tab = go.get("tab")
        if tab is not None and tab not in anchors.GO_VIEWS[go["view"]]:
            raise StepsError(f"{where}.go.tab 不認得 {tab!r}")
        go = {k: str(v) for k, v in go.items()}
    try_text = ""
    t = raw.get("try")
    if t is not None:
        if not isinstance(t, dict) or set(t) != {"text"}:
            raise StepsError(f"{where}.try 只能寫 {{\"text\": 要填進輸入框的字}}")
        try_text = _text(t["text"], f"{where}.try.text", MAX_TRY)
    event = value = ""
    d = raw.get("done_when")
    if d is not None:
        if not isinstance(d, dict) or set(d) - {"event", "value"} or d.get("event") not in anchors.EVENTS:
            raise StepsError(f"{where}.done_when.event 只能是 {'、'.join(anchors.EVENTS)}")
        event = d["event"]
        value = d.get("value", "")
        if not isinstance(value, str) or len(value) > 40:
            raise StepsError(f"{where}.done_when.value 要是一小段字")
    audience = raw.get("audience", "all")
    if audience not in AUDIENCES:
        raise StepsError(f"{where}.audience 只能是 {'／'.join(AUDIENCES)}")
    return Step(id=sid, title=_text(raw.get("title"), f"{where}.title", MAX_TITLE),
                body=_text(raw.get("body"), f"{where}.body", MAX_BODY),
                chat=_text(raw.get("chat"), f"{where}.chat", MAX_CHAT, required=False),
                anchors=tuple(anchors.resolve(n) for n in names), go=go, try_text=try_text,
                done_event=event, done_value=value, audience=audience)


def parse(raw, source: str = "", path: str = "") -> Tour:
    if not isinstance(raw, dict):
        raise StepsError("步驟檔要是一個 {…} 物件")
    if raw.get("schema") != SCHEMA:
        raise StepsError(f"schema 要是 {SCHEMA}")
    extra = set(raw) - TOUR_KEYS
    if extra:
        raise StepsError(f"不認得 {'、'.join(sorted(extra))}")
    tid = raw.get("id")
    if not isinstance(tid, str) or not ID_RE.match(tid):
        raise StepsError(f"id 只能用小寫英數與 -（{tid!r}）")
    version = raw.get("version")
    if not isinstance(version, str) or not VERSION_RE.match(version):
        raise StepsError("version 要像 1.0.0")
    minutes = raw.get("minutes", 5)
    if not isinstance(minutes, int) or isinstance(minutes, bool) or not 1 <= minutes <= 60:
        raise StepsError("minutes 要是 1～60 的整數")
    steps_raw = raw.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise StepsError("steps 要是一個不是空的清單")
    if len(steps_raw) > MAX_STEPS:
        raise StepsError(f"一份教學最多 {MAX_STEPS} 步")
    lang = raw.get("lang", DEFAULT_LANG)
    from synox.wizard.i18n import LANGS
    if lang not in LANGS:
        raise StepsError(f"lang 只能是 {'、'.join(LANGS)}")
    steps = [parse_step(s, f"steps[{i}]") for i, s in enumerate(steps_raw)]
    ids = [s.id for s in steps]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise StepsError(f"步驟 id 重複：{'、'.join(dup)}")
    return Tour(id=tid, title=_text(raw.get("title"), "title", MAX_TITLE),
                version=version, minutes=minutes,
                summary=_text(raw.get("summary"), "summary", MAX_BODY, required=False),
                steps=tuple(steps), source=source, path=path, lang=lang)


def load_file(path: str, source: str = "") -> Tour:
    if os.path.getsize(path) > MAX_FILE:
        raise StepsError(f"檔案太大（最多 {MAX_FILE // 1024} KB）")
    with open(path, "r", encoding="utf-8") as f:
        try:
            raw = json.load(f)
        except ValueError as e:
            raise StepsError(f"不是正確的 JSON：{e}") from None
    return parse(raw, source=source, path=path)


def load_dir(folder: str, source: str = "", inside: str = "") -> List[Tour]:
    """一個資料夾裡的 *.json（照檔名排序）。壞的那個檔整個略過、log 一行；inside＝檔案的真實路徑必須在這個資料夾裡
    （pack 附的教學：不准用捷徑指到 pack 外面）。"""
    out: List[Tour] = []
    if not os.path.isdir(folder):
        return out
    root = os.path.realpath(inside or folder)
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not name.endswith(".json") or not os.path.isfile(path):
            continue
        if os.path.commonpath([os.path.realpath(path), root]) != root:
            logging.warning("[TOUR] %s: outside %s, skipped", path, root)
            continue
        try:
            out.append(load_file(path, source))
        except (StepsError, OSError) as e:
            logging.warning("[TOUR] %s: %s (not loaded)", path, e)
    return out
