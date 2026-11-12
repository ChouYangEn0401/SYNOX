"""
soul.md：常駐助理的靈魂檔（docs/adr/0001 §5）。存保管箱（加密），不進 repo、不寫 log。

    soul = SoulStore(vault, clock=time.time)
    soul.text() / soul.updated_at()       讀（沒改過＝預設的四個空段落、updated_at None）
    soul.write(text, by="owner")          你改（空的＝重設）；太長、有像密鑰的 → SoulError
    soul.append_notes(lines, by="mother") 常駐助理追加：只加在「## 助理筆記」段最後，一次最多 3 行、每行 200 字，
                                          重複的、有密鑰樣式的、總長超過上限的不加；回實際加了哪幾行
    soul.audit()                          每次改的紀錄（時間、誰、什麼）
    soul.for_prompt(query=, weight=)      對話助理的系統提示用（唯讀；拿掉註解、沒寫東西＝""、有密鑰樣式＝""、最多 2000 字；
                                          決定 Q7，docs/adr/0002）。超過上限時你寫的段落先留，「助理筆記」照跟這句話的相關度
                                          與新舊挑著放（docs/adr/0005），不是從尾巴硬切
    soul.filter_notes(keep, by=, what=)   只能**拿掉**「助理筆記」段裡的行（別的段落碰不到）；soul 帳本（ledger.py）收起、整理、遺忘用
    soul.record(by, what) / soul.redact_audit(needle)   多記一筆稽核／把稽核裡提到某段字的那幾筆蓋掉（遺忘用）

保管箱打不開（vault=None）＝讀寫都丟 SoulError（不退回明文存）；for_prompt 回 ""。
"""

from __future__ import annotations

import re
import threading
import time
from typing import Callable, List, Optional, Set, Tuple

from synox.packs.kit import TOKEN_PATTERNS

KEY = "runtime_soul"
AUDIT_KEY = "runtime_soul_audit"
MAX_CHARS = 6000
APPEND_MAX_LINES = 3
APPEND_LINE_MAX = 200
AUDIT_MAX = 200
REDACTED = "（已遺忘）"
NOTES_HEADING = "## 助理筆記"

DEFAULT_SOUL = (
    "# soul.md\n"
    "\n"
    "<!-- 常駐助理每次巡都會讀這份。寫你的偏好、希望它怎麼跟你說話、一直要記得的事。不要寫密碼或金鑰。 -->\n"
    "\n"
    "## 偏好\n"
    "\n"
    "## 語氣\n"
    "\n"
    "## 長期注意事項\n"
    "\n"
    f"{NOTES_HEADING}\n"
)


class SoulError(Exception):
    """一句給人看的話。"""


def secret_problem(text: str) -> str:
    """有像密鑰的片段 → 一句說明；沒有 → ""。"""
    for pattern in TOKEN_PATTERNS:
        if pattern.search(text or ""):
            return "內容看起來有密鑰（API key、bot token、私鑰之類），soul.md 會送給 AI，不能放。"
    return ""


def normalize(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def clean_note(raw) -> str:
    """一行筆記的字：壓成一行、拿掉開頭的 - •（回的不帶 "- "；空的＝""）。"""
    return " ".join(str(raw or "").split()).lstrip("-• ").strip()


def _notes_span(rows: List[str]) -> Optional[Tuple[int, int]]:
    """「## 助理筆記」段在 rows 裡的（標題那一行, 下一個 ## 的位置）；沒有這段＝None。"""
    start = next((i for i, r in enumerate(rows) if r.strip() == NOTES_HEADING), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(rows)) if rows[i].startswith("## ")), len(rows))
    return start, end


def _is_bullet(row: str) -> bool:
    return row.strip().startswith("- ")


def note_lines(text: str) -> List[str]:
    """「助理筆記」段裡的每一條（"- …"，照順序）。"""
    rows = normalize(text).rstrip("\n").split("\n")
    span = _notes_span(rows)
    if span is None:
        return []
    return [r.strip() for r in rows[span[0] + 1:span[1]] if _is_bullet(r)]


def owner_lines(text: str) -> List[str]:
    """「助理筆記」段以外的每一條（"- …"）：你自己寫的，助理碰不到。註解不算。"""
    rows = _COMMENT.sub("", normalize(text)).rstrip("\n").split("\n")
    span = _notes_span(rows) or (len(rows), len(rows))
    return [r.strip() for i, r in enumerate(rows) if _is_bullet(r) and not span[0] < i < span[1]]


_WORD = re.compile(r"[a-z0-9]{2,}")
_CJK = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+")


def grams(text: str) -> Set[str]:
    """比對用的小片段：英數的字（2 個字元以上）＋中日韓文每兩個字一組（只有一個字就那個字）。不斷詞、不用外部套件。"""
    low = (text or "").lower()
    out = set(_WORD.findall(low))
    for run in _CJK.findall(low):
        if len(run) == 1:
            out.add(run)
        out.update(run[i:i + 2] for i in range(len(run) - 1))
    return out


def relevance(query: str, line: str) -> float:
    """這一條筆記有多少比例的片段出現在 query 裡（0～1）。"""
    mine = grams(line)
    return len(mine & grams(query)) / len(mine) if mine and query else 0.0


PROMPT_MAX_CHARS = 2000            # 對話助理的系統提示每一輪都送：比 MAX_CHARS 短，省 token（決定 Q7，docs/adr/0002）
_COMMENT = re.compile(r"<!--.*?-->", re.S)
RELEVANCE_WEIGHT = 3.0             # 挑筆記時的分數＝跟這句話的相關度 × 這個數 ＋ 新舊（0～1）
MORE_NOTES = "（還有 {n} 條助理筆記這一輪沒放）"


def prompt_text(text: str, limit: int = PROMPT_MAX_CHARS, query: str = "",
                weight: Optional[Callable[[str], float]] = None) -> str:
    """給對話助理系統提示用的 soul.md：拿掉 <!-- --> 註解；只剩標題與空行（還沒寫東西）＝""；
    有像密鑰的片段＝""（整份不送）。超過 limit 字：你寫的段落全留，「助理筆記」照分數（跟 query 的相關度、
    weight(行) 給的新舊）由高到低放到滿、其餘註明幾條沒放；你寫的段落自己就超過＝照舊從尾巴截斷並註明。"""
    body = _COMMENT.sub("", normalize(text))
    rows = [r.rstrip() for r in body.split("\n")]
    if not any(r.strip() and not r.lstrip().startswith("#") for r in rows):
        return ""
    if secret_problem(body):
        return ""
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(rows).strip())
    if len(out) <= limit:
        return out
    return _pick_notes(out, limit, query, weight) or out[:limit].rstrip() + "\n（後面太長，省略）"


def _pick_notes(out: str, limit: int, query: str, weight: Optional[Callable[[str], float]]) -> str:
    """超過上限時挑筆記（見 prompt_text）。沒有筆記可以省、或你寫的段落自己就放不下＝""（呼叫端照舊截斷）。"""
    rows = out.split("\n")
    span = _notes_span(rows)
    if span is None:
        return ""
    notes = [i for i in range(span[0] + 1, span[1]) if _is_bullet(rows[i])]
    fixed = sum(len(r) + 1 for r in rows) - sum(len(rows[i]) + 1 for i in notes)
    room = limit - fixed - len(MORE_NOTES.format(n=len(notes))) - 1
    if not notes or room < 0:
        return ""

    def score(i: int) -> float:
        try:
            age = float(weight(rows[i].strip())) if weight is not None else 1.0
        except Exception:
            age = 1.0
        return RELEVANCE_WEIGHT * relevance(query, rows[i]) + age

    keep: Set[int] = set()
    for i in sorted(notes, key=lambda i: (score(i), i), reverse=True):   # 同分：後面的（比較新）先
        if len(rows[i]) + 1 <= room:
            keep.add(i)
            room -= len(rows[i]) + 1
    drop = set(notes) - keep
    picked = [r for i, r in enumerate(rows[:span[1]]) if i not in drop]
    while picked and not picked[-1].strip():
        picked.pop()
    tail = rows[span[1]:]
    return "\n".join(picked + [MORE_NOTES.format(n=len(drop))] + ([""] + tail if tail else [])).strip()


class SoulStore:

    def __init__(self, vault, *, clock: Callable[[], float] = time.time):
        self._vault = vault
        self._clock = clock
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self._vault is not None

    def _need(self):
        if self._vault is None:
            raise SoulError("保管箱沒有打開，soul.md 讀寫不了（python -m synox doctor 看原因）。")
        return self._vault

    def _data(self) -> dict:
        data = self._need().load_json(KEY, None)
        return data if isinstance(data, dict) and isinstance(data.get("text"), str) else {}

    def text(self) -> str:
        return self._data().get("text") or DEFAULT_SOUL

    def for_prompt(self, limit: int = PROMPT_MAX_CHARS, *, query: str = "",
                   weight: Optional[Callable[[str], float]] = None) -> str:
        """對話助理（agent/loop.py）唯讀用：prompt_text(text(), …)。沒寫東西／保管箱沒開或解不開＝""（不丟錯、不寫 log）。
        query＝使用者這一輪說的話、weight＝soul 帳本給的新舊（只在超過 limit、要挑筆記時用到）。"""
        if self._vault is None:
            return ""
        try:
            return prompt_text(self.text(), limit, query, weight)
        except Exception:                            # 保管箱解不開：這一輪就不放 soul（聊天照常）
            return ""

    def updated_at(self) -> Optional[float]:
        at = self._data().get("updated_at")
        return float(at) if isinstance(at, (int, float)) else None

    def audit(self) -> List[dict]:
        data = self._need().load_json(AUDIT_KEY, [])
        return data if isinstance(data, list) else []

    def _record(self, by: str, what: str) -> None:
        vault = self._need()
        log = self.audit()
        log.append({"at": self._clock(), "by": by, "what": what[:300]})
        vault.save_json(AUDIT_KEY, log[-AUDIT_MAX:])

    def record(self, by: str, what: str) -> None:
        """多記一筆稽核（soul 帳本的提議、拒絕用；soul.md 本身沒有改）。"""
        with self._lock:
            self._record(by, what)

    def redact_audit(self, needle: str) -> int:
        """遺忘：稽核紀錄裡提到 needle 的那幾筆，內容蓋成「（已遺忘）」（時間與誰留著）。回蓋了幾筆。"""
        low = (needle or "").strip().lower()
        if not low:
            return 0
        with self._lock:
            log = self.audit()
            hits = [e for e in log if isinstance(e, dict) and low in str(e.get("what", "")).lower()]
            for e in hits:
                e["what"] = REDACTED
            if hits:
                self._need().save_json(AUDIT_KEY, log)
            return len(hits)

    def _save(self, text: str, by: str, what: str) -> float:
        now = self._clock()
        self._need().save_json(KEY, {"text": text, "updated_at": now})
        self._record(by, what)
        return now

    def write(self, text: str, *, by: str = "owner") -> dict:
        """你改（網頁 PUT）：空的（或只有空白）＝重設成預設。回 {"text", "updated_at"}。"""
        if not isinstance(text, str):
            raise SoulError("text 要是字串。")
        text = normalize(text)
        if len(text) > MAX_CHARS:
            raise SoulError(f"soul.md 最多 {MAX_CHARS} 字（現在 {len(text)} 字）。")
        problem = secret_problem(text)
        if problem:
            raise SoulError(problem)
        with self._lock:
            if not text.strip():
                at = self._save(DEFAULT_SOUL, by, "重設")
                return {"text": DEFAULT_SOUL, "updated_at": at}
            if not text.endswith("\n"):
                text += "\n"
            at = self._save(text, by, f"改了全文（{len(text)} 字）")
            return {"text": text, "updated_at": at}

    def append_notes(self, lines: List[str], *, by: str = "mother") -> List[str]:
        """常駐助理追加（規則見模組說明）。回實際加進去的行（已經是 "- …" 的樣子）。"""
        with self._lock:
            text = self.text()
            existing = {ln.strip() for ln in text.split("\n")}
            added: List[str] = []
            for raw in lines[:APPEND_MAX_LINES]:
                one = clean_note(raw)
                if not one or len(one) > APPEND_LINE_MAX or secret_problem(one):
                    continue
                line = f"- {one}"
                if line in existing or line in added:
                    continue
                added.append(line)
            if not added:
                return []
            new_text = self._insert_notes(text, added)
            if len(new_text) > MAX_CHARS:
                return []
            self._save(new_text, by, "追加：" + " / ".join(added))
            return added

    def filter_notes(self, keep: Callable[[int, str], bool], *, by: str = "owner", what: str = "") -> List[str]:
        """「助理筆記」段的每一條（第幾條、"- …"）問一次 keep：回 False 的那幾行拿掉。只能拿掉、不能改字，
        別的段落與筆記段裡不是 "- " 開頭的行都不動。回拿掉的行；一行都沒拿掉＝不存檔、不記稽核。"""
        with self._lock:
            rows = self.text().rstrip("\n").split("\n")
            span = _notes_span(rows)
            if span is None:
                return []
            removed: List[str] = []
            kept: List[str] = []
            n = 0
            for i, row in enumerate(rows):
                if span[0] < i < span[1] and _is_bullet(row):
                    n += 1
                    if not keep(n - 1, row.strip()):
                        removed.append(row.strip())
                        continue
                kept.append(row)
            if removed:
                self._save("\n".join(kept) + "\n", by, what or f"拿掉 {len(removed)} 條筆記")
            return removed

    @staticmethod
    def _insert_notes(text: str, lines: List[str]) -> str:
        """加在「## 助理筆記」段的最後（下一個 ## 之前）；沒有這段就在檔尾補一段。"""
        rows = text.rstrip("\n").split("\n")
        try:
            start = next(i for i, r in enumerate(rows) if r.strip() == NOTES_HEADING)
        except StopIteration:
            return text.rstrip("\n") + f"\n\n{NOTES_HEADING}\n" + "\n".join(lines) + "\n"
        end = next((i for i in range(start + 1, len(rows)) if rows[i].startswith("## ")), len(rows))
        while end - 1 > start and not rows[end - 1].strip():
            end -= 1
        rows[end:end] = lines
        return "\n".join(rows) + "\n"
