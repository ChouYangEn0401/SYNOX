"""
外觀的「大方針」（docs/themes.md）：SYNOX 定好有哪些顏色 token、哪些可以換的位置（slot），
外觀包（kind=theme）與「自己貼」只能把這些東西**換掉**，不能加程式、不能改別的地方。

相容規則（跟教學的位置清單 synox/tour/anchors.py 一樣）：
- token、slot 的名字只加不改。真的要改名：新名字進表、舊名字放進 RENAMED_*（舊 → 新）至少留一個 MINOR。
- 刪掉一個 slot 也要至少留一個 MINOR：先在說明寫「下一版拿掉」。
- tests/test_theme.py 會比對 app.html 用到的 token、data-slot 與這裡：多一個少一個都會失敗。
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

# SYNOX 原本的樣子（app.html 的 :root 與深色那一段；tests/test_theme.py 對過，改了兩邊要一起改）
DEFAULTS: Dict[str, Dict[str, str]] = {
    "light": {"bg": "#f3f5f8", "surface": "#ffffff", "text": "#131b26", "muted": "#6a7687", "line": "#e2e7ee",
              "accent": "#0a7c70", "accent-ink": "#ffffff", "accent2": "#2f7fd6", "soft": "#e0f2ef",
              "ok": "#12823b", "warn": "#9a6400", "bad": "#c62f2f", "radius": "10px",
              "m1": "#4f8df5", "m2": "#2f66d0", "mi": "#ffffff", "m-hi": "#8bb6ff"},
    "dark": {"bg": "#0b0f14", "surface": "#121924", "text": "#dbe4ef", "muted": "#7f90a7", "line": "#1f2b3b",
             "accent": "#35e0c4", "accent-ink": "#04221d", "accent2": "#4aa8ff", "soft": "rgba(53, 224, 196, .12)",
             "ok": "#46d17f", "warn": "#ffb454", "bad": "#ff6b78"},
}

# 套了外觀包時，進階 token 怎麼從核心 token 算（外觀包自己寫了就用它寫的）。
# 預設的 SYNOX 不用這張表：app.html 裡是原本調好的顏色。
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
}
RENAMED_SLOTS: Dict[str, str] = {}
RENAMED_TOKENS: Dict[str, str] = {}
MODES: Tuple[str, ...] = ("auto", "light", "dark")


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
