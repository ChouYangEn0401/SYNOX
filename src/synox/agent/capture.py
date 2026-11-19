"""
執行工具時用的 Channel：指令「回給這個聊天的純文字」攔下來交給 AI（工具結果），其他照常送給使用者
（帶按鈕的訊息、圖片、檔案、送給別的聊天的），並在工具結果裡註明「已經直接傳給使用者」——照 前身專案 bridge 的規則。

via_ai = True：SDK 的 Forms 與 Node.precheck 看這個旗標（經 AI 呼叫時不開問答，例如驗證碼）。
note_failure：loader／mcp 經 health.observe_failure 交來的失敗（agent/loop.py 改回 AI 一行 `FAIL …`）。
note_receipt：schedule.receipt.emit 交來的排程回執（docs/adr/0029 §3.2）；loop 在工具結果後面附上 machine_line()、
記進證據帳本，承諾把關（agent/claims.promise_verdict）看這一輪有沒有回執。
note_structured：loader 交來的「給 AI 的結構化結果」（核心合一規劃 11.6，agent/structured.py）：剛剛攔下來的那一行
（給人看的字）在 for_ai() 裡換成 message＋精簡 JSON；close() 照舊回給人看的字。
waker：發這次呼叫的 AgentLoop（loop 設）；工具執行中要確認（needs_confirm）出的卡記得它，按了之後叫醒它（規劃 11.10）。

CardRunApi（核准卡按 ✅ 之後執行用）：跟 CaptureApi 一樣記下結果，但**每一則都照常送給使用者**（人看到的跟以前一樣）；
via_ai＝False（照人按的處理：要碼照問、手動執行的警告照給），sync_result＝True（cli／mcp 同步跑完，結果才收得到）。
"""

from __future__ import annotations

import threading
from typing import Any, List, Optional, Sequence, Tuple

from isdtelekit.core.richtext import plain

from synox.agent import structured


def _labels(markup) -> str:
    rows = (markup or {}).get("inline_keyboard") or []
    names = [b.get("text", "") for row in rows for b in row]
    return f"（按鈕：{'、'.join(names)}）" if names else ""


class CaptureApi:
    via_ai = True
    sync_result = False

    def __init__(self, real, chat_id: int, waker=None):
        self._real = real
        self._chat = chat_id
        self._lines: List[str] = []
        self._structured: List[Tuple[int, str, Any]] = []   # (哪一行, message, 給 AI 的那一份)
        self._open = True
        self._lock = threading.Lock()
        self.waker = waker                  # 發這次呼叫的 AgentLoop（needs_confirm 的卡按了之後叫醒它）
        self.carded = False                 # 執行中送了確認卡（工具回 needs_confirm）：這一輪 AI 就停在這裡
        self.failure = None                 # 工具失敗了（health.Failure）：loop 交回 AI 的是固定格式的一行，不是人看的字
        self.receipts: List[object] = []     # 這次呼叫真的排上的事（schedule.receipt.ScheduleReceipt；承諾把關看這裡）

    def note_structured(self, shown: str, message: str, payload: Any) -> None:
        """loader：剛剛送出的那一則（shown，給人看的字）在 AI 那一份換成 message＋精簡 JSON（structured.compose）。
        找不到那一行（例如沒有送出任何字）就另加一行。"""
        with self._lock:
            if not self._open:
                return
            want = plain(shown or "")
            idx = next((i for i in range(len(self._lines) - 1, -1, -1) if self._lines[i] == want), None)
            if idx is None or any(i == idx for i, _m, _p in self._structured):
                self._lines.append("")
                idx = len(self._lines) - 1
            self._structured.append((idx, message or "", payload))

    @property
    def has_structured(self) -> bool:
        return bool(self._structured)

    def for_ai(self, limit: int, secrets: Sequence[str] = ()) -> str:
        """交回 AI 的字：沒有結構化結果＝跟 close() 一樣（攔下來的每一行）；有＝那幾行換成 message＋精簡 JSON，
        整段不超過 limit（其他行先算，剩下的平分給每一段 JSON）。"""
        with self._lock:
            lines = list(self._lines)
            notes = list(self._structured)
        if not notes:
            return "\n".join(lines)
        swap = {idx: (message, payload) for idx, message, payload in notes}
        other = sum(len(line) + 1 for i, line in enumerate(lines) if i not in swap)
        each = max(len(structured.LABEL) + structured.MIN_JSON, (int(limit) - other) // len(swap) - 1)
        out = []
        for i, line in enumerate(lines):
            if i in swap:
                message, payload = swap[i]
                out.append(structured.compose(structured.scrub(message, secrets),
                                              structured.scrub(payload, secrets), each))
            elif line:
                out.append(line)
        return "\n".join(out)

    def mark_carded(self) -> None:
        self.carded = True

    def note_failure(self, failure) -> None:
        self.failure = failure

    def note_receipt(self, receipt) -> None:
        """schedule.receipt.emit 交來的排程回執（ADR 0029 §3.2）：只有真的排上了才會有。
        loop 把每張的 machine_line() 附在工具結果後面，並記進這一輪的證據（claims.promise_verdict）。"""
        with self._lock:
            self.receipts.append(receipt)

    def receipt_lines(self) -> List[str]:
        out = []
        for r in list(self.receipts):
            try:
                out.append(r.machine_line())
            except Exception:
                continue
        return out

    @property
    def channel_name(self) -> str:
        return getattr(self._real, "channel_name", "")

    def _note(self, chat_id: int, line: str) -> None:
        with self._lock:
            if self._open and chat_id == self._chat:
                self._lines.append(line)

    def send_message(self, chat_id, text, reply_markup=None, quiet=False, **kw):
        with self._lock:
            capture = self._open and chat_id == self._chat and reply_markup is None
            if capture:
                self._lines.append(plain(text))
        if capture:
            return {"ok": True, "result": {"message_id": 0}}
        if reply_markup is not None:
            self._note(chat_id, f"〔已直接傳給使用者一則帶按鈕的訊息〕{plain(text)[:300]}{_labels(reply_markup)}")
        return self._real.send_message(chat_id, text, reply_markup=reply_markup, quiet=quiet, **kw)

    def send_photo(self, chat_id, photo, caption=""):
        self._note(chat_id, f"〔已直接傳給使用者一張圖〕{caption[:200]}")
        return self._real.send_photo(chat_id, photo, caption=caption)

    def send_image(self, chat_id, images, caption="", reply_markup=None, **kw):
        """工具回覆帶的圖（docs/sdk.md「回覆帶圖」）：直接給使用者，AI 拿到一行「已經傳了幾張圖」＋說明。
        這個 channel 不能畫圖（Telegram、Discord…）＝回 ok False，呼叫的人（kit.send_image）改送 send_photo。"""
        fn = getattr(self._real, "send_image", None)
        if not callable(fn):
            return {"ok": False, "error": "unsupported"}
        out = fn(chat_id, images, caption=caption, reply_markup=reply_markup, **kw)
        if (out or {}).get("ok"):
            n = len(list(images or []))
            self._note(chat_id, f"〔已直接傳給使用者 {n} 張圖（使用者看得到）〕{plain(caption or '')[:300]}"
                       + _labels(reply_markup))
        return out

    def send_document(self, chat_id, document, caption=""):
        self._note(chat_id, f"〔已直接傳給使用者一個檔案〕{caption[:200]}")
        return self._real.send_document(chat_id, document, caption=caption)

    def send_media_group(self, chat_id, photo_paths, caption="", kind="photo"):
        self._note(chat_id, f"〔已直接傳給使用者 {len(photo_paths)} 個檔案〕{caption[:200]}")
        return self._real.send_media_group(chat_id, photo_paths, caption, kind)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def close(self) -> str:
        with self._lock:
            self._open = False
            return "\n".join(self._lines)


class CardRunApi(CaptureApi):
    """核准卡按 ✅ 之後執行用（規劃 11.10）：記下結果給 AI，但每一則都照常送給使用者。"""
    via_ai = False
    sync_result = True

    def send_message(self, chat_id, text, reply_markup=None, quiet=False, **kw):
        with self._lock:
            if self._open and chat_id == self._chat:
                self._lines.append(plain(text) if reply_markup is None else
                                   f"〔已直接傳給使用者一則帶按鈕的訊息〕{plain(text)[:300]}{_labels(reply_markup)}")
        return self._real.send_message(chat_id, text, reply_markup=reply_markup, quiet=quiet, **kw)

    def outcome(self, limit: int, secrets: Sequence[str] = ()) -> Tuple[bool, str]:
        """(成功?, 給 AI 的結果)。失敗信封＝固定格式的一行（health.failures.ai_line）；沒有輸出＝一句話。"""
        self.close()
        if self.failure is not None:
            from synox import health
            return False, health.failures.ai_line(self.failure)
        text = self.for_ai(limit, secrets)
        lines = self.receipt_lines()
        if lines:
            text = "\n".join(x for x in [text] + lines if x)
        return True, text or "（做完了，沒有輸出）"

