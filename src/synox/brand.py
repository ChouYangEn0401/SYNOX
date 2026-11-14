"""SYNOX 的終端機門面：歡迎畫面（logo＋Welcome to SYNOX＋版本＋下一步）、`synox about`、`synox tips`。

什麼時候印、印成什麼樣子（`banner_mode`、`supports_unicode`、`supports_color`）：

- 不印：`--quiet`／`-q`、環境變數 `SYNOX_NO_BANNER`、`CI`、輸出不是終端機（管線、重導向、測試）。
  ＝既有指令被別的程式讀的時候，輸出一個字都沒變。
- 一行純文字：`TERM=dumb`。
- 完整版：互動終端機。`NO_COLOR` 只拿掉顏色、版面留著（照 no-color.org 的約定）；
  Windows 舊主控台的 code page 不是 65001（例如繁中預設的 cp950）時，方塊字元在細明體會變成兩格寬、整個 logo 歪掉，
  所以改用純 ASCII 的 logo、不放 emoji；`SYNOX_ASCII=1` 也可以強制用 ASCII。
- 寫出去還是遇到編不了的字（`UnicodeEncodeError`）就退回 ASCII 版，再不行就用 `?` 代替，絕不讓指令因為歡迎畫面掛掉。

顏色：ANSI（256 色；`COLORTERM=truecolor` 或 Windows Terminal 用全彩）。主色取 ISDPCS 深色的 `#35e0c4`（跟網頁介面同一個青綠），
logo 由左到右漸層；問候語照 ISDPCS 歡迎頁的時段（早安／午安／午後好／晚上好／深夜）。
"""

from __future__ import annotations

import os
import random
import sys
from datetime import datetime

PROJECT_URL = "https://github.com/ChouYangEn0401/SYNOX"     # repo 公開了（docs/QuestionToUser.md QB1 的 A：公開那天再填）
RELEASES_URL = PROJECT_URL + "/releases"                     # 每一版的發佈頁：看自己是不是最新版（docs/versioning.md）

#: 印歡迎畫面的指令（None＝`synox` 什麼都沒打）。init 是之後安裝流程會加的指令，先列著。
BANNER_COMMANDS = frozenset({None, "run", "open", "wizard", "init", "doctor", "about"})

# ---------------------------------------------------------------- 標語（唯一的來源）
#: SYNOX 的大標語（還沒定案，暫用這句）。要換只改這裡，再跑 python scripts/make_landing.py 重組介紹頁、
#: python scripts/make_cli_welcome.py 重產終端機預覽。兩段：介紹頁第一屏分兩行，第二段用主色。
#: 之後主題可以帶自己的「心情語」，但不會換掉這句標語。
SLOGAN = ("有事，", "跟它說一聲就好")
SLOGAN_EN = "Need something? Just tell it."
#: 定位句（介紹頁大標語上面那行小字）。
EYEBROW = "住在你自己電腦裡的 AI 助理"
EYEBROW_EN = "The AI assistant that lives on your own computer."
#: 介紹頁的彩蛋：偶爾冒出來、馬上被 S 寶寶刷掉的玩笑話（正式標語永遠是上面那句 SLOGAN，這些不會用在別的地方）。
#: 一個玩笑＝一拍或幾拍，每一拍是（第一行, 第二行）；介紹頁隨機挑一個玩笑、照順序播完每一拍。
#: 改了要重跑 python scripts/make_landing.py。
SLOGAN_JOKES = [
    [("一個人忙不過來，", "還有它。"), ("像多了一個室友，", "但會幫忙。")],
    [("一個只聽你的小幫手。", "你的助理，你說了算。")],
]

TAGLINE = "".join(SLOGAN) + EYEBROW + "。"

# ---------------------------------------------------------------- logo

_OWL = ["       ", "  ,_,  ", " (O,O) ", " (   ) ", ' -"-"- ', "       "]

# figlet「small」字型的 SYNOX（純 ASCII，cp950 也不會歪）
_ASCII_GLYPHS = {
    "S": [" ___ ", "/ __|", "\\__ \\", "|___/"],
    "Y": ["__   __", "\\ \\ / /", " \\ V / ", "  |_|  "],
    "N": [" _  _ ", "| \\| |", "| .` |", "|_|\\_|"],
    "O": ["  ___  ", " / _ \\ ", "| (_) |", " \\___/ "],
    "X": ["__  __", "\\ \\/ /", " >  < ", "/_/\\_\\"],
}

# 「ANSI Shadow」字型的 SYNOX（方塊字元，要 UTF-8 終端機）
_UNICODE_GLYPHS = {
    "S": ["███████╗", "██╔════╝", "███████╗", "╚════██║", "███████║", "╚══════╝"],
    "Y": ["██╗   ██╗", "╚██╗ ██╔╝", " ╚████╔╝ ", "  ╚██╔╝  ", "   ██║   ", "   ╚═╝   "],
    "N": ["███╗   ██╗", "████╗  ██║", "██╔██╗ ██║", "██║╚██╗██║", "██║ ╚████║", "╚═╝  ╚═══╝"],
    "O": [" ██████╗ ", "██╔═══██╗", "██║   ██║", "██║   ██║", "╚██████╔╝", " ╚═════╝ "],
    "X": ["██╗  ██╗", "╚██╗██╔╝", " ╚███╔╝ ", " ██╔██╗ ", "██╔╝ ██╗", "╚═╝  ╚═╝"],
}


def _word(glyphs: dict, text: str = "SYNOX") -> list[str]:
    rows = len(next(iter(glyphs.values())))
    out = [""] * rows
    for ch in text:
        g = glyphs[ch]
        width = max(len(r) for r in g)
        for i in range(rows):
            out[i] += g[i].ljust(width)
    return [r.rstrip() for r in out]


def logo_lines(unicode: bool = True) -> list[str]:
    """貓頭鷹＋SYNOX 字樣（每行不含顏色碼）。"""
    word = _word(_UNICODE_GLYPHS if unicode else _ASCII_GLYPHS)
    owl = _OWL if unicode else _OWL[1:5]
    return [(o + "  " + w).rstrip() for o, w in zip(owl, word)]


# ---------------------------------------------------------------- 問候語（照 ISDPCS 歡迎頁的時段）

_GREETINGS = [   # (到幾點為止, emoji, 問候, 一句話)
    (5, "🌙", "深夜了", "還在拼，是吧。SYNOX 陪你。"),
    (11, "🌅", "早安", "全新的一天，一起開工。"),
    (14, "🌞", "午安", "保持節奏，穩穩推進。"),
    (18, "🍵", "午後好", "下半場，把該收的一件件收掉。"),
    (23, "🌆", "晚上好", "回到家了，慢慢來。"),
    (24, "🌌", "夜深了", "夜貓模式啟動，別太晚睡。"),
]


def greeting(hour: int) -> tuple[str, str, str]:
    """(emoji, 問候, 一句話)；hour 是 0–23。"""
    for until, emoji, hi, sub in _GREETINGS:
        if hour < until:
            return emoji, hi, sub
    return _GREETINGS[-1][1:]


# ---------------------------------------------------------------- 小提示

TIPS = [
    "{prog} open：在這台電腦上打開網頁介面（SYNOX 沒在跑會先幫你開）。",
    "{prog} doctor --offline：不實際打 AI 的健康檢查，設定、資料、工具一次看。",
    "{prog} console：不連 Telegram，直接在終端機用擁有者的身分跟 bot 講話。",
    "{prog} stop（或雙擊 Stop.bat）：停掉正在跑的 SYNOX。",
    "{prog} install <檔>.synoxpack：先檢查、給你看報告，按確認才裝。",
    "{prog} packs status：看每個工具鎖了沒、有沒有被改過。",
    "{prog} about：版本、授權、裝在哪裡。",
    "在 Telegram 打 /web 拿網頁的登入連結（只能用一次、7 天內有效）。",
    "/schedule_add 21:00 <指令>：每天幾點自動替你跑一個指令。",
    "/ai_usage：看 AI 這個月用了多少。",
    "刪東西這類危險的事，AI 會先送一張確認卡給你按，不會自己做。",
    "data 資料夾不要刪：裡面有解密用的金鑰（.synox.key），不見了加密的資料就打不開。",
    "不想看到歡迎畫面：指令加 --quiet，或設環境變數 SYNOX_NO_BANNER=1。",
]


def tip(rng: random.Random | None = None, prog: str | None = None) -> str:
    return (rng or random).choice(TIPS).format(prog=prog or prog_name())


def all_tips(prog: str | None = None) -> list[str]:
    return [t.format(prog=prog or prog_name()) for t in TIPS]


# ---------------------------------------------------------------- 版本、名字

def version() -> str:
    from synox import __version__
    return __version__


def prog_name(argv0: str | None = None) -> str:
    """畫面上教人打的指令：從 `synox`（.venv\\Scripts\\synox.exe）叫的就寫 synox，否則 python -m synox。"""
    base = os.path.basename(argv0 if argv0 is not None else (sys.argv[0] if sys.argv else ""))
    stem = os.path.splitext(base)[0].lower()
    return "synox" if stem == "synox" else "python -m synox"


# ---------------------------------------------------------------- 偵測

def _truthy(value) -> bool:
    return str(value or "").strip().lower() not in ("", "0", "false", "no", "off")


def _isatty(stream) -> bool:
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def banner_mode(stream=None, *, quiet: bool = False, env=None) -> str:
    """off（不印）｜line（一行純文字）｜full（完整版）。"""
    env = os.environ if env is None else env
    stream = sys.stdout if stream is None else stream
    if quiet or _truthy(env.get("SYNOX_NO_BANNER")) or _truthy(env.get("CI")):
        return "off"
    if not _isatty(stream):
        return "off"
    if env.get("TERM", "").lower() == "dumb":
        return "line"
    return "full"


_UNICODE_SAMPLE = "███╗╚═╔╝" + "".join(g[1] for g in _GREETINGS)


def _console_codepage() -> int | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        return int(ctypes.windll.kernel32.GetConsoleOutputCP()) or None
    except Exception:
        return None


def supports_unicode(stream=None, *, env=None, codepage: int | None = None) -> bool:
    """方塊字元與 emoji 能不能放心印。codepage：測試用；None＝問 Windows 主控台（不是 Windows 就不管）。"""
    env = os.environ if env is None else env
    stream = sys.stdout if stream is None else stream
    if _truthy(env.get("SYNOX_ASCII")):
        return False
    encoding = getattr(stream, "encoding", None) or "ascii"
    try:
        _UNICODE_SAMPLE.encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    if env.get("WT_SESSION"):                      # Windows Terminal：UTF-8、方塊字元一格寬
        return True
    cp = codepage if codepage is not None else _console_codepage()
    return cp is None or cp == 65001


def _enable_windows_vt(stream) -> bool:
    """Windows 10 以後的主控台要先開「虛擬終端機」模式才吃 ANSI 顏色碼；開不了就不上色。"""
    if os.name != "nt":
        return True
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes
        handle = msvcrt.get_osfhandle(stream.fileno())
        kernel32 = ctypes.windll.kernel32
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        if mode.value & 0x0004:
            return True
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def supports_color(stream=None, *, env=None, enable_vt=None) -> bool:
    env = os.environ if env is None else env
    stream = sys.stdout if stream is None else stream
    if "NO_COLOR" in env and env.get("NO_COLOR", "") != "":
        return False
    if env.get("TERM", "").lower() == "dumb" or not _isatty(stream):
        return False
    if env.get("WT_SESSION"):
        return True
    return bool((enable_vt or _enable_windows_vt)(stream))


# ---------------------------------------------------------------- 上色

RESET = "\x1b[0m"
_BRAND_STOPS = [(0x35, 0xE0, 0xC4), (0x2A, 0xA5, 0xFF), (0x6A, 0x4B, 0xFF)]   # 青綠 → 藍 → 紫


def _lerp(stops, t: float):
    t = min(max(t, 0.0), 1.0) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    f = t - i
    a, b = stops[i], stops[i + 1]
    return tuple(round(a[k] + (b[k] - a[k]) * f) for k in range(3))


def _fg(rgb, truecolor: bool) -> str:
    r, g, b = rgb
    if truecolor:
        return f"\x1b[38;2;{r};{g};{b}m"
    return f"\x1b[38;5;{16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)}m"


class _Palette:
    def __init__(self, color: bool, truecolor: bool = False):
        self.color, self.truecolor = color, truecolor

    def wrap(self, text: str, code: str) -> str:
        return f"{code}{text}{RESET}" if self.color and text else text

    def accent(self, text: str) -> str:
        return self.wrap(text, _fg(_BRAND_STOPS[0], self.truecolor))

    def bold(self, text: str) -> str:
        return self.wrap(text, "\x1b[1m")

    def dim(self, text: str) -> str:
        return self.wrap(text, "\x1b[2m")

    def gradient(self, line: str, width: int) -> str:
        if not self.color:
            return line
        out, last = [], None
        for i, ch in enumerate(line):
            if ch == " ":
                out.append(ch)
                continue
            code = _fg(_lerp(_BRAND_STOPS, i / max(width - 1, 1)), self.truecolor)
            if code != last:
                out.append(code)
                last = code
            out.append(ch)
        return "".join(out) + (RESET if last else "")


# ---------------------------------------------------------------- 版面

_NEXT_STEPS = [("open", "打開網頁介面"), ("doctor", "健康檢查"), ("tips", "隨機一則小提示"), ("--help", "全部指令")]

_DOING = {   # 指令開始前的那一行（None＝沒有）
    "run": "正在啟動 SYNOX…",
    "open": "正在打開網頁介面…",
    "wizard": "安裝精靈的視窗馬上出現…",
    "init": "準備設定…",
    "doctor": "健康檢查開始…",
}


def render_banner(command=None, *, unicode: bool = True, color: bool = False, truecolor: bool = False,
                  now: datetime | None = None, tip_text: str | None = None, prog: str | None = None,
                  ver: str | None = None) -> str:
    """完整版歡迎畫面（字串，最後有換行）。command＝None 是 `synox` 什麼都沒打：多印「下一步」。"""
    p = _Palette(color, truecolor)
    prog = prog or prog_name()
    ver = ver or version()
    now = now or datetime.now()
    emoji, hi, sub = greeting(now.hour)
    logo = logo_lines(unicode)
    width = max(len(r) for r in logo)
    rule = ("─" if unicode else "-") * width
    lines = [""]
    lines += ["  " + p.gradient(r, width) for r in logo]
    lines.append("")
    lines.append("  " + p.bold("Welcome to SYNOX") + "  " + p.dim(f"v{ver}"))
    lines.append("  " + TAGLINE)
    lines.append("  " + (f"{emoji} " if unicode else "") + f"{hi}，{sub}")
    lines.append("  " + p.dim(rule))
    if command is None:
        lines.append("  " + p.bold("下一步"))
        cmd_width = max(len(f"{prog} {c}") for c, _ in _NEXT_STEPS)
        for c, what in _NEXT_STEPS:
            lines.append("    " + p.accent(f"{prog} {c}".ljust(cmd_width)) + "  " + what)
        lines.append("  " + p.dim(rule))
        if tip_text is None:
            tip_text = tip(prog=prog)
        lines.append("  " + ("💡 " if unicode else "") + "小提示：" + tip_text)
    else:
        hint = " · ".join(f"{p.accent(f'{prog} {c}')} {what}" for c, what in _NEXT_STEPS[:2]) \
               + f" · {p.accent(f'{prog} --help')}"
        lines.append("  " + hint)
        doing = _DOING.get(command)
        if doing:
            lines.append("  " + p.dim(doing))
    lines.append("")
    return "\n".join(lines) + "\n"


def render_line(command=None, *, ver: str | None = None, prog: str | None = None) -> str:
    prog = prog or prog_name()
    doing = _DOING.get(command) or f"{prog} open 打開網頁介面、{prog} --help 看全部指令"
    return f"SYNOX v{ver or version()} · Welcome to SYNOX · {doing}\n"


def _write(stream, text: str) -> bool:
    try:
        stream.write(text)
        stream.flush()
        return True
    except UnicodeEncodeError:
        return False


def show_banner(command=None, *, stream=None, quiet: bool = False, env=None, now: datetime | None = None,
                rng: random.Random | None = None, codepage: int | None = None, enable_vt=None) -> str:
    """照規則印歡迎畫面；回傳印出去的字（不印＝""）。任何錯都吞掉：歡迎畫面不能讓指令失敗。"""
    stream = sys.stdout if stream is None else stream
    env = os.environ if env is None else env
    try:
        mode = banner_mode(stream, quiet=quiet, env=env)
        if mode == "off":
            return ""
        if mode == "line":
            text = render_line(command)
            return text if _write(stream, text) else ""
        unicode = supports_unicode(stream, env=env, codepage=codepage)
        color = supports_color(stream, env=env, enable_vt=enable_vt)
        truecolor = color and (env.get("COLORTERM", "").lower() in ("truecolor", "24bit") or bool(env.get("WT_SESSION")))
        tip_text = tip(rng) if command is None else None
        text = render_banner(command, unicode=unicode, color=color, truecolor=truecolor, now=now, tip_text=tip_text)
        if _write(stream, text):
            return text
        if unicode:                                   # 偵測說可以、實際寫不出去：退回 ASCII 版
            text = render_banner(command, unicode=False, color=color, truecolor=truecolor, now=now,
                                 tip_text=tip_text)
            if _write(stream, text):
                return text
        encoding = getattr(stream, "encoding", None) or "ascii"
        text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        return text if _write(stream, text) else ""
    except Exception:
        return ""


def add_quiet_flags(subparsers, names) -> None:
    """讓 `synox run --quiet` 跟 `synox --quiet run` 都行（子指令上的 --quiet 沒給時不蓋掉全域的）。"""
    import argparse
    for name in names:
        p = subparsers.choices.get(name)
        if p is None:
            continue
        try:
            p.add_argument("-q", "--quiet", action="store_true", default=argparse.SUPPRESS,
                           help="不要印歡迎畫面（也可以設環境變數 SYNOX_NO_BANNER=1）")
        except argparse.ArgumentError:
            pass


# ---------------------------------------------------------------- about

def about_text(config_path: str | None = None, *, root: str | None = None) -> str:
    from synox.config import CONFIG_PATH, ROOT
    from synox.sdk.author import SDK_VERSION
    root = root or ROOT
    config_path = config_path or CONFIG_PATH
    has_config = os.path.exists(config_path)
    rows = [
        ("版本", f"SYNOX {version()} · 工具 SDK {SDK_VERSION} · Python {sys.version.split()[0]}"),
        ("授權", "核心 AGPL-3.0-or-later；工具 SDK 與範例 Apache-2.0（見 LICENSING.md）"),
        ("名稱與標誌", "「SYNOX」的使用規則見 .github/TRADEMARK.md"),
        ("裝在哪裡", root),
        ("設定檔", config_path + ("" if has_config else "（還沒有：雙擊 Setup.bat，或照 config.example.json 寫一份）")),
        ("文件", "README.md · docs/README.md · 安全問題請看 SECURITY.md（不要開公開 issue）"),
        ("專案網址", PROJECT_URL or "還沒公開"),
        ("有沒有新版", latest_hint()),
    ]
    width = max(_display_width(k) for k, _ in rows)
    out = [f"SYNOX v{version()} · {TAGLINE}", ""]
    for k, v in rows:
        out.append(f"  {k}{' ' * (width - _display_width(k))}  {v}")
    return "\n".join(out) + "\n"


def latest_hint() -> str:
    """一行：去哪裡看最新版。SYNOX 不會自己連網檢查（docs/adr/0023）。"""
    return f"到 {RELEASES_URL} 看最新版，跟這台的版本比（SYNOX 不會自己連網檢查）"


def _display_width(text: str) -> int:
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)
