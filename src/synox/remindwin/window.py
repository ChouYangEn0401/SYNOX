"""
電腦提醒視窗的畫面（tkinter）。邏輯全部在 logic.py；這裡只畫卡片、把按鈕接到 DeskModel。

- 每張提醒一個小視窗：右下角、永遠在最上層、多張往上疊、跳出來時響一聲。
- **不處理不會自己關**：沒有標題列的關閉鈕；只有按了「完成／延後」、或在別處處理掉（close 檔）才關。
- 下半部列待辦（每筆一個 ✓）。
- 每 1 秒看一次 to_win；沒有卡 10 分鐘就自己結束（要跳時引擎會再開）。

tkinter 只在 run() 裡 import：import 這個模組不會開視窗（測試只做 import 與語法檢查）。
"""

from __future__ import annotations

import logging
from typing import Dict

from synox.notify import desk as deskmod
from synox.remindwin import logic

CARD_W, CARD_H = 360, 190
BG, FG, MUTED, ACCENT = "#fffbe6", "#1f1f1f", "#6b6b6b", "#c2410c"


def _beep(root) -> None:
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        try:
            root.bell()
        except Exception:
            pass


class DeskWindow:

    def __init__(self, model: logic.DeskModel):
        self.model = model
        self.tk = None
        self.root = None
        self.tops: Dict[str, object] = {}
        self._last_todos: list = []

    # ── 主迴圈 ───────────────────────────────────────────────────────

    def run(self) -> None:
        import tkinter as tk
        self.tk = tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("SYNOX 提醒")
        self.root.after(0, self.tick)
        self.root.mainloop()

    def tick(self) -> None:
        try:
            changes = self.model.poll()
            for token, _note in changes.closed:
                self._close(token)
            for card in changes.updated:
                self._close(card.token)
                self._open(card, ring=False)
            for card in changes.new:
                self._open(card, ring=True)
            if changes.any or changes.todos != self._last_todos:
                self._last_todos = list(changes.todos)
                self._restack()
            if self.model.idle():
                self.root.destroy()
                return
        except Exception:
            logging.exception("[REMINDWIN] tick failed")
        self.root.after(int(deskmod.POLL_WIN_S * 1000), self.tick)

    # ── 一張卡 ───────────────────────────────────────────────────────

    def _open(self, card: deskmod.ShowCard, *, ring: bool) -> None:
        tk = self.tk
        top = tk.Toplevel(self.root)
        top.overrideredirect(True)                      # 沒有標題列＝沒有 ✕：不處理不會關
        top.attributes("-topmost", True)
        top.configure(bg=BG, highlightthickness=1, highlightbackground=ACCENT)
        top.protocol("WM_DELETE_WINDOW", lambda: None)
        title, sub = logic.card_lines(card)
        tk.Label(top, text=logic.T["title"], bg=BG, fg=ACCENT, font=("Microsoft JhengHei UI", 9, "bold"),
                 anchor="w").pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(top, text=title, bg=BG, fg=FG, font=("Microsoft JhengHei UI", 12, "bold"), anchor="w",
                 justify="left", wraplength=CARD_W - 24).pack(fill="x", padx=10)
        if sub:
            tk.Label(top, text=sub, bg=BG, fg=MUTED, font=("Microsoft JhengHei UI", 9), anchor="w").pack(fill="x", padx=10)
        row = tk.Frame(top, bg=BG)
        row.pack(fill="x", padx=8, pady=6)
        typed_row = tk.Frame(top, bg=BG)
        status = tk.Label(top, text="", bg=BG, fg=MUTED, font=("Microsoft JhengHei UI", 9), anchor="w")
        for button in card.buttons:
            label = logic.LABELS.get(button)
            if not label:
                continue
            if button == deskmod.BTN_SNOOZE_TYPED:
                cmd = (lambda tr=typed_row: tr.pack(fill="x", padx=10, pady=(0, 4)))
            else:
                cmd = (lambda b=button, t=card.token: self._press(t, b))
            tk.Button(row, text=label, command=cmd).pack(side="left", padx=2)
        entry = tk.Entry(typed_row)
        entry.pack(side="left", fill="x", expand=True)
        tk.Button(typed_row, text=logic.T["typed_ok"],
                  command=lambda t=card.token, e=entry, s=status: self._press(t, deskmod.BTN_SNOOZE_TYPED, e.get(), s)
                  ).pack(side="left", padx=4)
        tk.Label(typed_row, text=logic.T["typed_hint"], bg=BG, fg=MUTED, font=("Microsoft JhengHei UI", 8)).pack(side="left")
        status.pack(fill="x", padx=10)
        todo_box = tk.Frame(top, bg=BG)
        todo_box.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self._paint_todos(todo_box)
        top.todo_box = todo_box
        self.tops[card.token] = top
        if ring:
            _beep(self.root)
            self.model.shown(card.token)

    def _paint_todos(self, box) -> None:
        tk = self.tk
        for child in list(box.winfo_children()):
            child.destroy()
        if not self.model.todos:
            return
        tk.Label(box, text=logic.T["todos"], bg=BG, fg=MUTED, font=("Microsoft JhengHei UI", 9, "bold"),
                 anchor="w").pack(fill="x")
        for item in self.model.todos[:5]:
            line = tk.Frame(box, bg=BG)
            line.pack(fill="x")
            tk.Button(line, text=logic.T["todo_done"], width=2,
                      command=lambda u=item["uid"], r=item["rid"]: self._todo(u, r)).pack(side="left")
            tk.Label(line, text=item["text"], bg=BG, fg=FG, anchor="w").pack(side="left", padx=4)

    def _press(self, token: str, button: str, typed: str = "", status=None) -> None:
        ok, message = self.model.act(token, button, typed)
        if not ok:
            if status is not None and message:
                status.configure(text=message)
            return
        self._close(token)
        self._restack()

    def _todo(self, uid: int, rid: int) -> None:
        self.model.todo_done(uid, rid)
        self._restack()

    def _close(self, token: str) -> None:
        top = self.tops.pop(token, None)
        if top is not None:
            try:
                top.destroy()
            except Exception:
                pass

    def _restack(self) -> None:
        if self.root is None:
            return
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        cards = [c for c in self.model.ordered() if c.token in self.tops]
        for card, (x, y) in zip(cards, logic.stack_positions(len(cards), sw, sh, CARD_W, CARD_H)):
            top = self.tops[card.token]
            top.geometry(f"{CARD_W}x{CARD_H}+{x}+{y}")
            self._paint_todos(top.todo_box)


def run(data_dir: str, *, demo: bool = False) -> int:
    """視窗程式本體：popup.lock 拿不到（已經有一個在跑）就直接結束。"""
    lock = deskmod.popup_lock_at(data_dir)
    if not lock.try_acquire():
        return 0
    try:
        DeskWindow(logic.DeskModel(deskmod.spool_at(data_dir), demo=demo)).run()
    finally:
        lock.release()
    return 0


__all__ = ["DeskWindow", "run"]
