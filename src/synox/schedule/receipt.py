"""
排程回執（契約，docs/adr/0029 §3.2）：一個「之後會發生的事」真的排上了，指令回給使用者與 AI 的固定內容。

    ⏰ 排好了：今天 00:51 提醒你「倒垃圾」（只一次）。
    會送到：Telegram、這台電腦的視窗。
    不會響的情況：電腦關機或睡著時（開機後補送）。

- **只有排上了才產生回執**；擋下來（時間已過、格式錯、沒有任何管道）不給回執，回的是錯誤或要問的那一句。
- 回覆的字由 reply_text() 產生，不交給 AI 自由發揮；AI 轉述時照回執講（W4 的承諾把關看這裡）。
- emit()：送出回覆的字，並在 api 有 note_receipt（W4 在 agent/capture.py 加）時把回執本身交過去——
  這樣 AI 的工具結果裡有結構化的回執，承諾檢查不用從人看的字反推。

欄位、代號是契約：W1 產生、W4 檢查；改欄位要改 ADR 0029。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional

VERSION = 1
MARK = "〔排程回執〕"            # machine_line() 的開頭：只有系統會產生（W4 可以拿來辨認、也要防 AI 偽造）

# 回執的種類
REMIND, TODO, COMMAND = "remind", "todo", "command"
KINDS = (REMIND, TODO, COMMAND)

# 「什麼情況不會送」的代號 → 白話（W1 依實際狀況挑；順序照這裡）
NOT_WHEN = {
    "off": "電腦關機時",
    "asleep": "電腦睡著時",
    "app_closed": "SYNOX 沒開時",                  # 沒有提醒哨兵才會出現
    "web_only": "網頁沒開著時（只會在網頁上叫你）",
    "no_channel": "現在沒有任何地方可以叫你",         # 有這個代號＝其實不該給回執（W1 應先擋下）
}

CATCH_UP_TEXT = {
    "boot": "開機後補送",
    "next_start": "下次打開 SYNOX 時補送",
}

REPEAT_TEXT = {"once": "只一次", "daily": "每天", "none": "沒有時間"}


@dataclass
class ScheduleReceipt:
    """一張回執。to_dict()／from_dict() 來回不失真。"""

    kind: str                                  # remind｜todo｜command
    id: int                                    # 在那個人的清單裡的 id
    text: str                                  # 提醒什麼（command 時是指令字串）
    repeat: str                                # once｜daily｜none
    due: Optional[str] = None                  # 第一次到點的絕對時間（ISO，帶時區）；待辦＝None
    when: str = ""                             # 白話的時間：「今天 00:51」「明天 08:00」（notify.alarms.friendly）
    channels: List[str] = field(default_factory=list)          # 會送的管道 id（web／telegram／discord／desktop）
    channel_labels: List[str] = field(default_factory=list)    # 白話：「Telegram」「這台電腦的視窗」
    not_when: List[str] = field(default_factory=list)          # NOT_WHEN 的代號
    catch_up: str = "boot"                     # CATCH_UP_TEXT 的代號：沒響到的怎麼補
    ring_late_max_min: int = 60                # 晚多久內照常響（照 reminder.RING_LATE_MAX_MIN）
    missed_notice_max_h: int = 6               # 晚多久內一則一則說錯過（照 reminder.MISSED_NOTICE_MAX_H）
    warnings: List[str] = field(default_factory=list)          # notify.alarms.warnings 的 id（web_only、sleep…）
    ok: bool = True
    v: int = VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScheduleReceipt":
        names = {f.name for f in fields(cls)}
        rec = cls(**{k: v for k, v in data.items() if k in names})
        if rec.kind not in KINDS:
            raise ValueError(f"receipt kind 不認得：{rec.kind!r}")
        if rec.kind != TODO and not rec.due:
            raise ValueError("有時間的回執一定要有 due")
        return rec

    # ── 給人看的字 ───────────────────────────────────────────────────

    def reply_text(self) -> str:
        """回給使用者的固定三行（待辦只有一行）。AI 轉述要照這個講。"""
        if self.kind == TODO:
            return f"📝 記下了待辦：「{self.text}」（沒有時間，不會響；在提醒清單與電腦視窗的下半部看得到）。"
        if self.kind == COMMAND:
            head = f"🗓 排好了：{self.when} 替你執行 {self.text}（{REPEAT_TEXT.get(self.repeat, self.repeat)}）。"
        else:
            head = f"⏰ 排好了：{self.when} 提醒你「{self.text}」（{REPEAT_TEXT.get(self.repeat, self.repeat)}）。"
        lines = [head]
        if self.channel_labels:
            lines.append("會送到：" + "、".join(self.channel_labels) + "。")
        nots = [NOT_WHEN[c] for c in self.not_when if c in NOT_WHEN]
        if nots:
            lines.append("不會響的情況：" + "、".join(nots) + f"（{CATCH_UP_TEXT.get(self.catch_up, '')}）。")
        return "\n".join(lines)

    def machine_line(self) -> str:
        """一行給 AI 的結構化摘要（W4 決定要不要放進工具結果）：〔排程回執〕due=…；channels=…；not_when=…"""
        return (f"{MARK}kind={self.kind}；id={self.id}；due={self.due or '-'}；repeat={self.repeat}；"
                f"channels={','.join(self.channels) or '-'}；not_when={','.join(self.not_when) or '-'}")


def emit(api, chat_id: int, receipt: ScheduleReceipt, *, extra: str = "") -> None:
    """送出回執：人看的字照常 send_message；api 有 note_receipt（AI 呼叫時的 CaptureApi）就把回執也交過去。"""
    note = getattr(api, "note_receipt", None)
    if callable(note):
        note(receipt)
    api.send_message(chat_id, receipt.reply_text() + (("\n" + extra) if extra else ""))


__all__ = ["CATCH_UP_TEXT", "COMMAND", "KINDS", "MARK", "NOT_WHEN", "REMIND", "REPEAT_TEXT", "ScheduleReceipt", "TODO",
           "VERSION", "emit"]
