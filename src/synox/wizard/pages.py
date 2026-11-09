"""
安裝精靈（tkinter，stdlib，不開埠）：四頁＋完成頁。

  1. 這台給誰用？○ 只有我（個人版）○ 一群人（伺服器版）；底下一行「工程師？直接改 config.json」
  2. Telegram bot 的 token：「怎麼拿」三步 → 貼上 → getMe 驗證 →「✅ 這支 bot 叫 @xxx」
  3. 你是誰：六位數配對碼＋「打開 t.me/<bot>」→ 背景 getUpdates 等那則訊息 → 記下 owner_id
  4. AI：上面是預設「Claude（這台電腦登入的 Claude Code）」＋狀態＋測一下；下面「其他金鑰來源」
     （OpenAI／Anthropic API／Gemini／相容端點：下拉選單、網址（只有相容端點）、金鑰、模型、測一下）；「先不用 AI」
  5. 完成：桌面捷徑（預設勾）、開機自動啟動（預設不勾）→「完成並開始」寫 config.json、開 Start.bat

網路呼叫都在背景執行緒，結果用 root.after 交回畫面執行緒。畫面以外的邏輯在 logic.py／telegram_probe.py／
shortcuts.py（有單元測試）；這個檔案只有畫面。
"""

from __future__ import annotations

import os
import subprocess
import threading
import webbrowser

from synox.config import CONFIG_PATH, ROOT
from synox.wizard import logic, shortcuts, telegram_probe

TITLE = "SYNOX 安裝精靈"
STEPS = 4
HOW_TO_TOKEN = ("怎麼拿 token（三步）：\n"
                "  1. 在 Telegram 搜尋 @BotFather，打開它\n"
                "  2. 傳 /newbot，照它問的取一個名字和帳號（帳號要以 bot 結尾）\n"
                "  3. 它會回一串像 123456789:AAH… 的字，整串複製，貼到下面")


class Wizard:

    def __init__(self, root, config_path: str = CONFIG_PATH):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.root = root
        self.config_path = config_path
        self.existing = logic.read_existing(config_path)
        self.mode = self.existing.get("mode") if self.existing.get("mode") in logic.MODE_CHOICES else "personal"
        self.token = ""
        self.bot_name = ""
        self.owner = None
        self.llm = {"kind": "none"}
        self.stop = threading.Event()
        root.title(TITLE)
        root.geometry("640x580")
        root.minsize(580, 520)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.body = ttk.Frame(root, padding=18)
        self.body.pack(fill="both", expand=True)
        self.nav = ttk.Frame(root, padding=(18, 0, 18, 14))
        self.nav.pack(fill="x")
        self.next_btn = ttk.Button(self.nav, text="下一步 ▶", command=lambda: None, state="disabled")
        self.next_btn.pack(side="right")
        self.page_mode()

    # ── 小工具 ───────────────────────────────────────────────────────

    def clear(self, title: str, step: str):
        for w in self.body.winfo_children():
            w.destroy()
        self.ttk.Label(self.body, text=step, foreground="#666").pack(anchor="w")
        self.ttk.Label(self.body, text=title, font=("Microsoft JhengHei UI", 15, "bold")).pack(anchor="w", pady=(2, 10))

    def label(self, text: str, parent=None, **kw):
        lbl = self.ttk.Label(parent or self.body, text=text, wraplength=580, justify="left", **kw)
        lbl.pack(anchor="w", pady=4)
        return lbl

    def later(self, fn, *args):
        """背景執行緒 → 畫面執行緒。"""
        self.root.after(0, lambda: fn(*args))

    def background(self, work, done):
        threading.Thread(target=lambda: self.later(done, work()), daemon=True).start()

    def set_next(self, text: str, command, enabled: bool = True):
        self.next_btn.configure(text=text, command=command, state="normal" if enabled else "disabled")

    def close(self):
        self.stop.set()
        self.root.destroy()

    # ── 1. 這台給誰用 ────────────────────────────────────────────────

    def page_mode(self):
        self.clear("這台給誰用？", f"第 1 步，共 {STEPS} 步")
        tk, ttk = self.tk, self.ttk
        choice = tk.StringVar(value=self.mode)
        for value in logic.MODE_CHOICES:
            title, one, two = logic.mode_lines(value)
            ttk.Radiobutton(self.body, text=title, value=value, variable=choice).pack(anchor="w", pady=(10, 0))
            ttk.Label(self.body, text=f"{one}\n{two}", wraplength=540, justify="left",
                      foreground="#444").pack(anchor="w", padx=(26, 0))
        ttk.Separator(self.body).pack(fill="x", pady=14)
        self.label(logic.ENGINEER_HINT, foreground="#666")

        def go():
            self.mode = choice.get()
            self.page_token()

        self.set_next("下一步 ▶", go)

    # ── 2. token ─────────────────────────────────────────────────────

    def page_token(self):
        self.clear("Telegram bot 的 token", f"第 2 步，共 {STEPS} 步")
        self.label(HOW_TO_TOKEN)
        var = self.tk.StringVar(value=self.existing.get("bot_token", ""))
        entry = self.ttk.Entry(self.body, textvariable=var, width=60)
        entry.pack(anchor="w", pady=6, fill="x")
        entry.focus_set()
        status = self.label("")
        self.set_next("下一步 ▶", self.page_pair, enabled=False)

        def check():
            token = var.get().strip()
            if not telegram_probe.valid_token(token):
                status.configure(text="❌ 這看起來不是 token（長得像 123456789:AAH…，中間有冒號）。")
                return
            status.configure(text="⏳ 跟 Telegram 確認中…")

            def done(result):
                ok, info = result
                if ok:
                    self.token, self.bot_name = token, info
                    status.configure(text=f"✅ 這支 bot 叫 @{info}")
                    self.set_next("下一步 ▶", self.page_pair)
                else:
                    status.configure(text=f"❌ {info}")

            self.background(lambda: telegram_probe.get_me(token), done)

        self.ttk.Button(self.body, text="檢查 token", command=check).pack(anchor="w")
        entry.bind("<Return>", lambda _e: check())

    # ── 3. 配對 ──────────────────────────────────────────────────────

    def page_pair(self):
        self.clear("你是誰", f"第 3 步，共 {STEPS} 步")
        code = telegram_probe.new_pairing_code()
        self.label(f"打開你的 bot @{self.bot_name}，傳這六個數字給它（按下面的按鈕就會打開）：")
        self.ttk.Label(self.body, text=" ".join(code), font=("Consolas", 30, "bold")).pack(anchor="w", pady=10)
        self.ttk.Button(self.body, text=f"打開 t.me/{self.bot_name}",
                        command=lambda: webbrowser.open(f"https://t.me/{self.bot_name}")).pack(anchor="w")
        status = self.label("⏳ 等你傳過來…（不用再問 @userinfobot）")
        self.set_next("下一步 ▶", self.page_llm, enabled=False)
        self.stop.clear()

        def done(who):
            if who is None:
                if not self.stop.is_set():
                    status.configure(text="⌛ 等太久了。關掉精靈，晚點再雙擊 Setup.bat 重來。")
                return
            self.owner = who
            name = f"@{who['username']}" if who.get("username") else who.get("first_name", "")
            status.configure(text=f"✅ 認得你了：{name}（id {who['id']}）")
            self.set_next("下一步 ▶", self.page_llm)

        token = self.token
        self.background(lambda: telegram_probe.wait_for_code(token, code, stop=self.stop), done)

    # ── 4. AI ────────────────────────────────────────────────────────

    def page_llm(self):
        self.stop.set()
        self.clear("AI 從哪裡來", f"第 4 步，共 {STEPS} 步")
        tk, ttk = self.tk, self.ttk
        found, claude_text = logic.claude_status()
        choice = tk.StringVar(value=logic.default_choice(found))
        v = {k: tk.StringVar() for k in ("base_url", "api_key", "model")}
        provider = tk.StringVar(value=logic.provider_labels()[0])
        v["model"].set(logic.default_model("openai"))

        # 上：預設 Claude（這台電腦登入的 Claude Code）
        top = ttk.LabelFrame(self.body, text="預設", padding=10)
        top.pack(fill="x")
        ttk.Radiobutton(top, text=logic.CLAUDE_TITLE, value="claude_code", variable=choice,
                        command=lambda: changed()).pack(anchor="w")
        self.label(claude_text, parent=top, foreground="#2a6" if found else "#a33")
        claude_status = self.label("", parent=top)
        ttk.Button(top, text="測一下", command=lambda: test("claude_code", claude_status)).pack(anchor="w")

        # 下：其他金鑰來源
        bottom = ttk.LabelFrame(self.body, text="其他金鑰來源", padding=10)
        bottom.pack(fill="x", pady=(10, 0))
        ttk.Radiobutton(bottom, text="用我自己（或公司）的金鑰", value="keys", variable=choice,
                        command=lambda: changed()).pack(anchor="w")
        form = ttk.Frame(bottom)
        form.pack(fill="x", pady=4)

        def row(parent, label, var, secret=False):
            f = ttk.Frame(parent)
            f.pack(fill="x", pady=2)
            ttk.Label(f, text=label, width=12).pack(side="left")
            ttk.Entry(f, textvariable=var, show="•" if secret else "").pack(side="left", fill="x", expand=True)
            return f

        f = ttk.Frame(form)
        f.pack(fill="x", pady=2)
        ttk.Label(f, text="哪一家", width=12).pack(side="left")
        combo = ttk.Combobox(f, textvariable=provider, values=logic.provider_labels(), state="readonly")
        combo.pack(side="left", fill="x", expand=True)
        url_holder = ttk.Frame(form)              # 只有相容端點時才把「網址」那一列放進來
        url_holder.pack(fill="x")
        row_url = row(url_holder, "網址", v["base_url"])
        row_url.pack_forget()
        row(form, "API key", v["api_key"], secret=True)
        row(form, "模型", v["model"])
        keys_status = self.label("", parent=bottom)
        ttk.Button(bottom, text="測一下", command=lambda: test("keys", keys_status)).pack(anchor="w")

        ttk.Radiobutton(self.body, text="先不用 AI（只用指令和按鈕）", value="none", variable=choice,
                        command=lambda: changed()).pack(anchor="w", pady=(10, 0))

        def code():
            return logic.provider_by_label(provider.get())

        def on_provider(_e=None):
            p = code()
            v["model"].set(logic.default_model(p))
            if logic.needs_base_url(p):
                row_url.pack(fill="x", pady=2)
            else:
                row_url.pack_forget()
            choice.set("keys")
            changed()

        combo.bind("<<ComboboxSelected>>", on_provider)

        def settings(which):
            return logic.llm_settings(which, base_url=v["base_url"].get(), api_key=v["api_key"].get(),
                                      model=v["model"].get() if which == "keys" else "", provider=code())

        def changed():
            c = choice.get()
            # Claude（找得到）與「先不用 AI」直接能下一步（測一下是選用的）；金鑰要先測通
            self.set_next("下一步 ▶", lambda: commit(c), enabled=(c == "none" or (c == "claude_code" and found)))

        def commit(which):
            llm, err = settings(which)
            if err:
                (keys_status if which == "keys" else claude_status).configure(text=f"❌ {err}")
                return
            self.llm = llm
            self.page_finish()

        def test(which, status):
            llm, err = settings(which)
            if err:
                status.configure(text=f"❌ {err}")
                return
            choice.set(which)
            changed()
            status.configure(text="⏳ 真的打一句給 AI…")

            def done(problem):
                if problem is None:
                    status.configure(text="✅ 通了！AI 有回話。")
                    if choice.get() == which:
                        self.set_next("下一步 ▶", lambda: commit(which))
                else:
                    status.configure(text=f"❌ {problem}")

            self.background(lambda: logic.probe_llm(llm), done)

        changed()

    # ── 完成 ─────────────────────────────────────────────────────────

    def page_finish(self):
        self.clear("差不多了", "最後一步")
        tk, ttk = self.tk, self.ttk
        desk = tk.BooleanVar(value=True)
        auto = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.body, text="在桌面放一個「SYNOX」捷徑", variable=desk).pack(anchor="w", pady=4)
        ttk.Checkbutton(self.body, text="開機後自動啟動 SYNOX（看得到的小視窗，隨時可以關）", variable=auto).pack(anchor="w")
        title, _one, _two = logic.mode_lines(self.mode)
        status = self.label(f"這台是：{title}。\n按「完成並開始」：寫好設定、打開 bot，手機會收到「我在了」。")

        def finish():
            try:
                cfg = logic.build_config(self.token, self.owner["id"], self.llm, existing=self.existing,
                                         mode=self.mode)
                logic.save(self.config_path, cfg)
            except Exception as e:
                status.configure(text=f"❌ 存設定失敗：{e}")
                return
            notes = []
            if desk.get():
                err = shortcuts.create_desktop_shortcut(ROOT)
                notes.append("桌面捷徑 " + ("✅" if not err else f"❌ {err}"))
            try:
                if auto.get():
                    shortcuts.enable_autostart(ROOT)
                    notes.append("開機自動啟動 ✅")
                else:
                    shortcuts.disable_autostart()
            except OSError as e:
                notes.append(f"開機自動啟動 ❌ {e}")
            start = os.path.join(ROOT, "Start.bat")
            subprocess.Popen(["cmd", "/c", start], cwd=ROOT, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            link = logic.web_login_link(self.config_path)
            if link:
                notes.append("幾秒後會打開網頁介面（之後在 Telegram 打 /web 可以再拿登入連結）")
                self.root.after(6000, lambda: webbrowser.open(link))
            status.configure(text="✅ 設定好了，bot 開起來了。\n" + "\n".join(notes) + "\n可以關掉這個視窗。")
            self.set_next("關閉", self.close)

        self.set_next("完成並開始", finish)


def main(config_path: str = CONFIG_PATH) -> int:
    try:
        import tkinter as tk
        root = tk.Tk()
    except Exception as e:
        print(f"❌ 開不了視窗（{e}）。可以複製 config.example.json 成 config.json 手動填。")
        return 1
    Wizard(root, config_path)
    root.mainloop()
    return 0
