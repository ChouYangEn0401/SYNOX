"""
soul 帳本（docs/adr/0005）：soul.md「助理筆記」段每一條的來歷、等你確認的提議、收起來的舊筆記、整理與遺忘。

soul.md 的字仍然只在 SoulStore（你直接改的那一份才是正本）；這裡只記「關於那些行的事」，存同一個保管箱
（`runtime_soul_ledger`，加密）。帳本壞了或不見＝筆記照舊在，只是沒有來歷。

    ledger = SoulLedger(soul, vault, review=False, mother=mother, clock=time.time)
    out = ledger.propose(["他晚上不看工作訊息"], by="mother", source="heartbeat", evidence=[擁有者最近說的話])
    out.added / out.waiting / out.confirmed / out.dropped
    ledger.view()                      主控面板看的：筆記（誰、什麼時候、多久沒確認）、提議、收起來的、用量
    ledger.approve(pid, replace=False) / ledger.reject(pid)
    ledger.retire(note_id) / ledger.restore(archive_id) / ledger.confirm(note_id)
    ledger.tidy()                      整理一次（不叫 AI）：重複的拿掉、很像的與很久沒確認的變成提議、過期的提議丟掉
    ledger.forget("某段字", confirm=True)   筆記、提議、收起來的、稽核、常駐助理的記憶裡提到的全部拿掉
    ledger.export()                    全部倒成一個 dict（給你下載）
    ledger.weigher()                   給 SoulStore.for_prompt 的 weight（超過上限要挑筆記時，新的優先）

寫入的規則（結構上擋，不靠提示）：
- 助理提的每一條先過 `risk_flags`（像在對 AI 下指令、有網址、要跳過確認、要把資料傳出去…）；有疑慮的**不直接寫**，
  變成提議等你按。跟現有某一條很像（可能是更新、也可能相反）的也一樣：你決定取代舊的、兩條都留、還是不要。
- `review=True`（config `runtime.mother.soul_review`）＝每一條都先等你按。預設 False＝沒疑慮的直接加（原本的行為）。
- 一天最多自動加 AUTO_PER_DAY 條、筆記段最多 NOTES_MAX_LINES 條，超過的變成提議；提議最多 PENDING_MAX 則、
  PENDING_TTL_DAYS 天沒處理就丟掉。像密鑰的片段連提議都不留。
- 你拒絕過、收起來過、要它忘掉的那一條，助理再提一次直接丟（只記雜湊，不記字）。
- 取代與收起＝搬到「收起來的」（可以放回去），不是刪掉；真的要刪用 forget。
- 助理碰不到你自己寫的段落（只有 SoulStore.append_notes／filter_notes 兩條路，都只動「助理筆記」段）。
"""

from __future__ import annotations

import difflib
import hashlib
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from synox.agent import delimit
from synox.runtime import soul as soul_mod
from synox.runtime.soul import SoulError

KEY = "runtime_soul_ledger"
TASK_ID = "system.soul_tidy"
TASK_NAME = "整理助理筆記（soul.md）"
TIDY_INTERVAL = 6 * 3600.0
TIDY_FIRST_DELAY = 300.0
TIDY_TIMEOUT = 60.0

NOTES_MAX_LINES = 40               # 「助理筆記」段最多幾條（超過的變成提議）
AUTO_PER_DAY = 6                   # 一天最多自動加幾條
PENDING_MAX = 20
PENDING_TTL_DAYS = 30
ARCHIVE_MAX = 200
ARCHIVE_VIEW = 50
SUPPRESS_MAX = 500
STALE_DAYS = 90                    # 助理自己加的筆記這麼久沒再被確認 → 提議收起來
HALF_LIFE_DAYS = 30                # 挑筆記進系統提示時的新舊：每過這麼多天權重減半
RELATED_MIN = 0.6                  # 跟現有某一條這麼像 → 可能是更新或相反，先問你
NEAR_DUP = 0.85                    # 整理時：兩條筆記這麼像 → 提議收起舊的
EVIDENCE_MIN = 0.25                # 這一條有這麼多比例的片段出現在你最近說的話裡＝算有根據
FORGET_MIN = 2                     # forget 的字至少幾個字（一個字會掃到太多）
REASON_MAX = 200

WHY_REVIEW = "你設定了每一條都先問你"
WHY_RELATED = "跟現有的一條很像，可能是更新"
WHY_OPPOSITE = "跟現有的一條只差在否定字，可能相反"
WHY_FULL = f"助理筆記已經有 {NOTES_MAX_LINES} 條，先收起幾條舊的"
WHY_DAILY = f"今天已經自動加了 {AUTO_PER_DAY} 條"
WHY_NO_ROOM = "soul.md 快到字數上限"

# 寫進每一輪系統提示的東西要比一般資料嚴：下面任何一條中了就不自動寫，變成提議等人看。
# 這是「擋住自動寫入」，不是「判定是攻擊」——正常的偏好偶爾也會中，按一下就加進去了。
def _en(words: str) -> str:
    """英文的字要整個字才算（\b 把中文字也當成字的一部分，「的token」會漏掉，所以自己寫：前後不能是英數）。"""
    return r"(?<![a-z0-9])(?:" + words + r")(?![a-z0-9])"


RISK_RULES: Tuple[Tuple[str, "re.Pattern"], ...] = (
    ("有網址或網域", re.compile(
        r"https?://|www\.|(?<![a-z0-9])[a-z0-9-]+\.(?:com|net|org|io|ai|tw|cn|ru|xyz|top|info|dev|app|co|me|ly|sh)(?![a-z0-9])",
        re.I)),
    ("有電子郵件", re.compile(r"[a-z0-9.+_-]+@[a-z0-9-]+\.[a-z0-9.-]+", re.I)),
    ("像在對 AI 下指令（忽略／改掉規則）", re.compile(
        r"忽略|無視|不理會|不要理|覆蓋|取代上面|系統提示|開發者模式|你現在是|你的新(?:身分|角色|規則)|"
        + _en(r"ignore|disregard|override|forget (?:all|previous|everything)|system prompt|developer mode|"
              r"jailbreak|you are now|act as|new instructions?"), re.I)),
    ("要跳過確認或核准", re.compile(
        r"不用(?:再)?(?:問|確認|核准)|不需要(?:再)?(?:問|確認|核准)|免確認|自動核准|直接(?:執行|核准|刪)|"
        + _en(r"without (?:asking|confirmation|approval)|auto[- ]?approve|skip (?:the )?confirm\w*"), re.I)),
    ("提到執行指令或工具", re.compile(
        r"執行|呼叫工具|跑指令|下指令|cmd\.exe|(?<![a-z0-9/:.])/[a-z][a-z0-9_]{2,}|"
        + _en(r"run|exec|shell|powershell|curl|wget|rm -\w+"), re.I)),
    ("要把資料傳出去", re.compile(
        r"傳送到|傳到|寄到|寄給|上傳|轉寄|貼到|" + _en(r"send (?:it |them |this |that )?to|upload|forward|exfiltrate"), re.I)),
    ("要它把某個來源當成可信", re.compile(
        r"可信(?:的|任)?來源|信任(?:的)?來源|官方來源|優先(?:引用|推薦|參考)|"
        + _en(r"trusted source|authoritative|always (?:recommend|cite)"), re.I)),
    ("提到密碼或金鑰", re.compile(r"密碼|金鑰|密鑰|" + _en(r"password|passwd|api[ _-]?key|token|secret"), re.I)),
    ("「記住／從現在起」這種句型", re.compile(
        r"請記住|記住[:：]|記得[:：]|從現在(?:起|開始)|從今以後|"
        + _en(r"from now on|remember (?:that|to)|always remember"), re.I)),
    ("有一長串數字（像電話或證號）", re.compile(r"\d{8,}")),
    ("夾了標記或分隔符", re.compile(r"[⟦⟧]|<\|?/?[a-z_]+\|?>|```|\[/?(?:system|inst)\]", re.I)),
)
_NEGATIONS = set("不沒没別别非無无未勿免")
_NEG_WORDS = {"not", "no", "never", "dont", "don't", "doesnt", "doesn't", "n't"}
_PUNCT = re.compile(r"[\s\-_.,;:!?、，。；：！？「」『』（）()\[\]\"'`~]+")


class LedgerError(Exception):
    """一句給人看的話。"""


@dataclass
class Outcome:
    added: List[str] = field(default_factory=list)       # 直接寫進 soul.md 的
    waiting: List[str] = field(default_factory=list)     # 變成提議、等你確認的
    confirmed: List[str] = field(default_factory=list)   # 本來就有：只更新「上次確認」
    dropped: int = 0                                     # 丟掉的（空的、太長、像密鑰、你拒絕過、提議滿了）


# ── 純函式 ───────────────────────────────────────────────────────────

def fold(line: str) -> str:
    """比對用：拿掉開頭的 -、空白與標點、轉小寫。"""
    return _PUNCT.sub("", soul_mod.clean_note(line).lower())


def note_id(line: str) -> str:
    """一條筆記的代號＝內容的雜湊（你改了字＝另一條、原本的來歷不跟過去）。"""
    return hashlib.sha256(fold(line).encode("utf-8")).hexdigest()[:12]


def risk_flags(text: str) -> List[str]:
    """這一條有哪些不該自動寫進系統提示的樣子（給人看的理由；空的＝沒有）。"""
    flags = [why for why, pattern in RISK_RULES if pattern.search(text or "")]
    if delimit.looks_forged(text or "") and "夾了標記或分隔符" not in flags:
        flags.append("夾了標記或分隔符")
    return flags


def similarity(a: str, b: str) -> float:
    fa, fb = fold(a), fold(b)
    if not fa or not fb:
        return 0.0
    return difflib.SequenceMatcher(None, fa, fb, autojunk=False).ratio()


def only_negation_differs(a: str, b: str) -> bool:
    """兩條只差在否定字（不、沒、別、not…）：很可能是相反的意思。"""
    fa, fb = fold(a), fold(b)
    diff = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, fa, fb, autojunk=False).get_opcodes():
        if op != "equal":
            diff += [fa[i1:i2], fb[j1:j2]]
    parts = [d for d in diff if d]
    return bool(parts) and all(set(d) <= _NEGATIONS or d in _NEG_WORDS for d in parts)


def most_related(line: str, others: Iterable[str]) -> Tuple[str, float]:
    best, score = "", 0.0
    for other in others:
        s = similarity(line, other)
        if s > score:
            best, score = other, s
    return (best, score) if score >= RELATED_MIN else ("", score)


def grounded(line: str, evidence: Optional[List[str]]) -> Optional[bool]:
    """這一條看不看得出是從擁有者自己說的話來的。evidence=None（沒給、或設定不讓看對話）＝不知道。"""
    if evidence is None:
        return None
    return soul_mod.relevance("\n".join(str(e) for e in evidence), line) >= EVIDENCE_MIN


def _dicts(value) -> List[dict]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _num(value) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


# ── 帳本 ─────────────────────────────────────────────────────────────

class SoulLedger:

    def __init__(self, soul, vault=None, *, review: bool = False, mother=None,
                 clock: Callable[[], float] = time.time):
        self.soul = soul
        self._vault = vault
        self.review = bool(review)
        self.mother = mother
        self._clock = clock
        self._lock = threading.RLock()

    @property
    def available(self) -> bool:
        return self._vault is not None

    # ── 存取 ─────────────────────────────────────────────────────────

    def _need(self):
        if self._vault is None:
            raise LedgerError("保管箱沒有打開，助理筆記的紀錄讀寫不了（python -m synox doctor 看原因）。")
        return self._vault

    def _state(self) -> dict:
        data = self._vault.load_json(KEY, None) if self._vault is not None else None
        d = data if isinstance(data, dict) else {}
        notes = d.get("notes") if isinstance(d.get("notes"), dict) else {}
        return {"v": 1,
                "notes": {k: v for k, v in notes.items() if isinstance(k, str) and isinstance(v, dict)},
                "pending": [p for p in _dicts(d.get("pending"))
                            if isinstance(p.get("id"), str) and isinstance(p.get("text"), str)
                            and p.get("kind") in ("add", "retire")],
                "archive": [a for a in _dicts(d.get("archive"))
                            if isinstance(a.get("id"), str) and isinstance(a.get("text"), str)],
                "suppress": [s for s in d.get("suppress", []) if isinstance(s, str)]
                if isinstance(d.get("suppress"), list) else [],
                "day": d.get("day") if isinstance(d.get("day"), str) else "",
                "auto_today": d.get("auto_today") if isinstance(d.get("auto_today"), int) else 0,
                "told_day": d.get("told_day") if isinstance(d.get("told_day"), str) else ""}

    def _save(self, state: dict) -> None:
        state["archive"] = state["archive"][-ARCHIVE_MAX:]
        state["suppress"] = state["suppress"][-SUPPRESS_MAX:]
        self._need().save_json(KEY, state)

    def _today(self) -> str:
        return datetime.fromtimestamp(self._clock()).strftime("%Y-%m-%d")

    @staticmethod
    def _suppress(state: dict, key: str) -> None:
        if key not in state["suppress"]:
            state["suppress"].append(key)

    @staticmethod
    def _find(items: List[dict], item_id: str, missing: str) -> dict:
        for item in items:
            if item["id"] == item_id:
                return item
        raise LedgerError(missing)

    def _meta(self, by: str, source: str, now: float, evidence_ok: Optional[bool] = None, **extra) -> dict:
        meta = {"added_at": now, "by": by, "source": source, "confirmed_at": now, "confirmations": 0}
        if evidence_ok is not None:
            meta["grounded"] = bool(evidence_ok)
        meta.update(extra)
        return meta

    # ── 助理提議 ─────────────────────────────────────────────────────

    def propose(self, lines: List[str], *, by: str = "mother", source: str = "heartbeat",
                evidence: Optional[List[str]] = None) -> Outcome:
        """助理想記的幾行（一次最多 soul.APPEND_MAX_LINES 行）。規則見模組說明。保管箱沒開丟 SoulError。"""
        out = Outcome()
        with self._lock:
            state = self._state()
            text = self.soul.text()
            now = self._clock()
            if state["day"] != self._today():
                state["day"], state["auto_today"] = self._today(), 0
            notes = soul_mod.note_lines(text)
            in_notes = {fold(n) for n in notes}
            everything = notes + soul_mod.owner_lines(text)
            have = {fold(n) for n in everything}
            changed = False
            for raw in list(lines or [])[:soul_mod.APPEND_MAX_LINES]:
                one = soul_mod.clean_note(raw)
                if not one or len(one) > soul_mod.APPEND_LINE_MAX or soul_mod.secret_problem(one):
                    out.dropped += 1
                    continue
                line = f"- {one}"
                key, nid = fold(line), note_id(line)
                if key in have:                                   # 本來就有：算又確認了一次
                    meta = state["notes"].get(nid)
                    if meta is not None:
                        meta["confirmed_at"] = now
                        meta["confirmations"] = int(meta.get("confirmations") or 0) + 1
                        changed = True
                    out.confirmed.append(line)
                    continue
                if any(p["kind"] == "add" and fold(p["text"]) == key for p in state["pending"]):
                    continue                                      # 已經在等你確認
                if nid in state["suppress"]:                      # 你說過不要
                    out.dropped += 1
                    continue
                related, _ = most_related(line, everything)
                why = [WHY_REVIEW] if self.review else []
                why += risk_flags(one)
                if related:
                    why.append(WHY_OPPOSITE if only_negation_differs(line, related) else WHY_RELATED)
                if len(notes) + len(out.added) >= NOTES_MAX_LINES:
                    why.append(WHY_FULL)
                if state["auto_today"] >= AUTO_PER_DAY:
                    why.append(WHY_DAILY)
                ok = grounded(line, evidence)
                if not why:
                    if self.soul.append_notes([line], by=by):
                        state["notes"][nid] = self._meta(by, source, now, ok)
                        state["auto_today"] += 1
                        out.added.append(line)
                        everything.append(line)
                        have.add(key)
                        changed = True
                        continue
                    why.append(WHY_NO_ROOM)
                if len(state["pending"]) >= PENDING_MAX:
                    out.dropped += 1
                    continue
                item = {"id": "p-" + secrets.token_hex(4), "kind": "add", "text": line, "by": by, "source": source,
                        "at": now, "why": why, "related": related,
                        "related_in_notes": bool(related) and fold(related) in in_notes, "told": False}
                if ok is not None:
                    item["grounded"] = ok
                state["pending"].append(item)
                out.waiting.append(line)
                changed = True
                self.soul.record(by, "提議（等你確認）：" + line)
            if changed:
                self._save(state)
        return out

    # ── 你決定 ───────────────────────────────────────────────────────

    def approve(self, pid: str, *, replace: bool = False) -> dict:
        """採用一則提議。加筆記的：寫進「助理筆記」（replace=True＝順便把很像的那條舊的收起來）；
        收起來的：把那條搬到「收起來的」。回新的 view()。"""
        with self._lock:
            state = self._state()
            item = self._find(state["pending"], pid, "沒有這則提議（可能已經處理過了）。")
            now = self._clock()
            if item["kind"] == "retire":
                self._retire(state, str(item.get("nid") or note_id(item["text"])), now,
                             reason=str(item.get("reason") or "你同意收起來"), missing_ok=True)
            else:
                line = item["text"]
                old = str(item.get("related") or "")
                if replace and not (old and item.get("related_in_notes")):
                    raise LedgerError("這則提議沒有可以取代的舊筆記（很像的那一條是你自己寫的，要改請直接改上面的內容）。")
                if replace:
                    self._retire(state, note_id(old), now, reason="被新的一條取代", replaced_by=line, missing_ok=True)
                current = self.soul.text()
                have = {fold(n) for n in soul_mod.note_lines(current) + soul_mod.owner_lines(current)}
                if fold(line) not in have and not self.soul.append_notes([line], by="owner"):
                    self._save(state)                             # 取代的那條已經收起來了：存起來才放得回去
                    raise LedgerError(f"加不進去：soul.md 到 {soul_mod.MAX_CHARS} 字上限了，先刪掉或收起幾條再按一次。")
                state["notes"][note_id(line)] = self._meta(
                    str(item.get("by") or "mother"), str(item.get("source") or ""), now,
                    item.get("grounded") if isinstance(item.get("grounded"), bool) else None, approved=True)
            state["pending"] = [p for p in state["pending"] if p["id"] != pid]
            self._save(state)
            return self._view(state)

    def reject(self, pid: str) -> dict:
        """不採用。加筆記的：以後助理再提同一條直接丟；收起來的：筆記留著，算你剛確認過它還對。"""
        with self._lock:
            state = self._state()
            item = self._find(state["pending"], pid, "沒有這則提議（可能已經處理過了）。")
            now = self._clock()
            if item["kind"] == "retire":
                nid = str(item.get("nid") or note_id(item["text"]))
                meta = state["notes"].setdefault(nid, self._meta("owner", "", now))
                meta["confirmed_at"] = now
                if item.get("pair"):
                    self._suppress(state, str(item["pair"]))
            else:
                self._suppress(state, note_id(item["text"]))
                self.soul.record("owner", "不採用提議：" + item["text"])
            state["pending"] = [p for p in state["pending"] if p["id"] != pid]
            self._save(state)
            return self._view(state)

    def retire(self, nid: str) -> dict:
        """你把一條筆記收起來（不在 soul.md 裡了、AI 讀不到；「收起來的」裡還在，可以放回去）。"""
        with self._lock:
            state = self._state()
            self._retire(state, nid, self._clock(), reason="你收起來的")
            self._suppress(state, nid)
            self._save(state)
            return self._view(state)

    def restore(self, aid: str) -> dict:
        with self._lock:
            state = self._state()
            item = self._find(state["archive"], aid, "「收起來的」裡沒有這一條。")
            line, now = item["text"], self._clock()
            current = self.soul.text()
            have = {fold(n) for n in soul_mod.note_lines(current) + soul_mod.owner_lines(current)}
            if fold(line) not in have and not self.soul.append_notes([line], by="owner"):
                raise LedgerError(f"放不回去：soul.md 到 {soul_mod.MAX_CHARS} 字上限了，或這一條已經不合規則（太長、像密鑰）。")
            nid = note_id(line)
            state["notes"][nid] = self._meta(str(item.get("by") or "owner"), str(item.get("source") or ""), now,
                                             added_at=_num(item.get("added_at")) or now)
            state["archive"] = [a for a in state["archive"] if a["id"] != aid]
            state["suppress"] = [s for s in state["suppress"] if s != nid]
            self._save(state)
            return self._view(state)

    def confirm(self, nid: str) -> dict:
        """「這條還對」：重新起算多久沒確認。"""
        with self._lock:
            state = self._state()
            if not any(note_id(n) == nid for n in soul_mod.note_lines(self.soul.text())):
                raise LedgerError("soul.md 裡找不到這條筆記（可能已經改過了）。")
            now = self._clock()
            meta = state["notes"].setdefault(nid, self._meta("owner", "", now))
            meta["confirmed_at"] = now
            state["pending"] = [p for p in state["pending"] if not (p["kind"] == "retire" and p.get("nid") == nid)]
            self._save(state)
            return self._view(state)

    def _retire(self, state: dict, nid: str, now: float, *, reason: str, replaced_by: str = "",
                missing_ok: bool = False) -> None:
        removed = self.soul.filter_notes(lambda _i, line: note_id(line) != nid, by="owner",
                                         what="收起一條筆記" + (f"（{reason}）" if reason else ""))
        if not removed:
            if missing_ok:
                state["notes"].pop(nid, None)
                return
            raise LedgerError("soul.md 裡找不到這條筆記（可能已經改過了）。")
        meta = state["notes"].pop(nid, {})
        state["archive"].append({"id": "a-" + secrets.token_hex(4), "text": removed[0],
                                 "added_at": _num(meta.get("added_at")), "by": str(meta.get("by") or "owner"),
                                 "source": str(meta.get("source") or ""), "retired_at": now,
                                 "reason": reason[:REASON_MAX], "replaced_by": replaced_by})
        state["pending"] = [p for p in state["pending"] if not (p["kind"] == "retire" and p.get("nid") == nid)]

    # ── 整理（不叫 AI）───────────────────────────────────────────────

    def tidy(self) -> dict:
        """整理一次，回 {"removed", "proposed", "expired", "pending", "notes", "summary"}。
        自動做的只有不會掉東西的事（一模一樣的重複行、已經不存在的筆記的紀錄、過期的提議）；
        其他（很像的兩條、很久沒確認的）一律變成提議。"""
        with self._lock:
            state = self._state()
            now = self._clock()
            seen: set = set()

            def first_time(_i: int, line: str) -> bool:
                key = fold(line)
                if key in seen:
                    return False
                seen.add(key)
                return True

            removed = self.soul.filter_notes(first_time, by="tidy", what="整理：拿掉重複的筆記")
            notes = soul_mod.note_lines(self.soul.text())
            ids = {note_id(n): n for n in notes}
            before = len(state["notes"])
            state["notes"] = {k: v for k, v in state["notes"].items() if k in ids}
            have = {fold(n) for n in notes + soul_mod.owner_lines(self.soul.text())}
            cutoff = now - PENDING_TTL_DAYS * 86400
            fresh = [p for p in state["pending"]
                     if (_num(p.get("at")) or 0) >= cutoff
                     and not (p["kind"] == "retire" and p.get("nid") not in ids)
                     and not (p["kind"] == "add" and fold(p["text"]) in have)]
            expired = len(state["pending"]) - len(fresh)
            state["pending"] = fresh
            asked = {p.get("nid") for p in fresh if p["kind"] == "retire"}
            proposed = 0

            def ask(nid: str, line: str, reason: str, related: str = "", pair: str = "") -> None:
                nonlocal proposed
                if nid in asked or len(state["pending"]) >= PENDING_MAX:
                    return
                state["pending"].append({"id": "p-" + secrets.token_hex(4), "kind": "retire", "nid": nid, "text": line,
                                         "by": "tidy", "source": "tidy", "at": now, "why": [reason], "reason": reason,
                                         "related": related, "related_in_notes": bool(related), "pair": pair,
                                         "told": False})
                asked.add(nid)
                proposed += 1

            for i, older in enumerate(notes):                     # 很像的兩條：提議收起舊的（前面那條）
                for newer in notes[i + 1:]:
                    if similarity(older, newer) < NEAR_DUP:
                        continue
                    pair = "pair:" + "|".join(sorted((note_id(older), note_id(newer))))
                    if pair in state["suppress"]:
                        continue
                    opposite = only_negation_differs(older, newer)
                    ask(note_id(older), older,
                        "跟比較新的一條只差在否定字，可能互相矛盾：留哪一條？" if opposite else "跟比較新的一條幾乎一樣",
                        related=newer, pair=pair)
                    break
            for nid, line in ids.items():                         # 助理加的、很久沒再確認：還對嗎？
                meta = state["notes"].get(nid) or {}
                last = _num(meta.get("confirmed_at"))
                if meta.get("by") not in (None, "owner") and last is not None and now - last > STALE_DAYS * 86400:
                    ask(nid, line, f"{STALE_DAYS} 天沒有再確認過，還對嗎？")
            if removed or proposed or expired or before != len(state["notes"]):
                self._save(state)
            parts = []
            if removed:
                parts.append(f"拿掉 {len(removed)} 條重複的")
            if expired:
                parts.append(f"{expired} 則太久沒處理的提議丟掉了")
            if proposed:
                parts.append(f"新增 {proposed} 則提議")
            head = "整理過了：" + "、".join(parts) + "。" if parts else "整理過了，沒有要動的。"
            summary = f"{head}筆記 {len(notes)}/{NOTES_MAX_LINES} 條" + \
                (f"，{len(state['pending'])} 則提議等你確認。" if state["pending"] else "。")
            return {"removed": len(removed), "proposed": proposed, "expired": expired,
                    "pending": len(state["pending"]), "notes": len(notes), "summary": summary}

    def untold(self) -> int:
        """還沒通知過你的提議有幾則。"""
        with self._lock:
            return sum(1 for p in self._state()["pending"] if not p.get("told"))

    def mark_told(self) -> bool:
        """要通知了：今天還沒通知過＝把現在的提議都標成說過、回 True；今天說過了＝False（一天最多一次）。"""
        with self._lock:
            state = self._state()
            if state["told_day"] == self._today() or not any(not p.get("told") for p in state["pending"]):
                return False
            for p in state["pending"]:
                p["told"] = True
            state["told_day"] = self._today()
            self._save(state)
            return True

    # ── 遺忘、匯出 ───────────────────────────────────────────────────

    def forget(self, needle: str, *, confirm: bool = False) -> dict:
        """把提到 needle 的都拿掉：筆記（soul.md「助理筆記」段）、提議、收起來的、稽核紀錄裡的那幾筆、常駐助理的記憶。
        confirm=False＝只算會動到幾筆（先給你看）。你自己寫的段落不動，只回報有幾行提到（owner_lines）。"""
        needle = " ".join(str(needle or "").split())
        if len(needle) < FORGET_MIN:
            raise LedgerError(f"要忘掉的字至少 {FORGET_MIN} 個字（太短會掃到不相干的）。")
        low = needle.lower()

        def hit(*texts) -> bool:
            return any(low in str(t or "").lower() for t in texts)

        with self._lock:
            state = self._state()
            text = self.soul.text()
            notes = [n for n in soul_mod.note_lines(text) if hit(n)]
            pending = [p for p in state["pending"] if hit(p["text"], p.get("related"))]
            archive = [a for a in state["archive"] if hit(a["text"], a.get("replaced_by"))]
            result = {"notes": len(notes), "pending": len(pending), "archive": len(archive),
                      "owner_lines": sum(1 for n in soul_mod.owner_lines(text) if hit(n)),
                      "audit": sum(1 for e in self.soul.audit() if isinstance(e, dict) and hit(e.get("what"))),
                      "patrol": self.mother.scrub_memory(needle, dry_run=True) if self.mother is not None else 0,
                      "done": False, "preview": notes[:10]}
            if not confirm:
                return result
            if notes:
                self.soul.filter_notes(lambda _i, line: not hit(line), by="owner", what=f"遺忘（{len(notes)} 條筆記）")
            for line in notes + [p["text"] for p in pending if p["kind"] == "add"] + [a["text"] for a in archive]:
                state["notes"].pop(note_id(line), None)
                self._suppress(state, note_id(line))
            gone = {p["id"] for p in pending} | {a["id"] for a in archive}
            state["pending"] = [p for p in state["pending"] if p["id"] not in gone]
            state["archive"] = [a for a in state["archive"] if a["id"] not in gone]
            self._save(state)
            result["audit"] = self.soul.redact_audit(needle)
            if self.mother is not None:
                result["patrol"] = self.mother.scrub_memory(needle)
            result["done"] = True
            result["preview"] = []
            return result

    def export(self) -> dict:
        """你的東西全部倒出來（明文 dict：只回給擁有者自己，呼叫端不寫檔、不寫 log）。"""
        from synox.runtime.loop import iso
        with self._lock:
            state = self._state()
            view = self._view(state, archive_limit=ARCHIVE_MAX)
            patrol = []
            if self.mother is not None:
                patrol = [{"at": iso(_num(m.get("at"))), "said": m.get("said", ""), "answer": m.get("answer", "")}
                          for m in self.mother.memory()]
            return {"format": "synox-soul-export-1", "exported_at": iso(self._clock()),
                    "soul": {"text": self.soul.text(), "updated_at": iso(self.soul.updated_at())},
                    "notes": view["notes"], "pending": view["pending"], "archive": view["archive"],
                    "audit": [{"at": iso(_num(e.get("at"))), "by": e.get("by", ""), "what": e.get("what", "")}
                              for e in self.soul.audit() if isinstance(e, dict)],
                    "patrol_memory": patrol}

    # ── 給畫面、給系統提示 ───────────────────────────────────────────

    def view(self) -> dict:
        with self._lock:
            return self._view(self._state())

    def _view(self, state: dict, *, archive_limit: int = ARCHIVE_VIEW) -> dict:
        from synox.runtime.loop import iso
        now = self._clock()
        text = self.soul.text()
        notes = []
        for line in soul_mod.note_lines(text):
            nid = note_id(line)
            meta = state["notes"].get(nid) or {}
            last = _num(meta.get("confirmed_at"))
            by = str(meta.get("by") or "owner")
            notes.append({"id": nid, "text": line, "by": by, "source": str(meta.get("source") or ""),
                          "tracked": bool(meta), "added_at": iso(_num(meta.get("added_at"))),
                          "confirmed_at": iso(last), "grounded": meta.get("grounded"),
                          "stale": by != "owner" and last is not None and now - last > STALE_DAYS * 86400})
        pending = [{"id": p["id"], "kind": p["kind"], "text": p["text"], "by": str(p.get("by") or ""),
                    "source": str(p.get("source") or ""), "at": iso(_num(p.get("at"))),
                    "why": [str(w) for w in p.get("why", []) if isinstance(w, str)],
                    "related": str(p.get("related") or ""), "can_replace": p["kind"] == "add"
                    and bool(p.get("related")) and bool(p.get("related_in_notes")),
                    "grounded": p.get("grounded")} for p in state["pending"]]
        archive = [{"id": a["id"], "text": a["text"], "by": str(a.get("by") or ""),
                    "added_at": iso(_num(a.get("added_at"))), "retired_at": iso(_num(a.get("retired_at"))),
                    "reason": str(a.get("reason") or ""), "replaced_by": str(a.get("replaced_by") or "")}
                   for a in reversed(state["archive"][-archive_limit:])]
        return {"review": self.review, "notes": notes, "pending": pending, "archive": archive,
                "budget": {"chars": len(text), "max_chars": soul_mod.MAX_CHARS,
                           "prompt_chars": len(soul_mod.prompt_text(text, limit=10 ** 9)),
                           "prompt_max": soul_mod.PROMPT_MAX_CHARS,
                           "notes": len(notes), "notes_max": NOTES_MAX_LINES,
                           "pending": len(pending), "pending_max": PENDING_MAX,
                           "stale_days": STALE_DAYS}}

    def weigher(self) -> Callable[[str], float]:
        """給 SoulStore.for_prompt 的 weight：助理加的筆記照「上次確認」到現在的天數衰減（HALF_LIFE_DAYS 減半）；
        你自己寫的、沒有來歷的＝1（不衰減）。帳本第一次被問到才讀（沒超過上限的那些輪不讀保管箱）。"""
        cache: Dict[str, dict] = {}
        loaded = []

        def weight(line: str) -> float:
            if not loaded:
                loaded.append(True)
                try:
                    cache.update(self._state()["notes"])
                except Exception:
                    pass
            meta = cache.get(note_id(line)) or {}
            last = _num(meta.get("confirmed_at"))
            if last is None or meta.get("by") in (None, "owner"):
                return 1.0
            return 0.5 ** (max(0.0, self._clock() - last) / 86400 / HALF_LIFE_DAYS)

        return weight


# ── runtime 的任務 ───────────────────────────────────────────────────

class SoulTidy:
    """任務 system.soul_tidy：每 TIDY_INTERVAL 整理一次；有新的提議就通知擁有者一句（一天最多一次、安靜時段不吵）。"""

    def __init__(self, app, ledger: SoulLedger, *, quiet: Optional[Callable[[], bool]] = None):
        self.app = app
        self.ledger = ledger
        self._quiet = quiet or (lambda: False)

    def register(self, loop) -> None:
        loop.register(TASK_ID, TASK_NAME, fn=self.run, interval=TIDY_INTERVAL, timeout=TIDY_TIMEOUT,
                      first_delay=TIDY_FIRST_DELAY)

    def run(self, ctx=None) -> str:
        try:
            result = self.ledger.tidy()
        except (SoulError, LedgerError) as e:
            return f"沒有整理：{e}"
        summary = result["summary"]
        try:
            waiting = self.ledger.untold()
            if waiting and not self._quiet() and self.ledger.mark_told():
                self.app.notify_owner(f"🫀 常駐助理：有 {waiting} 則想記進 soul.md 的事等你確認（網頁「主控」→ 你的偏好）。")
                summary += "（通知了你）"
        except (SoulError, LedgerError):
            pass
        if ctx is not None:
            ctx.log(summary)
        return summary
