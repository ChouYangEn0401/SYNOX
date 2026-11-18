"""
電腦提醒視窗的畫面（tkinter）。邏輯全部在 logic.py、外觀（顏色、字型）在 style.py；這裡只畫卡片、把按鈕接到 DeskModel。

- 每張提醒一張圓角卡片：右下角、永遠在最上層、多張往上疊（高度照內容）、跳出來時響一聲。
- **不處理不會自己關**：沒有標題列的關閉鈕；只有按了按鈕、或在別處處理掉（close 檔）才關。
- 顏色跟著網頁的外觀（data/remind/desk/style.json；淺色／深色／跟著 Windows）；字型挑有中文字的（微軟正黑體…）。
- 版面：上面「⏰ 提醒」、大字的提醒內容、下面一行時間、晚了／延後的小標籤；主要的 [我知道了] [我完成了]；
  「稍後再叫我」5／15 分鐘、1 小時、自選；「安排到別天」明天同一時間、挑日期時間（只有一次性的提醒有）；最下面待辦。
- 鍵盤：每顆按鈕都能 Tab 到、Enter／空白鍵按；打字的格子 Enter 送出、Esc 收起來。
  **不搶焦點**：卡片跳出來時不拿鍵盤焦點（你正在打字的視窗不會被打斷）；點了卡片才是它的。
- 高 DPI：程式宣告 DPI aware（字不糊），像素尺寸照螢幕的縮放乘上去。
- 每 1 秒看一次 to_win；沒有卡 10 分鐘就自己結束（要跳時引擎會再開）。

tkinter 只在 run() 裡 import：import 這個模組不會開視窗（測試只做 import 與語法檢查）。
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from typing import Callable, Dict, List, Optional

from synox.notify import desk as deskmod
from synox.remindwin import logic, style

CARD_W = 380                      # 卡片寬（96 DPI 的像素；照縮放乘上去）
INSET = 18                        # 卡片內距
GAP = 10
TRANSPARENT = "#ff00fe"           # 卡片圓角外面的顏色（Windows 會把它變透明）
TODO_SHOW = 5


def _beep(root) -> None:
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        try:
            root.bell()
        except Exception:
            pass


def _dpi_aware() -> None:
    """字不要糊：宣告 DPI aware（Windows 8.1+ 用 shcore，舊的用 user32）。失敗就算了（照系統放大）。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def round_rect(canvas, x1, y1, x2, y2, r, **kw):
    """圓角矩形（smooth 的多邊形，角上的點重複一次＝圓角）。"""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2, x1, y2,
           x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


class Pill:
    """圓角按鈕（畫在自己的 Canvas 上）：滑過變色、按下、鍵盤焦點外框；Tab 到得了、Enter／空白鍵按。
    kind：primary（強調色實心）｜secondary（淺底＋框）｜chip（淡強調色）｜ghost（只有字）｜selected（選中的日子）。"""

    def __init__(self, tk, parent, text: str, command: Callable[[], None], *, colors: Dict[str, str], font, bg: str,
                 kind: str = "chip", scale: float = 1.0, padx: int = 14, pady: int = 7):
        self.tk, self.text, self.command, self.colors, self.font = tk, text, command, colors, font
        self.kind, self.scale, self.bg = kind, scale, bg
        self.hover = self.pressed = self.focused = False
        w = int(font.measure(text) + 2 * padx * scale)
        h = int(font.metrics("linespace") + 2 * pady * scale)
        self.w, self.h = w, h
        self.canvas = tk.Canvas(parent, width=w, height=h, bg=bg, highlightthickness=0, bd=0, takefocus=1,
                                cursor="hand2")
        c = self.canvas
        c.bind("<Enter>", lambda e: self._set(hover=True))
        c.bind("<Leave>", lambda e: self._set(hover=False, pressed=False))
        c.bind("<ButtonPress-1>", lambda e: (c.focus_set(), self._set(pressed=True)))
        c.bind("<ButtonRelease-1>", self._release)
        c.bind("<Return>", lambda e: self.invoke())
        c.bind("<space>", lambda e: self.invoke())
        c.bind("<FocusIn>", lambda e: self._set(focused=True))
        c.bind("<FocusOut>", lambda e: self._set(focused=False))
        self.draw()

    def _set(self, **kw) -> None:
        for k, v in kw.items():
            setattr(self, k, v)
        self.draw()

    def _release(self, event) -> None:
        inside = 0 <= event.x <= self.w and 0 <= event.y <= self.h
        self._set(pressed=False)
        if inside:
            self.invoke()

    def invoke(self) -> None:
        try:
            self.command()
        except Exception:
            logging.exception("[REMINDWIN] button failed")

    def set_kind(self, kind: str) -> None:
        self.kind = kind
        self.draw()

    def _fill(self):
        c = self.colors
        if self.kind == "primary":
            base, fg, line = c["accent"], c["accent-ink"], ""
            if self.hover:
                base = c["accent-hover"]
        elif self.kind == "selected":
            base, fg, line = c["accent"], c["accent-ink"], ""
        elif self.kind == "secondary":
            base, fg, line = c["surface-2"], c["text"], c["line-strong"]
            if self.hover:
                base = c["sunken"]
        elif self.kind == "ghost":
            base, fg, line = self.bg, c["text-2"], ""
            if self.hover:
                base = c["surface-2"]
        else:                                           # chip
            base, fg, line = c["soft"], c["text"], ""
            if self.hover:
                base = style.mix(c["soft"], c["accent"], 0.82)
        if self.pressed:
            base = style.mix(base, c["text"], 0.85)
        return base, fg, line

    def draw(self) -> None:
        c = self.canvas
        try:
            c.delete("all")
        except Exception:
            return
        base, fg, line = self._fill()
        inset = 1
        r = (self.h - 2 * inset) / 2
        if self.focused:                                # 鍵盤焦點：強調色外框
            round_rect(c, 0, 0, self.w, self.h, self.h / 2, fill=self.colors["accent"], outline="")
            inset = max(2, int(2 * self.scale))
            r = (self.h - 2 * inset) / 2
        round_rect(c, inset, inset, self.w - inset, self.h - inset, r, fill=base,
                   outline=line or base, width=1)
        c.create_text(self.w / 2, self.h / 2, text=self.text, fill=fg, font=self.font)

    def pack(self, **kw):
        self.canvas.pack(**kw)
        return self


class DeskWindow:

    def __init__(self, model: logic.DeskModel, data_dir: str = ""):
        self.model = model
        self.data_dir = data_dir
        self.tk = None
        self.root = None
        self.tops: Dict[str, object] = {}
        self._last_todos: list = []
        self.scale = 1.0
        self.look: Optional[style.Look] = None
        self.fonts: Dict[str, object] = {}

    # ── 主迴圈 ───────────────────────────────────────────────────────

    def run(self) -> None:
        import tkinter as tk
        _dpi_aware()
        self.tk = tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("SYNOX 提醒")
        try:
            self.scale = max(1.0, float(self.root.winfo_fpixels("1i")) / 96.0)
        except Exception:
            self.scale = 1.0
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
                for top in self.tops.values():
                    self._paint_todos(top)
                self._restack()
            if self.model.idle():
                self.root.destroy()
                return
        except Exception:
            logging.exception("[REMINDWIN] tick failed")
        self.root.after(int(deskmod.POLL_WIN_S * 1000), self.tick)

    # ── 外觀 ─────────────────────────────────────────────────────────

    def px(self, n: float) -> int:
        return int(round(n * self.scale))

    def _style(self) -> None:
        """每張卡跳出來時重讀一次外觀（網頁改了外觀，下一張就照新的）。"""
        import tkinter.font as tkfont
        try:
            self.look = style.load(self.data_dir) if self.data_dir else style.look({})
        except Exception:
            logging.exception("[REMINDWIN] style failed; using the original look")
            self.look = style.look({})
        try:
            family = style.pick_font(self.look.font_ui, tkfont.families(self.root))
        except Exception:
            family = style.DEFAULT_FONTS[0]
        mk = lambda size, weight="normal": tkfont.Font(root=self.root, family=family, size=size, weight=weight)
        self.fonts = {"title": mk(14, "bold"), "body": mk(10), "button": mk(10, "bold"), "chip": mk(10),
                      "small": mk(9), "label": mk(9, "bold"), "brand": mk(8, "bold")}

    # ── 一張卡 ───────────────────────────────────────────────────────

    def _open(self, card: deskmod.ShowCard, *, ring: bool) -> None:
        tk = self.tk
        self._style()
        c, f = self.look.colors, self.fonts
        surface = c["surface"]
        top = tk.Toplevel(self.root)
        top.overrideredirect(True)                      # 沒有標題列＝沒有 ✕：不處理不會關
        top.attributes("-topmost", True)
        top.protocol("WM_DELETE_WINDOW", lambda: None)
        rounded = True
        try:
            top.configure(bg=TRANSPARENT)
            top.attributes("-transparentcolor", TRANSPARENT)
        except Exception:                               # 不支援透明色（不是 Windows）：方角
            rounded = False
            top.configure(bg=surface)
        canvas = tk.Canvas(top, bg=TRANSPARENT if rounded else surface, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        body = tk.Frame(canvas, bg=surface)
        inset = self.px(INSET)
        inner_w = self.px(CARD_W) - 2 * inset
        top.card = card
        top.canvas, top.body, top.inset, top.rounded = canvas, body, inset, rounded
        top.panels = {}

        # 上面一行：⏰ 提醒                                   SYNOX
        head = tk.Frame(body, bg=surface)
        head.pack(fill="x")
        tk.Label(head, text=logic.T["title"], bg=surface, fg=c["accent"], font=f["label"]).pack(side="left")
        tk.Label(head, text=logic.T["brand"], bg=surface, fg=c["line-strong"], font=f["brand"]).pack(side="right")

        # 提醒的字（大）、下面一行時間（小、灰）
        title, _sub = logic.card_lines(card)
        tk.Label(body, text=title, bg=surface, fg=c["text"], font=f["title"], anchor="w", justify="left",
                 wraplength=inner_w).pack(fill="x", pady=(self.px(8), 0))
        if card.when:
            tk.Label(body, text=card.when, bg=surface, fg=c["muted"], font=f["body"], anchor="w").pack(
                fill="x", pady=(self.px(2), 0))

        # 晚了幾分鐘、延後第幾次：小標籤
        tags = []
        if card.late_min > 0:
            tags.append(logic.T["late"].format(n=card.late_min))
        if card.snooze_count > 0:
            tags.append(logic.T["snoozed"].format(n=card.snooze_count))
        if tags:
            row = tk.Frame(body, bg=surface)
            row.pack(fill="x", pady=(self.px(6), 0))
            for text in tags:
                tk.Label(row, text=text, bg=c["warn-soft"], fg=c["warn"], font=f["small"], padx=self.px(8),
                         pady=self.px(2)).pack(side="left", padx=(0, self.px(6)))

        status = tk.Label(body, text="", bg=surface, fg=c["muted"], font=f["small"], anchor="w", justify="left",
                          wraplength=inner_w)
        top.status = status
        buttons = list(card.buttons)

        def pill(parent, button, kind="chip", text=None, command=None, **kw):
            label = text or logic.LABELS.get(button, "")
            cmd = command or (lambda b=button: self._press(card.token, b))
            return Pill(tk, parent, label, cmd, colors=c, font=f["button"] if kind in ("primary", "secondary")
                        else f["chip"], bg=surface, kind=kind, scale=self.scale, **kw)

        # 主要：[我知道了] [我完成了]（完成＝強調色實心）
        main = [b for b in (deskmod.BTN_ACK, deskmod.BTN_DONE) if b in buttons]
        if main:
            row = tk.Frame(body, bg=surface)
            row.pack(fill="x", pady=(self.px(14), 0))
            for b in main:
                pill(row, b, "primary" if b == deskmod.BTN_DONE else "secondary", padx=18, pady=8).pack(
                    side="left", padx=(0, self.px(8)))

        later = [b for b in buttons if b in logic.PRESET_MIN or b == deskmod.BTN_SNOOZE_TYPED]
        move = [b for b in buttons if b in (deskmod.BTN_RESCHEDULE_TOMORROW, deskmod.BTN_RESCHEDULE_PICK)]
        if later or move:
            tk.Frame(body, bg=c["line"], height=1).pack(fill="x", pady=(self.px(14), self.px(10)))
        if later:
            self._section(body, logic.T["snooze_head"])
            row = tk.Frame(body, bg=surface)
            row.pack(fill="x", pady=(self.px(4), 0))
            for b in later:
                if b == deskmod.BTN_SNOOZE_TYPED:
                    pill(row, b, command=lambda t=top: self._toggle(t, "typed")).pack(side="left", padx=(0, self.px(6)))
                else:
                    pill(row, b).pack(side="left", padx=(0, self.px(6)))
            top.panels["typed"] = self._typed_panel(top, body, inner_w)
        if move:
            self._section(body, logic.T["move_head"], top_pad=10)
            row = tk.Frame(body, bg=surface)
            row.pack(fill="x", pady=(self.px(4), 0))
            for b in move:
                if b == deskmod.BTN_RESCHEDULE_PICK:
                    pill(row, b, command=lambda t=top: self._toggle(t, "pick")).pack(side="left", padx=(0, self.px(6)))
                else:
                    pill(row, b).pack(side="left", padx=(0, self.px(6)))
            top.panels["pick"] = self._pick_panel(top, body, card)
        # 錯過的、其他沒排進去的鍵（舊的卡片）：照樣給
        rest = [b for b in buttons if b not in main + later + move and logic.LABELS.get(b)]
        if rest:
            row = tk.Frame(body, bg=surface)
            row.pack(fill="x", pady=(self.px(8), 0))
            for b in rest:
                pill(row, b).pack(side="left", padx=(0, self.px(6)))

        spot = tk.Frame(body, bg=surface, height=1)    # 「自選」「挑日子」那一塊、錯誤訊息插在這裡之前
        spot.pack(fill="x")
        top.status_spot = spot
        todo_box = tk.Frame(body, bg=surface)
        todo_box.pack(fill="x")
        top.todo_box = todo_box
        self._paint_todos(top, layout=False)

        canvas.create_window(inset, inset, window=body, anchor="nw", width=inner_w)
        self.tops[card.token] = top
        self._layout(top)
        if ring:
            _beep(self.root)
            self.model.shown(card.token)

    def _section(self, body, text: str, top_pad: int = 0) -> None:
        c = self.look.colors
        self.tk.Label(body, text=text, bg=c["surface"], fg=c["muted"], font=self.fonts["label"], anchor="w").pack(
            fill="x", pady=(self.px(top_pad), 0))

    def _entry(self, parent, width: int):
        c = self.look.colors
        return self.tk.Entry(parent, width=width, font=self.fonts["body"], relief="flat", bd=0, bg=c["sunken"],
                             fg=c["text"], insertbackground=c["text"], highlightthickness=1,
                             highlightbackground=c["line-strong"], highlightcolor=c["accent"])

    def _typed_panel(self, top, body, inner_w: int):
        """自選：打幾分鐘或時間。"""
        tk, c = self.tk, self.look.colors
        panel = tk.Frame(body, bg=c["surface"])
        row = tk.Frame(panel, bg=c["surface"])
        row.pack(fill="x", pady=(self.px(8), 0))
        entry = self._entry(row, 14)
        entry.pack(side="left", fill="x", expand=True, ipady=self.px(5))
        send = lambda t=top, e=entry: self._press(t.card.token, deskmod.BTN_SNOOZE_TYPED, e.get())
        Pill(tk, row, logic.T["typed_ok"], send, colors=c, font=self.fonts["button"], bg=c["surface"], kind="primary",
             scale=self.scale).pack(side="left", padx=(self.px(8), 0))
        entry.bind("<Return>", lambda e: send())
        entry.bind("<Escape>", lambda e, t=top: self._toggle(t, "typed"))
        tk.Label(panel, text=logic.T["typed_hint"], bg=c["surface"], fg=c["muted"], font=self.fonts["small"],
                 anchor="w", justify="left", wraplength=inner_w).pack(fill="x", pady=(self.px(4), 0))
        panel.entry = entry
        return panel

    def _pick_panel(self, top, body, card):
        """挑日子：明天起 7 天的日子（點一個）＋幾點（預設原本的時間）。"""
        tk, c = self.tk, self.look.colors
        panel = tk.Frame(body, bg=c["surface"])
        days = logic.day_choices(datetime.now())
        chosen = {"day": days[0][0]}
        pills: List[Pill] = []

        def choose(day, me):
            chosen["day"] = day
            for p in pills:
                p.set_kind("selected" if p is me else "chip")

        for start in range(0, len(days), 4):
            row = tk.Frame(panel, bg=c["surface"])
            row.pack(fill="x", pady=(self.px(8 if start == 0 else 6), 0))
            for day, label in days[start:start + 4]:
                p = Pill(tk, row, label, lambda: None, colors=c, font=self.fonts["chip"], bg=c["surface"],
                         kind="selected" if day == chosen["day"] else "chip", scale=self.scale, padx=10, pady=5)
                p.command = (lambda d=day, me=p: choose(d, me))
                p.pack(side="left", padx=(0, self.px(6)))
                pills.append(p)
        row = tk.Frame(panel, bg=c["surface"])
        row.pack(fill="x", pady=(self.px(8), 0))
        entry = self._entry(row, 10)
        try:
            occ = datetime.fromisoformat(card.occurrence)
            entry.insert(0, (occ.astimezone() if occ.tzinfo else occ).strftime("%H:%M"))
        except (TypeError, ValueError):
            pass
        entry.pack(side="left", ipady=self.px(5))
        send = lambda t=top, e=entry: self._press(t.card.token, deskmod.BTN_RESCHEDULE_PICK,
                                                  at=logic.pick_at(chosen["day"], e.get()))
        Pill(tk, row, logic.T["pick_ok"], send, colors=c, font=self.fonts["button"], bg=c["surface"], kind="primary",
             scale=self.scale).pack(side="left", padx=(self.px(8), 0))
        entry.bind("<Return>", lambda e: send())
        entry.bind("<Escape>", lambda e, t=top: self._toggle(t, "pick"))
        tk.Label(panel, text=logic.T["pick_hint"], bg=c["surface"], fg=c["muted"], font=self.fonts["small"],
                 anchor="w").pack(fill="x", pady=(self.px(4), 0))
        panel.entry = entry
        return panel

    def _toggle(self, top, name: str) -> None:
        """打開／收起「自選」「挑日子」那一塊（同時只開一塊）；打開時焦點給打字的格子（是你點的，不算搶）。"""
        for other, panel in top.panels.items():
            if other != name and panel.winfo_manager():
                panel.pack_forget()
        panel = top.panels.get(name)
        if panel is None:
            return
        if panel.winfo_manager():
            panel.pack_forget()
        else:
            panel.pack(fill="x", before=top.status_spot)
            try:
                top.focus_force()
                panel.entry.focus_set()
            except Exception:
                pass
        self._say(top, "")
        self._layout(top)
        self._restack()

    def _say(self, top, message: str) -> None:
        """卡片上的一行字（看不懂的時間等）；沒有字就收起來（不留空白）。"""
        status = top.status
        if message:
            status.configure(text=message, fg=self.look.colors["bad"])
            if not status.winfo_manager():
                status.pack(fill="x", pady=(self.px(6), 0), before=top.status_spot)
        else:
            status.configure(text="")
            status.pack_forget()

    def _paint_todos(self, top, layout: bool = True) -> None:
        tk = self.tk
        box = top.todo_box
        c, f = self.look.colors if self.look else style.look({}).colors, self.fonts
        for child in list(box.winfo_children()):
            child.destroy()
        if self.model.todos:
            tk.Frame(box, bg=c["line"], height=1).pack(fill="x", pady=(self.px(12), self.px(8)))
            tk.Label(box, text=logic.T["todos"], bg=c["surface"], fg=c["muted"], font=f["label"], anchor="w").pack(
                fill="x")
            for item in self.model.todos[:TODO_SHOW]:
                line = tk.Frame(box, bg=c["surface"])
                line.pack(fill="x", pady=(self.px(4), 0))
                Pill(tk, line, logic.T["todo_done"], lambda u=item["uid"], r=item["rid"]: self._todo(u, r), colors=c,
                     font=f["small"], bg=c["surface"], kind="chip", scale=self.scale, padx=8, pady=2).pack(side="left")
                tk.Label(line, text=item["text"], bg=c["surface"], fg=c["text"], font=f["body"], anchor="w").pack(
                    side="left", padx=self.px(8))
        if layout:
            self._layout(top)

    def _layout(self, top) -> None:
        """照內容量高度、畫圓角底。"""
        try:
            top.body.update_idletasks()
            w = self.px(CARD_W)
            h = top.body.winfo_reqheight() + 2 * top.inset
            canvas = top.canvas
            canvas.configure(width=w, height=h)
            canvas.delete("card")
            c = self.look.colors
            r = self.px(self.look.radius * 1.4) if top.rounded else 0
            item = round_rect(canvas, 0, 0, w - 1, h - 1, r, fill=c["surface"], outline=c["line-strong"], width=1,
                              tags="card")
            canvas.tag_lower(item)
            top.size = (w, h)
        except Exception:
            logging.exception("[REMINDWIN] layout failed")

    def _press(self, token: str, button: str, typed: str = "", at=None) -> None:
        ok, message = self.model.act(token, button, typed, at=at)
        if not ok:
            top = self.tops.get(token)
            if top is not None and message:
                self._say(top, message)
                self._layout(top)
                self._restack()
            return
        self._close(token)
        self._restack()

    def _todo(self, uid: int, rid: int) -> None:
        self.model.todo_done(uid, rid)
        for top in self.tops.values():
            self._paint_todos(top)
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
        heights = [getattr(self.tops[c.token], "size", (0, self.px(200)))[1] for c in cards]
        spots = logic.stack_heights(heights, sw, sh, self.px(CARD_W), margin=self.px(12), bottom=self.px(56))
        for card, (x, y) in zip(cards, spots):
            top = self.tops[card.token]
            w, h = getattr(top, "size", (self.px(CARD_W), self.px(200)))
            top.geometry(f"{w}x{h}+{x}+{y}")


def run(data_dir: str, *, demo: bool = False) -> int:
    """視窗程式本體：popup.lock 拿不到（已經有一個在跑）就直接結束。"""
    lock = deskmod.popup_lock_at(data_dir)
    if not lock.try_acquire():
        return 0
    try:
        DeskWindow(logic.DeskModel(deskmod.spool_at(data_dir), demo=demo), data_dir).run()
    finally:
        lock.release()
    return 0


__all__ = ["DeskWindow", "Pill", "run"]
