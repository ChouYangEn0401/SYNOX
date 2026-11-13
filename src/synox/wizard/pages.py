"""
安裝精靈（tkinter，stdlib，不開埠）：（語言）＋四頁＋完成頁。

  0. 語言：只有沒帶 --lang（或 SYNOX_LANG）進來時才問（Setup.bat 已經問過就跳過）；預選 lang.txt 存的那個。
     換了就用那個語言重畫，按「下一步」時存回 lang.txt。字串都在 i18n.py／lang/<代號>.py。
  1. 這台給誰用？○ 只有我（個人版）○ 一群人（伺服器版）；底下一行「工程師？直接改 config.json」
  2. 選 Telegram 或 Discord 的 bot（各自有自己的「怎麼拿 token」導覽）→ 貼上 → 驗證 →「✅ 這支 bot 叫 xxx」；
     或者「先跳過，晚點再補」，直接進第 4 步（核心功能不靠任何通道）。
  3. 你是誰：六位數配對碼。Telegram 直接「打開 t.me/<bot>」傳給它；Discord 要先把 bot 加進一個伺服器再私訊它。
     背景等那則訊息 → 記下 owner_id（Discord 另外把帳號接進 identities.json）。
  4. AI：上面是預設「Claude（這台電腦登入的 Claude Code）」＋狀態＋測一下；下面「其他金鑰來源」
     （OpenAI／Anthropic API／Gemini／相容端點：下拉選單、網址（只有相容端點）、金鑰、模型、測一下）；「先不用 AI」
  5. 完成：桌面捷徑（預設勾）、開機自動啟動（預設不勾）、完成後立刻開啟 SYNOX（預設勾）→「完成並開始」寫 config.json
     （連同 "language"）；勾了就開 Start.bat（沒接聊天軟體＝只跑網頁介面，自己會打開瀏覽器）；沒勾就只存設定

阿拉伯文（由右至左）盡力而為：文字靠右、右對齊，「下一步」移到左邊，一列裡的元件從右排起；
Tk 本身不做雙向文字重排，框線、下拉選單、輸入框、捲軸不會鏡像。

網路呼叫都在背景執行緒，結果用 root.after 交回畫面執行緒。畫面以外的邏輯在 logic.py／telegram_probe.py／
discord_probe.py／shortcuts.py（有單元測試）；這個檔案只有畫面。
"""

from __future__ import annotations

import os
import subprocess
import threading
import webbrowser

from synox import tutorials
from synox.config import CONFIG_PATH, ROOT
from synox.wizard import discord_probe, i18n, logic, shortcuts, telegram_probe
from synox.wizard.i18n import t

STEPS = 4
PLATFORMS = (("telegram", "Telegram"), ("discord", "Discord"))
WIDE = ("es", "fr", "de", "pt-BR", "ru", "ar", "hi")   # 字比較長的語言：視窗放寬，免得字被切掉


class Wizard:

    def __init__(self, root, config_path: str = CONFIG_PATH, lang=None, lang_file=None):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.root = root
        self.config_path = config_path
        self.lang_file = lang_file or i18n.lang_path(os.path.dirname(os.path.abspath(config_path)))
        self.existing = logic.read_existing(config_path)
        self.mode = self.existing.get("mode") if self.existing.get("mode") in logic.MODE_CHOICES else "personal"
        self.platform = "telegram"
        self.token = ""
        self.bot_name = ""
        self.bot_id = None
        self.owner = None
        self.llm = {"kind": "none"}
        self.stop = threading.Event()
        given = i18n.normalize(lang)
        self.ask_lang = given is None                # Setup.bat 已經問過（--lang）就不再問
        if given:
            self.save_lang(given)
        i18n.set_lang(given or i18n.read_lang(self.lang_file)
                      or i18n.normalize(self.existing.get("language")) or i18n.DEFAULT)
        try:                                        # 視窗左上角的圖示（找不到就用預設的）
            root.iconbitmap(shortcuts.icon_path(ROOT))
        except Exception:
            pass
        root.protocol("WM_DELETE_WINDOW", self.close)
        # 「下一步」那一列先釘在視窗最下面：內容再長也不會把它擠出畫面（擁有者回報過按鈕被藏起來）
        self.nav = ttk.Frame(root, padding=(18, 8, 18, 14))
        self.nav.pack(side="bottom", fill="x")
        # 內容放在可以捲動的畫布裡：比視窗高時出現捲軸、可以用滑鼠滾輪
        holder = ttk.Frame(root)
        holder.pack(side="top", fill="both", expand=True)
        self.canvas = tk.Canvas(holder, highlightthickness=0, borderwidth=0)
        self.scroll = ttk.Scrollbar(holder, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas, padding=18)
        self._body_id = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self._fit())
        self.canvas.bind("<Configure>", lambda e: (self.canvas.itemconfigure(self._body_id, width=e.width), self._fit()))
        root.bind_all("<MouseWheel>", self._wheel)
        root.bind_all("<Button-4>", lambda e: self._scroll_by(-3))
        root.bind_all("<Button-5>", lambda e: self._scroll_by(3))
        self.next_btn = ttk.Button(self.nav, text=t("next"), command=lambda: None, state="disabled")
        self.apply_lang()
        if self.ask_lang:
            self.page_language()
        else:
            self.page_mode()

    # ── 小工具 ───────────────────────────────────────────────────────

    def apply_lang(self):
        """依目前語言設好視窗標題、大小、字型、左右方向。"""
        lang = i18n.get_lang()
        self.rtl = i18n.is_rtl()
        self.west = "e" if self.rtl else "w"             # 「靠起頭那邊」
        self.start = "right" if self.rtl else "left"     # 一列裡元件從哪邊排起
        self.justify = "right" if self.rtl else "left"
        self.wrap = 660 if lang in WIDE else 580
        self.root.title(t("title"))
        self.root.geometry("720x660" if lang in WIDE else "640x580")
        self.root.minsize(self.wrap, 520)
        try:
            from tkinter import font as tkfont
            self.family = i18n.font_family(tkfont.families(self.root))
            if self.family != "TkDefaultFont":
                for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
                    tkfont.nametofont(name).configure(family=self.family)
        except Exception:
            self.family = "TkDefaultFont"
        style = self.ttk.Style(self.root)
        for kind in ("TCheckbutton", "TRadiobutton"):     # 長的選項自己換行，不被視窗切掉
            style.configure(kind, wraplength=self.wrap - 40, justify=self.justify)
        self.next_btn.pack_forget()
        self.next_btn.pack(side="left" if self.rtl else "right")

    def save_lang(self, lang):
        try:
            i18n.write_lang(self.lang_file, lang)
        except OSError:
            pass

    def clear(self, title: str, step: str):
        for w in self.body.winfo_children():
            w.destroy()
        try:
            self.canvas.yview_moveto(0)                   # 換頁回到最上面
        except Exception:
            pass
        self.ttk.Label(self.body, text=step, foreground="#666").pack(anchor=self.west)
        self.ttk.Label(self.body, text=title, font=(self.family, 15, "bold")).pack(anchor=self.west, pady=(2, 10))

    def label(self, text: str, parent=None, **kw):
        lbl = self.ttk.Label(parent or self.body, text=text, wraplength=self.wrap, justify=self.justify, **kw)
        lbl.pack(anchor=self.west, pady=4)
        return lbl

    def later(self, fn, *args):
        """背景執行緒 → 畫面執行緒。"""
        self.root.after(0, lambda: fn(*args))

    def background(self, work, done):
        threading.Thread(target=lambda: self.later(done, work()), daemon=True).start()

    def _fit(self):
        """內容高度變了：更新可捲範圍；放得下就藏起捲軸。"""
        try:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            need = self.body.winfo_reqheight() > self.canvas.winfo_height() + 1
        except self.tk.TclError:
            return
        if need and not self.scroll.winfo_ismapped():
            self.scroll.pack(side="right", fill="y")
        elif not need and self.scroll.winfo_ismapped():
            self.scroll.pack_forget()
            self.canvas.yview_moveto(0)

    def _scroll_by(self, units: int):
        if self.scroll.winfo_ismapped():
            self.canvas.yview_scroll(units, "units")

    def _wheel(self, event):
        self._scroll_by(-1 if event.delta > 0 else 1)

    def set_next(self, text: str, command, enabled: bool = True):
        self.next_btn.configure(text=text, command=command, state="normal" if enabled else "disabled")

    def close(self):
        self.stop.set()
        self.root.destroy()

    # ── 0. 語言 ──────────────────────────────────────────────────────

    def page_language(self):
        self.clear(t("lang_title"), "")
        ttk = self.ttk
        names = [f"{i18n.LANG_NAMES[c]} — {i18n.LATIN_NAMES[c]}" if c != "en" else "English"
                 for c in i18n.LANGS]
        current = names[i18n.LANGS.index(i18n.get_lang())]
        var = self.tk.StringVar(value=current)
        combo = ttk.Combobox(self.body, textvariable=var, values=names, state="readonly", width=40)
        combo.pack(anchor=self.west, pady=6)
        self.label(t("lang_hint"), foreground="#666")

        def picked(_e=None):
            i18n.set_lang(i18n.LANGS[names.index(var.get())])
            self.apply_lang()
            self.page_language()                  # 用新語言重畫

        combo.bind("<<ComboboxSelected>>", picked)

        def go():
            self.save_lang(i18n.get_lang())
            self.page_mode()

        self.set_next(t("next"), go)

    # ── 1. 這台給誰用 ────────────────────────────────────────────────

    def page_mode(self):
        self.clear(t("mode_title"), t("step", n=1, total=STEPS))
        tk, ttk = self.tk, self.ttk
        choice = tk.StringVar(value=self.mode)
        for value in logic.MODE_CHOICES:
            title, one, two = logic.mode_lines(value)
            ttk.Radiobutton(self.body, text=title, value=value, variable=choice).pack(anchor=self.west, pady=(10, 0))
            pad = (0, 26) if self.rtl else (26, 0)
            ttk.Label(self.body, text=f"{one}\n{two}", wraplength=self.wrap - 40, justify=self.justify,
                      foreground="#444").pack(anchor=self.west, padx=pad)
        ttk.Separator(self.body).pack(fill="x", pady=14)
        self.label(t("engineer_hint"), foreground="#666")

        def go():
            self.mode = choice.get()
            self.page_token()

        self.set_next(t("next"), go)

    # ── 2. token ─────────────────────────────────────────────────────

    def page_token(self):
        self.clear(t("token_title"), t("step", n=2, total=STEPS))
        tk, ttk = self.tk, self.ttk
        platform = tk.StringVar(value=self.platform)

        chooser = ttk.Frame(self.body)
        chooser.pack(anchor=self.west, pady=(0, 6))
        ttk.Label(chooser, text=t("token_which")).pack(side=self.start)
        for value, title in PLATFORMS:
            ttk.Radiobutton(chooser, text=title, value=value, variable=platform,
                            command=lambda: switch()).pack(side=self.start, padx=(6, 0))

        guide = self.label("")
        # 「看圖文教學」：有 docs/tutorials/<平台>/index.html 才出現（synox/tutorials.py），用瀏覽器開本機那份
        tutorial_btn = ttk.Button(self.body, text=t("open_tutorial"),
                                  command=lambda: tutorials.open_local(platform.get()))
        var = tk.StringVar(value=self.existing.get("bot_token", "") if self.platform == "telegram" else "")
        entry = ttk.Entry(self.body, textvariable=var, width=60)
        entry.pack(anchor=self.west, pady=6, fill="x")
        entry.focus_set()
        status = self.label("")
        self.set_next(t("next"), self.page_pair, enabled=False)

        def probe():
            return telegram_probe if platform.get() == "telegram" else discord_probe

        def switch():
            self.platform = platform.get()
            guide.configure(text=t("how_to_token") if self.platform == "telegram" else t("how_to_discord_token"))
            if tutorials.path_of(self.platform):
                tutorial_btn.pack(anchor=self.west, pady=(0, 4), before=entry)
            else:
                tutorial_btn.pack_forget()
            var.set("")
            status.configure(text="")
            self.token, self.bot_name, self.bot_id = "", "", None
            self.set_next(t("next"), self.page_pair, enabled=False)

        def check():
            token = var.get().strip()
            p = probe()
            if not p.valid_token(token):
                status.configure(text=t("token_not_token"))
                return
            status.configure(text=t("checking"))

            def done(result):
                ok, info = result
                if ok:
                    self.token, self.bot_name = token, info
                    if self.platform == "discord":
                        self.bot_id = discord_probe.bot_id(token)
                    status.configure(text=t("bot_is", name=info))
                    self.set_next(t("next"), self.page_pair)
                else:
                    status.configure(text=f"❌ {info}")

            self.background(lambda: p.get_me(token), done)

        self.ttk.Button(self.body, text=t("check_token"), command=check).pack(anchor=self.west)
        entry.bind("<Return>", lambda _e: check())
        self.ttk.Separator(self.body).pack(fill="x", pady=14)
        self.label(t("skip_hint"), foreground="#666")
        self.ttk.Button(self.body, text=t("skip_button"), command=self.skip_token).pack(anchor=self.west)
        switch()

    def skip_token(self):
        self.token, self.bot_name, self.bot_id, self.owner = "", "", None, None
        self.page_llm()

    # ── 3. 配對 ──────────────────────────────────────────────────────

    def page_pair(self):
        self.clear(t("pair_title"), t("step", n=3, total=STEPS))
        probe = telegram_probe if self.platform == "telegram" else discord_probe
        code = probe.new_pairing_code()
        if self.platform == "discord":
            self.label(t("pair_discord_invite"))
            self.ttk.Button(self.body, text=t("pair_open_invite"),
                            command=lambda: webbrowser.open(discord_probe.invite_url(self.bot_id))
                            ).pack(anchor=self.west, pady=(0, 10))
            self.label(t("pair_discord_dm", name=self.bot_name))
        else:
            self.label(t("pair_telegram", name=self.bot_name))
        self.ttk.Label(self.body, text=" ".join(code), font=("Consolas", 30, "bold")).pack(anchor=self.west, pady=10)
        if self.platform == "telegram":
            self.ttk.Button(self.body, text=t("pair_open_tme", name=self.bot_name),
                            command=lambda: webbrowser.open(f"https://t.me/{self.bot_name}")).pack(anchor=self.west)
        status = self.label(t("pair_waiting"))
        self.set_next(t("next"), self.page_llm, enabled=False)
        self.stop.clear()

        def done(who):
            if who is None:
                if not self.stop.is_set():
                    status.configure(text=t("pair_timeout"))
                return
            self.owner = who
            name = f"@{who['username']}" if who.get("username") else who.get("first_name", "")
            status.configure(text=t("pair_ok", name=name, id=who["id"]))
            self.set_next(t("next"), self.page_llm)

        token = self.token
        self.background(lambda: probe.wait_for_code(token, code, stop=self.stop), done)

    # ── 4. AI ────────────────────────────────────────────────────────

    def install_claude(self):
        """開一個 PowerShell 視窗跑官方安裝指令（不用系統管理員）；裝完在那個視窗打 claude 登入，再回來按「重新偵測」。"""
        try:
            flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            subprocess.Popen(logic.claude_install_args(t("install_ps_after")), creationflags=flags)
        except OSError:
            webbrowser.open(logic.CLAUDE_DOWNLOAD_URL)       # 沒有 PowerShell（不是 Windows）：改開官方說明

    def page_llm(self):
        self.stop.set()
        self.clear(t("llm_title"), t("step", n=4, total=STEPS))
        tk, ttk = self.tk, self.ttk
        found, claude_text = logic.claude_status()
        choice = tk.StringVar(value=logic.default_choice(found))
        v = {k: tk.StringVar() for k in ("base_url", "api_key", "model")}
        provider = tk.StringVar(value=logic.provider_labels()[0])
        v["model"].set(logic.default_model("openai"))
        wide = i18n.get_lang() in WIDE

        # 上：預設 Claude（這台電腦登入的 Claude Code）
        top = ttk.LabelFrame(self.body, text=t("llm_default"), padding=10)
        top.pack(fill="x")
        ttk.Radiobutton(top, text=t("claude_title"), value="claude_code", variable=choice,
                        command=lambda: changed()).pack(anchor=self.west)
        self.label(claude_text, parent=top, foreground="#2a6" if found else "#a33")
        if not found:                               # 沒裝：一鍵安裝（PowerShell）或去下載頁；裝好登入後按「重新偵測」
            helper = ttk.Frame(top)
            helper.pack(anchor=self.west)
            ttk.Button(helper, text=t("install_ps"), command=self.install_claude).pack(side=self.start)
            ttk.Button(helper, text=t("open_download"), command=lambda: webbrowser.open(logic.CLAUDE_DOWNLOAD_URL)
                       ).pack(side=self.start, padx=(6, 0))
            ttk.Button(helper, text=t("redetect"), command=self.page_llm).pack(side=self.start, padx=(6, 0))
            self.label(t("install_ps_note"), parent=top, foreground="#666")
            cmd_row = ttk.Frame(top)
            cmd_row.pack(anchor=self.west, fill="x")
            cmd = ttk.Entry(cmd_row, width=44)
            cmd.insert(0, logic.CLAUDE_INSTALL_PS)
            cmd.configure(state="readonly")
            cmd.pack(side=self.start)
            copied = ttk.Label(cmd_row, text="")

            def copy_cmd():
                self.root.clipboard_clear()
                self.root.clipboard_append(logic.CLAUDE_INSTALL_PS)
                copied.configure(text=t("copied"))
            ttk.Button(cmd_row, text=t("copy_cmd"), command=copy_cmd).pack(side=self.start, padx=(6, 0))
            copied.pack(side=self.start, padx=(6, 0))
        claude_status = self.label("", parent=top)
        ttk.Button(top, text=t("test"), command=lambda: test("claude_code", claude_status)).pack(anchor=self.west)

        # 下：其他金鑰來源
        bottom = ttk.LabelFrame(self.body, text=t("llm_other"), padding=10)
        bottom.pack(fill="x", pady=(10, 0))
        ttk.Radiobutton(bottom, text=t("llm_own_keys"), value="keys", variable=choice,
                        command=lambda: changed()).pack(anchor=self.west)
        form = ttk.Frame(bottom)
        form.pack(fill="x", pady=4)
        label_width = 16 if wide else 12

        def row(parent, label, var, secret=False):
            f = ttk.Frame(parent)
            f.pack(fill="x", pady=2)
            ttk.Label(f, text=label, width=label_width, anchor=self.west).pack(side=self.start)
            ttk.Entry(f, textvariable=var, show="•" if secret else "").pack(side=self.start, fill="x", expand=True)
            return f

        f = ttk.Frame(form)
        f.pack(fill="x", pady=2)
        ttk.Label(f, text=t("llm_provider"), width=label_width, anchor=self.west).pack(side=self.start)
        combo = ttk.Combobox(f, textvariable=provider, values=logic.provider_labels(), state="readonly")
        combo.pack(side=self.start, fill="x", expand=True)
        url_holder = ttk.Frame(form)              # 只有相容端點時才把「網址」那一列放進來
        url_holder.pack(fill="x")
        row_url = row(url_holder, t("llm_url"), v["base_url"])
        row_url.pack_forget()
        row(form, t("llm_api_key"), v["api_key"], secret=True)
        row(form, t("llm_model"), v["model"])
        keys_status = self.label("", parent=bottom)
        ttk.Button(bottom, text=t("test"), command=lambda: test("keys", keys_status)).pack(anchor=self.west)

        # 本地模型（llm.kind = "local"，docs/adr/0007）：伺服器、網址、模型、context-size（附建議）
        local = ttk.LabelFrame(self.body, text=t("llm_local"), padding=10)
        local.pack(fill="x", pady=(10, 0))
        ttk.Radiobutton(local, text=t("llm_local_pick"), value="local", variable=choice,
                        command=lambda: changed()).pack(anchor=self.west)
        lv = {"server": tk.StringVar(value=list(logic.LOCAL_SERVERS.values())[0]),
              "base_url": tk.StringVar(value=logic.local_defaults()["base_url"]),
              "model": tk.StringVar(), "context": tk.StringVar(value="8192")}
        local_body = ttk.Frame(local)            # 選了「本地模型」才展開（視窗高度有限）
        lf = ttk.Frame(local_body)
        lf.pack(fill="x", pady=4)
        f2 = ttk.Frame(lf)
        f2.pack(fill="x", pady=2)
        ttk.Label(f2, text=t("llm_local_server"), width=label_width, anchor=self.west).pack(side=self.start)
        server_combo = ttk.Combobox(f2, textvariable=lv["server"], values=list(logic.LOCAL_SERVERS.values()),
                                    state="readonly")
        server_combo.pack(side=self.start, fill="x", expand=True)
        row(lf, t("llm_url"), lv["base_url"])
        row(lf, t("llm_model"), lv["model"])
        f3 = ttk.Frame(lf)
        f3.pack(fill="x", pady=2)
        ttk.Label(f3, text=t("llm_local_context"), width=label_width, anchor=self.west).pack(side=self.start)
        from synox.llm.local_advice import OPTIONS as CONTEXT_OPTIONS
        ctx_combo = ttk.Combobox(f3, textvariable=lv["context"], width=18, values=[str(c) for c in CONTEXT_OPTIONS])
        ctx_combo.pack(side=self.start)
        advice_text = self.label(t("llm_local_context_hint"), parent=local_body, foreground="#666")
        local_status = self.label("", parent=local_body)
        lb = ttk.Frame(local_body)
        lb.pack(anchor=self.west)
        ttk.Button(lb, text=t("llm_local_advice"), command=lambda: advise()).pack(side=self.start)
        ttk.Button(lb, text=t("test"), command=lambda: test("local", local_status)).pack(side=self.start, padx=(6, 0))

        def server_code():
            return next((k for k, v in logic.LOCAL_SERVERS.items() if v == lv["server"].get()), "ollama")

        def on_server(_e=None):
            lv["base_url"].set(logic.local_defaults(server_code())["base_url"])
            choice.set("local")
            changed()

        server_combo.bind("<<ComboboxSelected>>", on_server)

        def advise():
            advice_text.configure(text=t("llm_local_advice_running"))
            server, url, model = server_code(), lv["base_url"].get(), lv["model"].get()

            def done(result):
                if isinstance(result, Exception):
                    advice_text.configure(text=f"❌ {result}")
                    return
                from synox.llm.local_advice import option_label
                ctx_combo.configure(values=[option_label(r) for r in result["options"]])
                if result.get("recommended"):
                    lv["context"].set(str(result["recommended"]))
                summary = "／".join(option_label(r) for r in result["options"])
                advice_text.configure(text=t("llm_local_advice_done", options=summary,
                                             least=result["min_context"]) + "\n" + result["notes"][0])

            def work():
                try:
                    return logic.local_advice(server, url, model)
                except Exception as e:                # 建議失敗不該讓精靈當掉
                    return e

            self.background(work, done)

        ttk.Radiobutton(self.body, text=t("llm_none"), value="none", variable=choice,
                        command=lambda: changed()).pack(anchor=self.west, pady=(10, 0))

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
            if which == "local":
                ctx = lv["context"].get().split("（")[0].strip()
                return logic.llm_settings("local", server=server_code(), base_url=lv["base_url"].get(),
                                          model=lv["model"].get(), context_size=int(ctx) if ctx.isdigit() else ctx)
            return logic.llm_settings(which, base_url=v["base_url"].get(), api_key=v["api_key"].get(),
                                      model=v["model"].get() if which == "keys" else "", provider=code())

        def changed():
            c = choice.get()
            if c == "local":
                local_body.pack(fill="x")
                form.pack_forget()
            else:
                local_body.pack_forget()
                if not form.winfo_manager():
                    form.pack(fill="x", pady=4, before=keys_status)
            # Claude（找得到）與「先不用 AI」直接能下一步（測一下是選用的）；金鑰要先測通
            self.set_next(t("next"), lambda: commit(c), enabled=(c == "none" or (c == "claude_code" and found)))

        def commit(which):
            llm, err = settings(which)
            if err:
                {"keys": keys_status, "local": local_status}.get(which, claude_status).configure(text=f"❌ {err}")
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
            status.configure(text=t("llm_testing"))

            def done(problem):
                if problem is None:
                    status.configure(text=t("llm_local_ok") if which == "local" else t("llm_ok"))
                    if choice.get() == which:
                        self.set_next(t("next"), lambda: commit(which))
                else:
                    status.configure(text=f"❌ {problem}")

            self.background(lambda: logic.probe_llm(llm), done)

        changed()

    # ── 完成 ─────────────────────────────────────────────────────────

    def page_finish(self):
        self.clear(t("finish_title"), t("last_step"))
        tk, ttk = self.tk, self.ttk
        desk = tk.BooleanVar(value=True)
        # Setup.bat 問過「建議／自訂」（setup/bootstrap.ps1 的 Invoke-SetupPlan）：建議＝勾好；自己開精靈＝照舊不勾
        auto = tk.BooleanVar(value=os.environ.get("SYNOX_SETUP_AUTOSTART") == "1")
        packs = tk.BooleanVar(value=True)
        launch = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.body, text=t("finish_desktop"), variable=desk).pack(anchor=self.west, pady=4)
        ttk.Checkbutton(self.body, text=t("finish_autostart"), variable=auto).pack(anchor=self.west)
        ttk.Checkbutton(self.body, text=t("finish_packs"), variable=packs).pack(anchor=self.west, pady=4)
        ttk.Checkbutton(self.body, text=t("finish_launch"), variable=launch).pack(anchor=self.west)
        title, _one, _two = logic.mode_lines(self.mode)
        if self.token:
            who = "bot" if self.platform == "telegram" else t("finish_discord_bot", name=self.bot_name)
            finish_hint = t("finish_hint_token", title=title, who=who)
        else:
            finish_hint = t("finish_hint_web", title=title)
        status = self.label(finish_hint)

        def finish():
            try:
                is_discord = self.platform == "discord" and bool(self.token)
                telegram_token = "" if is_discord else self.token
                if is_discord:
                    owner_id = logic.discord_owner_sentinel()
                elif self.owner:
                    owner_id = self.owner["id"]
                else:
                    owner_id = logic.local_owner_id()       # 沒接聊天軟體：本機擁有者（網頁登入用），之後補 Telegram 會換成真的
                cfg = logic.build_config(telegram_token, owner_id, self.llm, existing=self.existing,
                                         mode=self.mode, language=i18n.get_lang())
                cfg = logic.save(self.config_path, cfg)
                if is_discord:
                    cfg = logic.save_discord_token(self.config_path, cfg, self.token)
                    if self.owner:
                        logic.bind_discord_owner(self.config_path, cfg, self.owner["id"])
            except Exception as e:
                status.configure(text=t("finish_save_failed", e=e))
                return
            notes = []
            if desk.get():
                err = shortcuts.create_desktop_shortcut(ROOT)
                notes.append(t("note_desktop") + " " + ("✅" if not err else f"❌ {err}"))
            try:
                if auto.get():
                    shortcuts.enable_autostart(ROOT)
                    notes.append(t("note_autostart") + " ✅")
                else:
                    shortcuts.disable_autostart()
            except OSError as e:
                notes.append(f"{t('note_autostart')} ❌ {e}")
            if packs.get():
                try:
                    shortcuts.register_synoxpack(ROOT)
                    notes.append(t("note_packs") + " ✅")
                except OSError as e:
                    notes.append(f"{t('note_packs')} ❌ {e}")
            else:                                             # Setup.bat 先登記了；沒勾＝使用者不要，拿掉
                try:
                    shortcuts.unregister_synoxpack()
                except OSError:
                    pass
            if launch.get():                                  # 勾了才開；不管有沒有接聊天軟體
                start = os.path.join(ROOT, "Start.bat")
                subprocess.Popen(["cmd", "/c", start], cwd=ROOT,
                                 creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
                if self.token:
                    link = logic.web_login_link(self.config_path)
                    if link:
                        notes.append(t("note_web_later"))
                        self.root.after(6000, lambda: webbrowser.open(link))
                else:
                    notes.append(t("note_web_auto"))
            status.configure(text=logic.finish_status(notes, launched=launch.get(), has_token=bool(self.token)))
            self.set_next(t("close"), self.close)

        self.set_next(t("finish_go"), finish)


def main(config_path: str = CONFIG_PATH, lang=None) -> int:
    """lang＝Setup.bat 問過的語言（--lang／SYNOX_LANG）；沒有就在第一頁問。"""
    if lang:
        i18n.set_lang(lang)
    try:
        import tkinter as tk
        root = tk.Tk()
    except Exception as e:
        print(t("no_window", e=e))
        return 1
    Wizard(root, config_path, lang=lang)
    root.mainloop()
    return 0
