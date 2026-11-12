"""
切訊息（Telegram 4096、Discord 2000）：輸出 adapter 把每個區塊畫成一個 Piece，這裡負責打包與切割。

- Piece＝prefix＋一串 Atom＋suffix。Atom 是「一小段原始字＋它自己的開頭與結尾標記」（例如 <b>…</b>、**…**）；
  原始字到組裝時才跳脫，所以切在哪裡都不會切壞實體（&amp;）或標籤。
- 打包：在區塊邊界切；放得下就跟前一則併在一起（中間空一行）。
- 單一區塊太長才在區塊裡切：每一段都補上 prefix／suffix（例如 <pre>…</pre>、``` 圍欄），
  切到的 Atom 兩半各自補上自己的開頭與結尾標記——所以每一則的標籤一定成對。
  切點優先找換行，其次空白，都沒有（一行沒有空白的超長字串）才硬切。
- 長度一律用 UTF-16 單位（width.utf16_len）。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable, List

from synox.present.width import utf16_len


@dataclass
class Atom:
    text: str
    open: str = ""
    close: str = ""
    escape: bool = True          # False：text 已經是最後的樣子（例如 Discord 程式碼區塊裡的字）


@dataclass
class Piece:
    atoms: List[Atom] = field(default_factory=list)
    prefix: str = ""
    suffix: str = ""


class Packer:

    def __init__(self, limit: int, esc: Callable[[str], str], sep: str = "\n\n",
                 measure: Callable[[str], int] = utf16_len):
        self.limit = int(limit)
        self.esc = esc
        self.sep = sep
        self.measure = measure

    def atom(self, a: Atom, text=None) -> str:
        body = a.text if text is None else text
        return a.open + (self.esc(body) if a.escape else body) + a.close

    def render(self, piece: Piece) -> str:
        return piece.prefix + "".join(self.atom(a) for a in piece.atoms) + piece.suffix

    def pack(self, pieces: List[Piece]) -> List[str]:
        out: List[str] = []
        cur = ""
        for piece in pieces:
            if not piece.atoms:
                continue
            whole = self.render(piece)
            parts = [whole] if self.measure(whole) <= self.limit else self.split(piece)
            for i, part in enumerate(parts):
                if i == 0 and cur and self.measure(cur + self.sep + part) <= self.limit:
                    cur = cur + self.sep + part
                    continue
                if cur:
                    out.append(cur)
                cur = part
        if cur:
            out.append(cur)
        return out

    def _cut(self, a: Atom, room: int) -> int:
        """這個 Atom 的字最多取前幾個字元，畫出來（含開頭結尾標記）還放得進 room。"""
        lo, hi = 0, len(a.text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.measure(self.atom(a, a.text[:mid])) <= room:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def split(self, piece: Piece) -> List[str]:
        budget = self.limit - self.measure(piece.prefix) - self.measure(piece.suffix)
        parts: List[str] = []
        cur: List[str] = []
        used = 0

        def flush():
            nonlocal cur, used
            if cur:
                body = "".join(cur)
                if body.endswith("\n"):                    # 切在換行上：結尾的換行不用留（圍欄前不會多一行空白）
                    body = body[:-1]
                parts.append(piece.prefix + body + piece.suffix)
            cur, used = [], 0

        queue = deque(piece.atoms)
        while queue:
            a = queue.popleft()
            if not cur and not a.text.strip("\n") and not a.open:
                continue                                   # 新的一則不用從換行開始
            s = self.atom(a)
            cost = self.measure(s)
            if used + cost <= budget:
                cur.append(s)
                used += cost
                continue
            if cost <= budget and cur:                     # 整個放得進新的一則：換一則
                flush()
                queue.appendleft(a)
                continue
            room = budget - used
            if room - self.measure(a.open + a.close) < 8 and cur:
                flush()
                room = budget
            k = max(1, self._cut(a, room))
            head = a.text[:k]
            cut = k
            if k < len(a.text):
                nl = head.rfind("\n")
                sp = head.rfind(" ")
                if nl > k // 2:
                    cut = nl
                elif sp > k // 2:
                    cut = sp + 1
            rest = a.text[cut:]
            if rest.startswith("\n"):
                rest = rest[1:]
            cur.append(self.atom(a, a.text[:cut]))
            flush()
            if rest:
                queue.appendleft(Atom(rest, a.open, a.close, a.escape))
        flush()
        return parts
