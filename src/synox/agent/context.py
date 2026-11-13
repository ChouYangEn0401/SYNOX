"""
Context 預算（docs/adr/0015、0016；研究交接書規格 6，卡片 E1、E2、E3、E5）：送給模型之前先估長度，超過就照 Qwen-Agent
的順序分級截斷——**不讓伺服器靜默地從最前面（系統提示）截掉**。

    estimate(text)                    粗估 token：CJK 字 1、其他每 4 字 1，再 ×1.15（留 15% 餘裕；不精確沒關係）
    fit(messages, limit, reserve=, start=, soul=) -> Fit
        limit＝llm.context_size（0＝不裁，原樣回）；reserve＝回覆上限＋工具規格的估算。順序：
        (1) 丟最舊的歷史（對話記憶的「使用者／AI」一對一對丟）
        (2) 這一輪除了最後一則以外的工具結果，內容換成「（省略）」
        (3) 截最後一則工具結果（保頭 2/3、尾 1/3）
        (4) 還超過：拿掉系統提示裡的 soul.md 區塊（擁有者偏好；最後才動）
        系統提示的其他部分與這一輪使用者說的話永遠不裁；都做完還超過＝Fit.over（照送，並告訴使用者）。
        **不改傳進來的 list 與 Message**（回新的 list；對話紀錄 append-only，E5）。
    cap_result(text, limit_chars)     工具結果超過上限：保頭 2/3、尾 1/3，中間一行「（省略 N 字…）」

誰開：`llm.context_size` 有設（> 0）才有預算；沒設＝不裁（保持以前的行為）。工具結果上限 `llm.tool_result_chars`
＝auto（預設：有預算時 3000 字，沒有＝不限）｜0（不限）｜正整數。截了什麼一律寫 log，並在這一輪結束時另送一則提醒給使用者（不靜默）。
"""

from __future__ import annotations

import dataclasses
import json
import math
import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from synox.llm import textproto
from synox.llm.base import TOOL, USER, Message

SAFETY = 1.15
MESSAGE_OVERHEAD = 4                   # 每則訊息的角色、模板標記（粗估）
OMITTED = "（省略）"
SOUL_OMITTED = "（使用者偏好 soul.md 這一輪太長、省略了）"
CAP_NOTE = "（省略 {n} 字；工具的完整輸出已直接給使用者的部分不受影響）"
DEFAULT_RESULT_CHARS = 3000
MAX_RESULT_CHARS = 200000
MIN_CUT_CHARS = 200
_CJK = re.compile(r"[⺀-鿿豈-﫿＀-￯\U00020000-\U0002fa1f]")


def estimate(text: str) -> int:
    text = text or ""
    cjk = len(_CJK.findall(text))
    other = len(text) - cjk
    return int(math.ceil((cjk + other / 4) * SAFETY))


def message_tokens(m: Message) -> int:
    n = estimate(m.content or "") + MESSAGE_OVERHEAD
    for c in m.tool_calls or ():
        try:
            args = json.dumps(c.args or {}, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            args = str(c.args)
        n += estimate(c.name + args)
    return n


def total_tokens(messages: Sequence[Message]) -> int:
    return sum(message_tokens(m) for m in messages)


def is_result(m: Message) -> bool:
    """工具結果：原生的 role=tool，或文字協定以「〔工具結果〕」開頭的 user 訊息。"""
    return m.role == TOOL or (m.role == USER and (m.content or "").startswith(textproto.RESULT_PREFIX))


def cap_result(text: str, limit_chars: int) -> str:
    """超過 limit_chars 字：保頭 2/3、尾 1/3，中間放一行說省略了幾個字（含分隔符時頭尾的分隔符都留著）。"""
    text = text or ""
    if not limit_chars or limit_chars <= 0 or len(text) <= limit_chars:
        return text
    head = limit_chars * 2 // 3
    tail = limit_chars - head
    omitted = len(text) - head - tail
    return text[:head] + "\n" + CAP_NOTE.format(n=omitted) + "\n" + (text[-tail:] if tail else "")


@dataclass
class Fit:
    messages: List[Message] = field(default_factory=list)
    limit: int = 0
    budget: int = 0
    before: int = 0
    after: int = 0
    dropped_turns: int = 0
    omitted_results: int = 0
    cut_chars: int = 0
    soul_dropped: bool = False
    over: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.dropped_turns or self.omitted_results or self.cut_chars or self.soul_dropped)

    def log_text(self) -> str:
        return (f"limit={self.limit} budget={self.budget} before={self.before} after={self.after} "
                f"dropped_turns={self.dropped_turns} omitted_results={self.omitted_results} cut_chars={self.cut_chars} "
                f"soul_dropped={self.soul_dropped} over={self.over}")


def _omit(m: Message) -> Message:
    if m.role == TOOL:
        return dataclasses.replace(m, content=OMITTED)
    first = (m.content or "").split("\n", 1)[0]               # 文字協定：「〔工具結果〕<工具名>」那一行留著
    return dataclasses.replace(m, content=f"{first}\n{OMITTED}")


def fit(messages: Sequence[Message], limit: int, *, reserve: int = 0, start: Optional[int] = None,
        soul: str = "") -> Fit:
    """messages[0] 是系統提示、messages[start] 是這一輪使用者說的話（沒給＝最後一則不是工具結果的 user）。"""
    msgs = list(messages)
    out = Fit(messages=msgs, limit=int(limit or 0))
    if out.limit <= 0 or not msgs:
        return out
    out.budget = max(0, out.limit - max(0, int(reserve or 0)))
    out.before = out.after = total_tokens(msgs)
    if out.before <= out.budget:
        return out
    if start is None:
        start = max((i for i, m in enumerate(msgs) if m.role == USER and not is_result(m)), default=len(msgs) - 1)
    start = max(1, min(int(start), len(msgs) - 1))

    def total() -> int:
        return total_tokens(msgs)

    # (1) 最舊的歷史，一對一對丟（對話記憶是「使用者／AI」成對寫的）
    while total() > out.budget and start > 1:
        n = 2 if start > 2 else 1
        del msgs[1:1 + n]
        start -= n
        out.dropped_turns += 1
    # (2) 這一輪除了最後一則以外的工具結果：內容換成（省略）
    results = [i for i in range(start + 1, len(msgs)) if is_result(msgs[i])]
    for i in results[:-1]:
        if total() <= out.budget:
            break
        msgs[i] = _omit(msgs[i])
        out.omitted_results += 1
    # (3) 截最後一則工具結果（保頭尾）
    if results and total() > out.budget:
        i = results[-1]
        original = msgs[i]
        content = original.content or ""
        keep = len(content)
        while keep > MIN_CUT_CHARS and total() > out.budget:
            over = total() - out.budget
            ratio = max(0.0, 1 - (over + 8) / max(1, estimate(msgs[i].content)))
            keep = max(MIN_CUT_CHARS, min(keep - 1, int(keep * ratio)))
            msgs[i] = dataclasses.replace(original, content=cap_result(content, keep))
        if msgs[i] is not original:
            out.cut_chars = len(content) - keep
    # (4) soul.md 區塊（系統提示裡最後才動的部分）
    if total() > out.budget and soul and soul in (msgs[0].content or ""):
        msgs[0] = dataclasses.replace(msgs[0], content=msgs[0].content.replace(soul, SOUL_OMITTED))
        out.soul_dropped = True
    out.after = total()
    out.over = out.after > out.budget
    return out


def note_text(*, limit: int, dropped_turns: int = 0, omitted_results: int = 0, cut_chars: int = 0,
              soul_dropped: bool = False, over: bool = False, capped: Sequence[str] = ()) -> str:
    """這一輪結束時給使用者的一則提醒（不進對話記憶）；什麼都沒截＝""。"""
    parts = []
    if dropped_turns:
        parts.append(f"較舊的 {dropped_turns} 輪對話")
    if omitted_results:
        parts.append(f"{omitted_results} 個較早的工具結果")
    if cut_chars:
        parts.append(f"最後一個工具結果的中間 {cut_chars} 字")
    if soul_dropped:
        parts.append("你的偏好設定（soul.md）")
    if capped:
        parts.append("太長的工具結果（" + "、".join(dict.fromkeys(capped)) + "）的中間部分")
    if not parts and not over:
        return ""
    head = f"⚠️ 對話超過 context 預算（llm.context_size={limit}），這一輪交給 AI 時省略了：" if parts else \
        f"⚠️ 對話超過 context 預算（llm.context_size={limit}）"
    text = head + "、".join(parts) + "。"
    if over:
        text += "省略之後仍然太長，模型可能沒看到全部：把 llm.context_size 調大，或少裝幾個工具。"
    return text


# ── 設定 ──────────────────────────────────────────────────────────────

def parse_result_chars(value):
    """llm.tool_result_chars：auto（預設）｜0（不限）｜正整數（字數）。寫錯丟 ValueError。"""
    if value is None or value == "" or (isinstance(value, str) and value.strip().lower() == "auto"):
        return "auto"
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_RESULT_CHARS:
        raise ValueError(f"llm.tool_result_chars 只能是 auto、0（不限）或 1～{MAX_RESULT_CHARS} 的整數（字數）。")
    return value


def context_limit(llm: Optional[dict]) -> int:
    """預算上限＝llm.context_size（> 0 才算；沒設或寫錯＝0，不裁）。"""
    from synox.llm.local import parse_context
    try:
        return int(parse_context((llm or {}).get("context_size")) or 0)
    except ValueError:
        return 0


def result_chars(llm: Optional[dict]) -> int:
    """工具結果的上限（字）：auto＝有 context 預算時 3000、沒有＝0（不限，以前的行為）。"""
    try:
        value = parse_result_chars((llm or {}).get("tool_result_chars"))
    except ValueError:
        return 0
    if value == "auto":
        return DEFAULT_RESULT_CHARS if context_limit(llm) > 0 else 0
    return int(value)
