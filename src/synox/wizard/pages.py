"""
安裝精靈（tkinter，stdlib，不開埠）：spec §2 的三頁＋完成頁。

  1. Telegram bot 的 token：「怎麼拿」三步 → 貼上 → getMe 驗證 →「✅ 這支 bot 叫 @xxx」
  2. 你是誰：六位數配對碼＋「打開 t.me/<bot>」→ 背景 getUpdates 等那則訊息 → 記下 owner_id
  3. AI 從哪裡來（四選一）→「測一下」真的打一句
  4. 完成：桌面捷徑（預設勾）、開機自動啟動（預設不勾）→「完成並開始」寫 config.json、開 Start.bat

網路呼叫都在背景執行緒，結果用 root.after 交回畫面執行緒。畫面以外的邏輯在 logic.py／telegram_probe.py／
shortcuts.py（有單元測試）；這個檔案只有畫面。
"""

from __future__ import annotations

import os
import subprocess
import threading
import webbrowser

from synox.config import CONFIG_PATH, ROOT
from synox.llm.claude_code import find_claude
from synox.wizard import logic, shortcuts, telegram_probe

TITLE = "SYNOX 安裝精靈"
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
        self.token = ""
        self.bot_name = ""
        self.owner = None
        self.llm = {"kind": "none"}
        self.stop = threading.Event()
        root.title(TITLE)
        root.geometry("620x480")
        root.minsize(560, 440)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.body = ttk.Frame(root, padding=18)
        self.body.pack(fill="both", expand=True)
        self.nav = ttk.Frame(root, padding=(18, 0, 18, 14))
        self.nav.pack(fill="x")
        self.next_btn = ttk.Button(self.nav, text="下一步 ▶", command=lambda: None, state="disabled")
        self.next_btn.pack(side="right")
        self.page_token()

    # ── 小工具 ───────────────────────────────────────────────────────

    def clear(self, title: str, step: str):
        for w in self.body.winfo_children():
            w.destroy()
        self.ttk.Label(self.body, text=step, foreground="#666").pack(anchor="w")
        self.ttk.Label(self.body, text=title, font=("Microsoft JhengHei UI", 15, "bold")).pack(anchor="w", pady=(2, 10))

    def label(self, text: str, **kw):
        lbl = self.ttk.Label(self.body, text=text, wraplength=560, justify="left", **kw)
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

    # ── 1. token ─────────────────────────────────────────────────────

    def page_token(self):
        self.clear("Telegram bot 的 token", "第 1 步，共 3 步")
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

    # ── 2. 配對 ──────────────────────────────────────────────────────

    def page_pair(self):
        self.clear("你是誰", "第 2 步，共 3 步")
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

    # ── 3. AI ────────────────────────────────────────────────────────

    def page_llm(self):
        self.stop.set()
        self.clear("AI 從哪裡來", "第 3 步，共 3 步")
        tk, ttk = self.tk, self.ttk
        choice = tk.StringVar(value="none")
        options = [("friend", "① 朋友／公司給的 AI 網址＋金鑰"), ("own", "② 我自己的 API key（OpenAI／Anthropic／Gemini）")]
        if find_claude():
            options.append(("claude_code", "③ 用這台電腦已登入的 Claude Code"))
        options.append(("none", "④ 先不用 AI（只用指令和按鈕）"))
        for value, text in options:
            ttk.Radiobutton(self.body, text=text, value=value, variable=choice,
                            command=lambda: show()).pack(anchor="w")
        form = ttk.Frame(self.body)
        form.pack(fill="x", pady=8)
        v = {k: tk.StringVar() for k in ("base_url", "api_key", "model", "provider")}
        v["provider"].set("openai")
        status = self.label("")

        def row(label, var, secret=False):
            f = ttk.Frame(form)
            f.pack(fill="x", pady=2)
            ttk.Label(f, text=label, width=12).pack(side="left")
            ttk.Entry(f, textvariable=var, show="•" if secret else "").pack(side="left", fill="x", expand=True)

        def show():
            for w in form.winfo_children():
                w.destroy()
            c = choice.get()
            if c == "friend":
                row("AI 網址", v["base_url"])
                row("金鑰", v["api_key"], secret=True)
                row("模型名稱", v["model"])
            elif c == "own":
                f = ttk.Frame(form)
                f.pack(fill="x", pady=2)
                ttk.Label(f, text="哪一家", width=12).pack(side="left")
                for p in logic.PROVIDERS:
                    ttk.Radiobutton(f, text=p, value=p, variable=v["provider"]).pack(side="left")
                row("API key", v["api_key"], secret=True)
                row("模型（可空）", v["model"])
            elif c == "claude_code":
                row("模型（可空）", v["model"])
            status.configure(text="")
            self.set_next("下一步 ▶", lambda: commit(go=True), enabled=(c == "none"))

        def commit(go=False):
            llm, err = logic.llm_settings(choice.get(), base_url=v["base_url"].get(), api_key=v["api_key"].get(),
                                          model=v["model"].get(), provider=v["provider"].get())
            if err:
                status.configure(text=f"❌ {err}")
                return None
            if go:
                self.llm = llm
                self.page_finish()
            return llm

        def test():
            llm = commit()
            if llm is None:
                return
            if llm.get("kind") == "none":
                status.configure(text="不用 AI，不用測。")
                return
            status.configure(text="⏳ 真的打一句給 AI…")

            def work():
                from synox.llm import make_adapter
                try:
                    adapter = make_adapter({"llm": llm})
                    return adapter.probe() if adapter is not None else "不認得的 AI 來源"
                except Exception as e:
                    return str(e)

            def done(err):
                if err is None:
                    status.configure(text="✅ 通了！AI 有回話。")
                    self.set_next("下一步 ▶", lambda: commit(go=True))
                else:
                    status.configure(text=f"❌ {err}")

            self.background(work, done)

        ttk.Button(self.body, text="測一下", command=test).pack(anchor="w")
        show()

    # ── 完成 ─────────────────────────────────────────────────────────

    def page_finish(self):
        self.clear("差不多了", "最後一步")
        tk, ttk = self.tk, self.ttk
        desk = tk.BooleanVar(value=True)
        auto = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.body, text="在桌面放一個「SYNOX」捷徑", variable=desk).pack(anchor="w", pady=4)
        ttk.Checkbutton(self.body, text="開機後自動啟動 SYNOX（看得到的小視窗，隨時可以關）", variable=auto).pack(anchor="w")
        status = self.label("按「完成並開始」：寫好設定、打開 bot，手機會收到「我在了」。")

        def finish():
            try:
                cfg = logic.build_config(self.token, self.owner["id"], self.llm, existing=self.existing)
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
