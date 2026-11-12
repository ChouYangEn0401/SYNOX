"""
soul.md：常駐助理的靈魂檔（docs/adr/0001 §5）。存保管箱（加密），不進 repo、不寫 log。

    soul = SoulStore(vault, clock=time.time)
    soul.text() / soul.updated_at()       讀（沒改過＝預設的四個空段落、updated_at None）
    soul.write(text, by="owner")          你改（空的＝重設）；太長、有像密鑰的 → SoulError
    soul.append_notes(lines, by="mother") 常駐助理追加：只加在「## 助理筆記」段最後，一次最多 3 行、每行 200 字，
                                          重複的、有密鑰樣式的、總長超過上限的不加；回實際加了哪幾行
    soul.audit()                          每次改的紀錄（時間、誰、什麼）
    soul.for_prompt()                     對話助理的系統提示用（唯讀；拿掉註解、沒寫東西＝""、有密鑰樣式＝""、最多 2000 字；
                                          決定 Q7，docs/adr/0002）

保管箱打不開（vault=None）＝讀寫都丟 SoulError（不退回明文存）；for_prompt 回 ""。
"""

from __future__ import annotations

import re
import threading
import time
from typing import Callable, List, Optional

from synox.packs.kit import TOKEN_PATTERNS

KEY = "runtime_soul"
AUDIT_KEY = "runtime_soul_audit"
MAX_CHARS = 6000
APPEND_MAX_LINES = 3
APPEND_LINE_MAX = 200
AUDIT_MAX = 200
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


PROMPT_MAX_CHARS = 2000            # 對話助理的系統提示每一輪都送：比 MAX_CHARS 短，省 token（決定 Q7，docs/adr/0002）
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def prompt_text(text: str, limit: int = PROMPT_MAX_CHARS) -> str:
    """給對話助理系統提示用的 soul.md：拿掉 <!-- --> 註解；只剩標題與空行（還沒寫東西）＝""；
    有像密鑰的片段＝""（整份不送）；超過 limit 字截斷並註明。"""
    body = _COMMENT.sub("", normalize(text))
    rows = [r.rstrip() for r in body.split("\n")]
    if not any(r.strip() and not r.lstrip().startswith("#") for r in rows):
        return ""
    if secret_problem(body):
        return ""
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(rows).strip())
    if len(out) > limit:
        out = out[:limit].rstrip() + "\n（後面太長，省略）"
    return out


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

    def for_prompt(self, limit: int = PROMPT_MAX_CHARS) -> str:
        """對話助理（agent/loop.py）唯讀用：prompt_text(text())。沒寫東西／保管箱沒開或解不開＝""（不丟錯、不寫 log）。"""
        if self._vault is None:
            return ""
        try:
            return prompt_text(self.text(), limit)
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
                one = " ".join(str(raw or "").split()).lstrip("-• ").strip()
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
