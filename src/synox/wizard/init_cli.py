"""
`python -m synox init`：文字版的安裝引導（跟 Setup.bat 的視窗精靈寫同一份 config.json）。

給誰用：
- 沒有視窗可開的時候（可攜版 Python 沒有 tkinter、遠端桌面、伺服器）——bootstrap.ps1 偵測到就改跑這個；
- git clone 下來、習慣終端機的人；
- 自動化與 clean-room 檢查：`--non-interactive`（全部用參數給）、`--dry-run`（只印出會寫什麼，什麼都不寫）。

步驟：這台給誰用 → Telegram（可以跳過，先只用網頁）→ AI 來源 → 工具庫在哪裡 → 挑工具裝（不自動全裝）→ 寫 config.json。
- 不連網：Telegram token 只檢查格式（要實際試就跑 `synox doctor`）；工具庫只讀本機資料夾（網址只會告訴你去下載）。
- 金鑰：互動時用 getpass 問、存進保管箱（config 只寫 "vault:llm_api_key"）；非互動只收 `--api-key-env 變數名`（config 寫 "env:變數名"），
  命令列上不收金鑰本身（會留在 shell 的歷史紀錄）。
- 工具照舊過 packs/admin.py 的五關：第 1、2 關的報告印出來，互動時一個一個問「裝嗎」；非互動時 `--tools` 列的就是核准。
"""

from __future__ import annotations

import getpass
import importlib.util
import json
import os
from typing import Callable, List, Optional

from synox import tutorials
from synox.config import redacted
from synox.wizard import logic
from synox.wizard import tools as library

AI_CHOICES = ("none", "claude_code", "openai", "anthropic", "gemini", "openai_compat")
AI_LABELS = {"none": "先不用 AI（只用指令和按鈕）", "claude_code": "Claude Code（這台電腦登入的 claude）",
             "openai": "OpenAI（金鑰）", "anthropic": "Anthropic API（金鑰）", "gemini": "Gemini（金鑰）",
             "openai_compat": "相容端點（公司閘道、自己電腦上的 Ollama；要網址）"}
EASY_LLM_HINT = ("用金鑰的 AI 要多裝 ntu_easy_llm（還沒上 PyPI）：裝法見 docs/AGENT.md「ntu_easy_llm」。"
                 "設定先存著，裝好之後 synox doctor 會測。")


class InitAbort(Exception):
    """使用者在問答中途取消（Ctrl+C／EOF）或非互動的參數不夠。"""


class Prompter:
    """問答的那一層（測試換掉 ask／secret）。非互動時一律拿預設值，沒有預設就丟 InitAbort。"""

    def __init__(self, interactive: bool, ask: Callable[[str], str] = input,
                 secret: Callable[[str], str] = getpass.getpass, out: Callable[[str], None] = print):
        self.interactive = interactive
        self._ask = ask
        self._secret = secret
        self.out = out

    def text(self, question: str, default: Optional[str] = None, *, required: bool = False) -> str:
        if not self.interactive:
            if default is None and required:
                raise InitAbort(f"非互動模式缺參數：{question}")
            return default or ""
        hint = f" [{default}]" if default else ""
        while True:
            try:
                answer = self._ask(f"{question}{hint}：").strip()
            except (EOFError, KeyboardInterrupt):
                raise InitAbort("取消了，什麼都沒寫。")
            if answer:
                return answer
            if default is not None or not required:
                return default or ""

    def choice(self, question: str, options: List[str], default: str, labels: Optional[dict] = None) -> str:
        if not self.interactive:
            return default
        self.out(question)
        for i, opt in enumerate(options, 1):
            self.out(f"  {i}. {(labels or {}).get(opt, opt)}" + ("（預設）" if opt == default else ""))
        while True:
            answer = self.text("選一個（數字或名字）", default)
            if answer in options:
                return answer
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return options[int(answer) - 1]
            self.out(f"  不認得 {answer!r}，再選一次。")

    def yes(self, question: str, default: bool = False) -> bool:
        if not self.interactive:
            return default
        answer = self.text(question + ("（Y/n）" if default else "（y/N）"), "y" if default else "n")
        return answer.strip().lower() in ("y", "yes", "是", "好")

    def password(self, question: str) -> str:
        if not self.interactive:
            return ""
        try:
            return self._secret(f"{question}（畫面不會顯示）：").strip()
        except (EOFError, KeyboardInterrupt):
            raise InitAbort("取消了，什麼都沒寫。")


def _token_ok(token: str) -> bool:
    from isdtelekit.host.config import TOKEN_RE
    return bool(TOKEN_RE.match(token or ""))


def ask_mode(p: Prompter, given: Optional[str], existing: dict) -> str:
    default = given or existing.get("mode") or "personal"
    if given or not p.interactive:
        if default not in logic.MODE_CHOICES:
            raise InitAbort(f"--mode 只能是 {'、'.join(logic.MODE_CHOICES)}")
        return default
    labels = {k: v[0] for k, v in logic.MODE_CHOICES.items()}
    return p.choice("① 這台給誰用？", list(logic.MODE_CHOICES), default, labels)


def _telegram_owner(value) -> Optional[int]:
    """舊 config 的 owner_id 是真的 Telegram id 才回（保留號段的本機擁有者、亂寫的都不算）。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if 0 < n < 10 ** 15 else None


def ask_telegram(p: Prompter, token: Optional[str], owner: Optional[str], existing: dict) -> tuple:
    """回 (token, owner_id)；不接 Telegram＝("", 本機擁有者)。"""
    old_token = existing.get("bot_token") or ""
    old_owner = _telegram_owner(existing.get("owner_id"))
    if p.interactive and token is None:
        p.out("② Telegram（可以先跳過，只用這台電腦上的網頁；之後再跑一次 init 或 Setup.bat 補上）")
        p.out("   跟 @BotFather 傳 /newbot 拿 token。")
        guide = tutorials.path_of("telegram")
        if guide:
            p.out(f"   圖文教學（用瀏覽器打開）：{guide}")
        token = p.password("貼上 bot token（Enter＝跳過" + ("／沿用舊的" if _token_ok(old_token) else "") + "）")
        if not token and _token_ok(old_token):
            token = old_token
    token = (token if token is not None else (old_token if _token_ok(old_token) else "")).strip()
    if not token:
        return "", logic.local_owner_id()
    if not _token_ok(token):
        raise InitAbort("bot token 的格式不對（長得像 123456789:AAH…，跟 @BotFather 拿）。")
    if owner is None and p.interactive:
        p.out("   你的 Telegram 數字 id：不知道的話留空，這次先不接 Telegram（之後雙擊 Setup.bat 用配對碼接，最簡單）。")
        owner = p.text("你的 Telegram id", str(old_owner) if old_owner else None)
    elif owner is None and old_owner:
        owner = str(old_owner)
    if not owner:
        p.out("   （沒有 Telegram id：token 這次不存，先只用網頁）")
        return "", logic.local_owner_id()
    try:
        owner_id = int(str(owner).strip())
    except ValueError:
        raise InitAbort(f"Telegram id 要是數字（現在是 {owner!r}）。")
    if owner_id <= 0:
        raise InitAbort("Telegram id 要是正整數。")
    return token, owner_id


def ask_ai(p: Prompter, args, existing: dict) -> tuple:
    """回 (config 的 llm 那一塊, 提醒的話)。金鑰：互動＝明文（logic.save 會存進保管箱）；非互動＝env:名字。"""
    notes: List[str] = []
    old = existing.get("llm") or {}
    default = getattr(args, "llm", None) or (old.get("kind") if old.get("kind") in AI_CHOICES else None)
    if not default:
        default = "claude_code" if logic.claude_status()[0] else "none"
    kind = default if (getattr(args, "llm", None) or not p.interactive) else \
        p.choice("③ AI 從哪裡來？", list(AI_CHOICES), default, AI_LABELS)
    if kind not in AI_CHOICES:
        raise InitAbort(f"--llm 只能是 {'、'.join(AI_CHOICES)}")
    model = getattr(args, "model", None)
    if kind == "none":
        return {"kind": "none"}, notes
    if kind == "claude_code":
        found, status = logic.claude_status()
        if not found:
            notes.append(f"⚠️ {status}（安裝說明：{logic.CLAUDE_DOWNLOAD_URL}）")
        llm, _err = logic.llm_settings("claude_code", model=model or "")
        return llm, notes
    base_url = getattr(args, "base_url", None) or ""
    if logic.needs_base_url(kind) and not base_url:
        base_url = p.text("相容端點的網址（例如 http://127.0.0.1:11434/v1）", old.get("base_url") or None, required=True)
    if model is None and p.interactive:
        model = p.text("模型", old.get("model") or logic.default_model(kind))
    env_name = getattr(args, "api_key_env", None) or ""
    if env_name:
        api_key = "env:" + env_name.strip()
    elif p.interactive:
        api_key = p.password("API 金鑰（存進這台電腦的保管箱；也可以打 env:環境變數名）")
        if not api_key and str(old.get("api_key") or "").startswith(("vault:", "env:")):
            api_key = old["api_key"]
    else:
        api_key = str(old.get("api_key") or "")
        if not api_key.startswith(("vault:", "env:")) and kind != "openai_compat":
            raise InitAbort("非互動模式用金鑰的 AI 要給 --api-key-env <環境變數名>（金鑰不要打在命令列上）。")
    llm, err = logic.llm_settings("keys", provider=kind, base_url=base_url, api_key=api_key, model=model or "")
    if err:
        raise InitAbort(err)
    if importlib.util.find_spec("ntu_easy_llm") is None:
        notes.append("⚠️ " + EASY_LLM_HINT)
    return llm, notes


def ask_library(p: Prompter, given: Optional[str], root: str, existing: dict) -> str:
    """回寫進 config 的 packs.library（相對於 SYNOX 資料夾；"" ＝不設）。"""
    old = ((existing.get("packs") or {}).get("library") or "").strip()
    default_folder = library.default_location(root)
    default = given if given is not None else (old or (library.DEFAULT_FOLDER if default_folder else ""))
    if p.interactive and given is None:
        p.out("④ 工具庫在哪裡？（SYNOX 出廠不帶工具；發佈的 zip／安裝程式旁邊附的 tools 資料夾就是）")
        while True:
            answer = p.text("工具庫資料夾（Enter＝" + (default or "先不設") + "）", default or None)
            if not answer:
                return ""
            problem = library.why_not_library(library.resolve(answer, root))
            if not problem:
                return library.to_config_value(library.resolve(answer, root), root)
            p.out(f"   ⚠️ {problem}")
            if library.is_url(answer) or p.yes("   還是照這樣存？", False):
                return answer
    if not default:
        return ""
    folder = library.resolve(default, root)
    problem = library.why_not_library(folder)
    if problem and given is not None:
        p.out(f"⚠️ 工具庫：{problem}")
    return default if library.is_url(default) else library.to_config_value(folder, root)


def choose_tools(p: Prompter, given: Optional[List[str]], lib: library.Library, have: set) -> list:
    p.out("⑤ 挑要裝的工具（不會自動全裝；之後也能在網頁「設定 → 裝功能」或 synox tools install 裝）")
    for line in library.list_lines(lib, have):
        p.out("   " + line)
    words = given if given is not None else ([p.text("要裝哪些？（名字或組合代號，空白分開；Enter＝先不裝）", "")]
                                             if p.interactive else [])
    chosen, unknown = library.pick(lib, words)
    if unknown:
        raise InitAbort(f"工具庫裡沒有：{'、'.join(unknown)}（有：{'、'.join(e.name for e in lib.entries)}）")
    return chosen


def install_tools(p: Prompter, lib: library.Library, chosen: list, have: set, *, data_dir: str, packs_dir: str,
                  owner, dry_run: bool) -> List[str]:
    """每個工具：對雜湊 → 第 1、2 關 → 印報告 →（互動）問 → 裝（第 3 關寫鎖）。回結果的每一行。"""
    from synox.packs import admin
    results: List[str] = []
    for entry in chosen:
        if entry.name in have:
            results.append(f"• {entry.name}：已經裝了（要升級：python -m synox tools install {entry.name}）")
            continue
        try:
            path = library.file_of(lib, entry)
        except library.LibraryError as e:
            results.append(f"❌ {entry.name}：{e}")
            continue
        if dry_run:
            results.append(f"• {entry.name} {entry.version}：會裝（--dry-run：雜湊對過了，沒有解壓、沒有裝）")
            continue
        try:
            token, summary = admin.stage_file(path, data_dir)
        except admin.GateRefused as e:
            if e.summary:
                p.out(admin.format_summary(e.summary))
            results.append(f"❌ {entry.name}：安全檢查沒過，不裝（{e}）")
            continue
        except admin.PackAdminError as e:
            results.append(f"❌ {entry.name}：{e}")
            continue
        p.out(admin.format_summary(summary))
        tier = summary.get("tier") or {}
        publisher = None
        if tier.get("needs_publisher"):
            if not p.interactive:
                results.append(f"⏭ {entry.name}：有掃不到內容的程式（T2），要你親手確認發行者；"
                               f"用 python -m synox tools install {entry.name} 裝")
                continue
            publisher = p.text(f"這個工具要你打發行者名字 {tier.get('publisher')!r} 才裝（Enter＝不裝）", "")
            if not publisher:
                results.append(f"⏭ {entry.name}：沒裝")
                continue
        if p.interactive and not publisher and not p.yes(f"裝 {entry.name}？", True):
            results.append(f"⏭ {entry.name}：沒裝")
            continue
        try:
            name = admin.install_staged(token, data_dir, packs_dir, approved_by=owner or "init", via="init",
                                        trust_publisher=publisher)
        except admin.PackAdminError as e:
            results.append(f"❌ {entry.name}：{e}")
            continue
        results.append(f"✅ {name} {entry.version}：裝好了（已寫進 packs.lock）")
    return results


def run(args, *, config_path: str, ask=input, secret=getpass.getpass, out=print,
        packs_dir: Optional[str] = None, vault_opener=None) -> int:
    """回 0＝寫好了（或 --dry-run 印好了）；1＝取消；2＝參數或工具庫有問題。"""
    from synox.packs.loader import PACK_DIRS
    interactive = not getattr(args, "non_interactive", False)
    dry_run = bool(getattr(args, "dry_run", False))
    config_path = os.path.abspath(config_path)
    root = os.path.dirname(config_path)
    p = Prompter(interactive, ask=ask, secret=secret, out=out)
    existing = logic.read_existing(config_path)
    out("SYNOX 安裝引導（文字版）" + ("　--dry-run：只印出來，什麼都不寫" if dry_run else ""))
    out(f"設定檔：{config_path}" + ("（已經有了：沒問到的設定照舊）" if existing else ""))
    try:
        mode = ask_mode(p, getattr(args, "mode", None), existing)
        token, owner_id = ask_telegram(p, getattr(args, "telegram_token", None), getattr(args, "owner_id", None),
                                       existing)
        llm, notes = ask_ai(p, args, existing)
        library_value = ask_library(p, getattr(args, "library", None), root, existing)
        cfg = logic.build_config(token, owner_id, llm, existing=existing, mode=mode)
        packs = dict(cfg.get("packs") or {})
        if library_value:
            packs["library"] = library_value
        else:
            packs.pop("library", None)
        cfg["packs"] = packs
        tools_words = getattr(args, "tools", None)
        chosen, lib = [], None
        folder = library.resolve(library_value, root) if library_value else ""
        packs_dir = packs_dir or PACK_DIRS[0]
        have = library.installed_names(packs_dir)
        if folder and not library.why_not_library(folder):
            lib = library.read(folder)
            chosen = choose_tools(p, tools_words, lib, have)
        elif tools_words and any(w.strip() for w in tools_words):
            raise InitAbort("要裝工具，先給工具庫的位置（--library <tools 資料夾>）")
    except InitAbort as e:
        out(f"❌ {e}")
        return 1 if interactive else 2
    except library.LibraryError as e:
        out(f"❌ 工具庫：{e}")
        return 2

    shown = redacted(cfg)
    if dry_run:
        out("— 會寫進 config.json 的內容（金鑰、token 只說有沒有）—")
        out(json.dumps(shown, ensure_ascii=False, indent=2))
    else:
        try:
            cfg = logic.save(config_path, cfg, vault_opener=vault_opener)
        except Exception as e:                       # 保管箱打不開、資料夾不能寫
            out(f"❌ 存設定失敗：{e}")
            return 2
        out(f"✅ 存好了：{config_path}")
    for note in notes:
        out(note)
    if lib is not None and chosen:
        from synox.config import SynoxConfig
        data_dir = SynoxConfig.from_dict(cfg, require_token=False, root=root).data_dir
        for line in install_tools(p, lib, chosen, have, data_dir=data_dir, packs_dir=packs_dir, owner=owner_id,
                                  dry_run=dry_run):
            out(line)
    elif lib is None:
        out("🧰 還沒設工具庫：拿到 tools 資料夾（.synoxpack＋index.json）後，跑 python -m synox tools list --library <資料夾>")
    out("下一步：python -m synox doctor（健康檢查）→ 雙擊 Start.bat（或 python -m synox run）開 SYNOX。")
    return 0
