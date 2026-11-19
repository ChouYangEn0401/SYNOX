"""
外觀的「大方針」（docs/themes.md）：SYNOX 定好有哪些顏色 token、哪些可以換的位置（slot），
外觀包（kind=theme）與「自己貼」只能把這些東西**換掉**，不能加程式、不能改別的地方。

相容規則（跟教學的位置清單 synox/tour/anchors.py 一樣）：
- token、slot 的名字只加不改。真的要改名：新名字進表、舊名字放進 RENAMED_*（舊 → 新）至少留一個 MINOR。
- 刪掉一個 slot 也要至少留一個 MINOR：先在說明寫「下一版拿掉」。
- tests/test_theme.py 會比對 app.html 用到的 token、data-slot 與這裡：多一個少一個都會失敗。
- 顏色的值只在這裡（DEFAULTS、FIXED；ADR 0042）：app.html 的 :root 送出時由 root_decls 產生。
- 向前相容（ADR 0042）：外觀包一定要給的只有 REQUIRED_COLORS（凍結）；以後加的 token 一律選填，沒給的用 DERIVED 或 DEFAULTS。
- CONTRACT_VERSION：加名字不用升；改名／刪名（過了相容期）才升。外觀包的 theme.contract 寫它照哪一版做的。
"""

from __future__ import annotations

from typing import Dict, Tuple

CONTRACT_VERSION = 1

# ── token（CSS 自訂屬性，app.html 最上面的 :root）──────────────────────────
# 核心 12 色：外觀包的 tokens.light 與 tokens.dark 都一定要給齊（整個對話畫面才會一起換色）
CORE_COLORS: Tuple[str, ...] = ("bg", "surface", "text", "muted", "line", "accent", "accent-ink", "accent2",
                                "soft", "ok", "warn", "bad")
SHAPE_TOKENS: Tuple[str, ...] = ("radius",)
FONT_TOKENS: Tuple[str, ...] = ("font-ui", "font-brand")
MASCOT_TOKENS: Tuple[str, ...] = ("m1", "m2", "mi", "mb")
# 合約上的名字（給外觀包作者的那一份）
TOKENS: Tuple[str, ...] = CORE_COLORS + SHAPE_TOKENS + FONT_TOKENS
# 進階：沒寫就從核心 token 算出來（DERIVED）；寫了就用寫的
ADVANCED_TOKENS: Tuple[str, ...] = ("bg-glow", "surface-2", "sunken", "line-strong", "text-2", "accent-hover",
                                    "accent-line", "ok-soft", "warn-soft", "bad-soft", "me", "me-ink", "m-hi",
                                    "scrim", "shadow-up")
ALL_TOKENS: Tuple[str, ...] = TOKENS + MASCOT_TOKENS + ADVANCED_TOKENS
TOKEN_KIND: Dict[str, str] = {**{t: "color" for t in CORE_COLORS + MASCOT_TOKENS + ADVANCED_TOKENS},
                              "radius": "length", "font-ui": "font", "font-brand": "font", "shadow-up": "shadow"}

# 外觀包一定要給的：合約第 1 版的核心 12 色。**以後加的 token 一律選填**（ADR 0042）：
# 沒更新的舊外觀包不會因為 SYNOX 多了 token 就裝不上；它沒給的照下面 DEFAULTS（或 DERIVED）走。
REQUIRED_COLORS: Tuple[str, ...] = CORE_COLORS

# ── SYNOX 原本的顏色：**整個 SYNOX 只在這裡宣告**（ADR 0042）────────────────────────────────
# 網頁 app.html 最上面的 :root（淺色、跟隨系統的深色、強制深色三段）在送出時由這兩張表產生（root_decls）；
# 預覽頁、登入的小頁（web/server.PAGE_CSS）、電腦提醒視窗（remindwin/style）也都從這裡拿。
# light＝每個合約 token 都有值；dark＝深色時換掉的（沒列的跟淺色一樣：吉祥物、圓角、字型）。
# 加一個 token：名字進上面的表、值進這裡（淺色一定要有）；app.html 會自己多一行，舊外觀包沒給的就用這裡的。
DEFAULTS: Dict[str, Dict[str, str]] = {
    "light": {
        "bg": "#f3f5f8", "surface": "#ffffff", "text": "#131b26", "muted": "#6a7687", "line": "#e2e7ee",
        "accent": "#0a7c70", "accent-ink": "#ffffff", "accent2": "#2f7fd6", "soft": "#e0f2ef",
        "ok": "#12823b", "warn": "#9a6400", "bad": "#c62f2f",
        "radius": "10px",
        "font-ui": '"Segoe UI Variable Text", "Segoe UI", "Microsoft JhengHei UI", "Microsoft JhengHei", '
                   '"PingFang TC", "Noto Sans TC", system-ui, sans-serif',
        "font-brand": "var(--font-ui)",
        "m1": "#4f8df5", "m2": "#2f66d0", "mi": "#ffffff", "mb": "color-mix(in srgb, var(--bad) 55%, transparent)",
        "bg-glow": "#e3eef0", "surface-2": "#f7f9fb", "sunken": "#eef1f5", "line-strong": "#cdd5df",
        "text-2": "#465264", "accent-hover": "#086a60", "accent-line": "#9fd6cd", "ok-soft": "#e6f4ea",
        "warn-soft": "#fdf1dc", "bad-soft": "#fbe8e8", "me": "#dff1ee", "me-ink": "#0c3a35", "m-hi": "#8bb6ff",
        "scrim": "rgba(10, 15, 22, .4)", "shadow-up": "0 -8px 24px -16px rgba(0, 0, 0, .4)",
    },
    "dark": {
        "bg": "#0b0f14", "surface": "#121924", "text": "#dbe4ef", "muted": "#7f90a7", "line": "#1f2b3b",
        "accent": "#35e0c4", "accent-ink": "#04221d", "accent2": "#4aa8ff", "soft": "rgba(53, 224, 196, .12)",
        "ok": "#46d17f", "warn": "#ffb454", "bad": "#ff6b78",
        "bg-glow": "#13222b", "surface-2": "#161f2c", "sunken": "#0d131b", "line-strong": "#2d3b4f",
        "text-2": "#aab6c6", "accent-hover": "#63ead5", "accent-line": "rgba(53, 224, 196, .42)",
        "ok-soft": "rgba(70, 209, 127, .12)", "warn-soft": "rgba(255, 180, 84, .12)",
        "bad-soft": "rgba(255, 93, 108, .13)", "me": "#163836", "me-ink": "#dff7f2", "scrim": "rgba(3, 7, 12, .66)",
    },
}

# SYNOX 自己用、外觀包**不能換**的顏色（陰影、圖片的白底、暗幕）：一樣只在這裡宣告，一樣產生到 app.html 的 :root。
FIXED: Dict[str, Dict[str, str]] = {
    "light": {
        "img-bg": "#ffffff",                     # 工具回覆的圖（多半是透明底的 SVG／PNG）深色也墊白底才看得清楚
        "img-scrim": "rgba(0, 0, 0, .72)",       # 點圖放大時後面的暗幕
        "shadow-sm": "0 1px 2px rgba(19, 27, 38, .05), 0 1px 3px rgba(19, 27, 38, .06)",
        "shadow-md": "0 10px 30px -10px rgba(19, 27, 38, .22)",
        "shadow-lg": "0 24px 60px -18px rgba(19, 27, 38, .35)",
        "highlight": "inset 0 1px 0 rgba(255, 255, 255, .7)",
        "tour-scrim": "rgba(8, 12, 18, .38)",
    },
    "dark": {
        "shadow-sm": "0 1px 2px rgba(0, 0, 0, .4)",
        "shadow-md": "0 14px 34px -12px rgba(0, 0, 0, .75)",
        "shadow-lg": "0 28px 70px -20px rgba(0, 0, 0, .85)",
        "highlight": "inset 0 1px 0 rgba(255, 255, 255, .045)",
    },
}

# 沒給的時候沿用 SYNOX 預設、也不用提醒的（暗幕、陰影：哪一套外觀都合用）。套用清單上不算「要注意」。
NEUTRAL_TOKENS: Tuple[str, ...] = ("scrim", "shadow-up")


def default_tokens(mode: str) -> Dict[str, str]:
    """這個 mode 下 SYNOX 原本的每一個合約 token（深色＝淺色＋深色換掉的）。"""
    out = dict(DEFAULTS["light"])
    if mode == "dark":
        out.update(DEFAULTS["dark"])
    return out


def root_decls(mode: str, indent: str = "") -> str:
    """:root 那一段的宣告（合約 token＋FIXED），一行一個 `--名字: 值;`。mode＝light｜dark（dark 只列換掉的）。"""
    values = {**DEFAULTS[mode], **FIXED[mode]}
    return "\n".join(f"{indent}--{k}: {v};" for k, v in values.items())


def root_css() -> str:
    """SYNOX 原本的顏色，三段（淺色、跟隨系統的深色、強制深色），選擇器同 app.html：給沒有 app.html 的頁（預覽頁）墊底。"""
    light, dark = " ".join(root_decls("light").split("\n")), " ".join(root_decls("dark").split("\n"))
    return (f":root {{ {light} color-scheme: light; }}\n"
            f"@media (prefers-color-scheme: dark) {{ :root:not([data-theme=\"light\"]) {{ {dark} "
            f"color-scheme: dark; }} }}\n"
            f":root[data-theme=\"dark\"] {{ {dark} color-scheme: dark; }}")


# 套了外觀包時，進階 token 怎麼從核心 token 算（外觀包自己寫了就用它寫的）。
# 預設的 SYNOX 不用這張表：用上面 DEFAULTS 裡原本調好的顏色。
DERIVED: Dict[str, str] = {
    "bg-glow": "color-mix(in srgb, var(--accent) 9%, var(--bg))",
    "surface-2": "color-mix(in srgb, var(--surface) 62%, var(--bg))",
    "sunken": "color-mix(in srgb, var(--bg) 82%, var(--line))",
    "line-strong": "color-mix(in srgb, var(--line) 78%, var(--text))",
    "text-2": "color-mix(in srgb, var(--text) 72%, var(--muted))",
    "accent-hover": "color-mix(in srgb, var(--accent) 84%, var(--text))",
    "accent-line": "color-mix(in srgb, var(--accent) 45%, var(--surface))",
    "ok-soft": "color-mix(in srgb, var(--ok) 13%, var(--surface))",
    "warn-soft": "color-mix(in srgb, var(--warn) 13%, var(--surface))",
    "bad-soft": "color-mix(in srgb, var(--bad) 13%, var(--surface))",
    "me": "var(--soft)",
    "me-ink": "var(--text)",
    "m1": "var(--accent)",
    "m2": "color-mix(in srgb, var(--accent) 70%, var(--text))",
    "mi": "var(--accent-ink)",
    "mb": "color-mix(in srgb, var(--bad) 55%, transparent)",
    "m-hi": "color-mix(in srgb, var(--m1) 60%, var(--surface))",
}

# ── slot：可以整個換掉的位置（網頁上 data-slot="<名字>" 的元素）────────────────
# 名字 → (說明, 哪一版合約加的, 收什麼)；svg＝一張 SVG；html＝HTML 小子集（可以含 SVG）
SLOTS: Dict[str, Tuple[str, int, Tuple[str, ...]]] = {
    "mascot.idle": ("吉祥物（平常）：側欄與登入卡左上角的標誌、空白對話的插圖；預設是「S」方塊", 1, ("svg", "html")),
    "mascot.think": ("吉祥物（在想）：等 AI 回覆時那顆會晃的小方塊；預設是藍色方塊", 1, ("svg", "html")),
    "mascot.happy": ("吉祥物（開心）：裝好、套用成功的時候；預設是笑臉的 S 寶寶", 1, ("svg", "html")),
    "mascot.warn": ("吉祥物（注意）：安裝被拒、出問題的時候；預設是擔心的 S 寶寶", 1, ("svg", "html")),
    "opening": ("開場動畫：打開網頁時播的那一段（SVG＋CSS 動畫；時間 SYNOX 管，約 1.7 秒）；預設是 S 寶寶掉下來", 1,
                ("svg", "html")),
    "wordmark": ("字標：側欄的「SYNOX」字樣（開場的字也跟著換）；預設是文字 SYNOX", 1, ("svg", "html")),
    "appicon": ("分頁圖示（favicon）：只收 SVG；預設是瀏覽器的預設圖示", 1, ("svg",)),
    "chat.background": ("對話的背景：整個對話區後面的一張圖（鋪滿、在訊息底下、點不到）；只收 SVG；預設沒有。"
                        "使用者在「外觀 → 背景」自己選的（不要、純色、花紋、自己貼）蓋過外觀包的", 1, ("svg",)),
}
RENAMED_SLOTS: Dict[str, str] = {}
RENAMED_TOKENS: Dict[str, str] = {}
MODES: Tuple[str, ...] = ("auto", "light", "dark")

# ── 背景（設定 → 外觀 → 背景；每個人自己選，規則同 mode）──────────────────────────
# theme＝跟著外觀（外觀包有 chat.background 就用它，沒有就沒有）；none＝不要背景（外觀包有也不要）；
# color＝純色（跟底色混一半，深色也看得清楚）；pattern＝內建的花紋（只用 CSS 和 token 畫，跟著外觀換色）；
# svg＝自己貼的 SVG（「自己貼」的 chat.background 那一格）。
BACKGROUND_KINDS: Tuple[str, ...] = ("theme", "none", "color", "pattern", "svg")
BACKGROUND_PATTERNS: Dict[str, str] = {"dots": "小圓點", "grid": "方格紙", "stripes": "細斜線", "glow": "淡淡的光"}


def slot_name(name) -> str:
    """寫的名字 → 現在的 slot 名字；不認得＝""。"""
    name = RENAMED_SLOTS.get(str(name or ""), str(name or ""))
    return name if name in SLOTS else ""


def token_name(name) -> str:
    """寫的 token 名字（可以帶 --）→ 現在的名字；不認得＝""。"""
    name = str(name or "")
    name = name[2:] if name.startswith("--") else name
    name = RENAMED_TOKENS.get(name, name)
    return name if name in ALL_TOKENS else ""


def slot_key(name: str) -> str:
    """slot 名字 → 用在 class／id 前綴的寫法（mascot.idle → mascot-idle）。"""
    return name.replace(".", "-")
