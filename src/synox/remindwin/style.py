"""
電腦提醒視窗的外觀：跟著網頁主控面板的外觀（設定 → 外觀：外觀包、淺色／深色／跟著系統）。

    style.write(data_dir, theme="costume-b-lantern", mode="auto", tokens={"light": {...}, "dark": {...}})   # 主程式
    look = style.load(data_dir)            # 視窗程式：→ Look（顏色都是 #rrggbb、字型、圓角）

- 主程式（網頁的 Appearance）在啟動時、擁有者改外觀時寫 data/remind/desk/style.json：外觀包的名字、mode、
  外觀包的 token（已經過 theme.tokens 的檢查；沒有個人資料，只有顏色、字型名、圓角）。
- 視窗程式讀它，把 token 換成 tkinter 看得懂的 #rrggbb：認得 #hex、rgb()／rgba()（透明的混到卡片底色上）、
  var(--token)、color-mix(in srgb, A p%, B)；看不懂的那一個 token 用 SYNOX 原本的顏色。檔案沒有／壞了＝原本的 SYNOX。
- mode=auto：照 Windows「應用程式模式」（淺色／深色），跟網頁的「跟著系統」一樣。
- 字型：外觀包的字型是網頁用的 .woff2，視窗用不到；從 font-ui 名單裡挑這台電腦有裝、而且有中文字的，
  沒有就用微軟正黑體（中文要清楚）。

本檔不 import tkinter（測試不開視窗）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional

from synox.notify import desk as deskmod
from synox.theme import contract

FILE = "style.json"                      # data/remind/desk/style.json
VERSION = 1

# 視窗用到的 token：值從 synox/theme/contract.py 拿（ADR 0042：整個 SYNOX 的顏色只宣告一次）
WINDOW_TOKENS = ("bg", "surface", "surface-2", "sunken", "line", "line-strong", "text", "text-2", "muted", "accent",
                 "accent-hover", "accent-ink", "soft", "accent-line", "ok", "warn", "bad", "warn-soft")
DEFAULTS: Dict[str, Dict[str, str]] = {mode: {k: contract.default_tokens(mode)[k] for k in WINDOW_TOKENS}
                                       for mode in ("light", "dark")}
# 外觀包沒寫的進階 token：同 contract.DERIVED（只拿視窗用到的）
DERIVED: Dict[str, str] = {k: v for k, v in contract.DERIVED.items() if k in WINDOW_TOKENS}
DEFAULT_RADIUS = 10
DEFAULT_FONTS = ("Microsoft JhengHei UI", "Microsoft JhengHei", "PingFang TC", "Noto Sans TC", "Microsoft YaHei UI")
CJK_FONTS = frozenset(DEFAULT_FONTS + ("Noto Sans CJK TC", "Source Han Sans TC", "Microsoft YaHei", "SimHei",
                                       "Noto Serif TC", "Noto Sans HK", "Noto Sans SC", "Yu Gothic UI", "Meiryo UI"))
MODES = ("auto", "light", "dark")

_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_RGB_RE = re.compile(r"^rgba?\(\s*([\d.]+%?)[\s,]+([\d.]+%?)[\s,]+([\d.]+%?)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$")
_VAR_RE = re.compile(r"^var\(\s*--([a-z0-9-]+)\s*(?:,\s*(.+))?\)$")
_MIX_RE = re.compile(r"^color-mix\(\s*in\s+srgb\s*,(.+)\)$")
_STOP_RE = re.compile(r"^(.*?)(?:\s+([\d.]+)%)?$")

RGBA = tuple   # (r, g, b, a)：0–255 整數、a 是 0–1


def path(data_dir: str) -> str:
    return os.path.join(deskmod.remind_dir(data_dir), deskmod.DESK, FILE)


# ── 寫（主程式）─────────────────────────────────────────────────────────

def write(data_dir: str, *, theme: str = "", mode: str = "auto",
          tokens: Optional[Dict[str, Dict[str, str]]] = None) -> Optional[str]:
    """寫 style.json（內容一樣就不寫）。tokens＝外觀包的 {"light": {...}, "dark": {...}}（檢查過的）；沒有＝原本的 SYNOX。"""
    data = {"v": VERSION, "theme": str(theme or ""), "mode": mode if mode in MODES else "auto",
            "tokens": {m: {str(k): str(v) for k, v in ((tokens or {}).get(m) or {}).items()} for m in ("light", "dark")}}
    target = path(data_dir)
    try:
        with open(target, "r", encoding="utf-8") as f:
            if json.load(f) == data:
                return target
    except (OSError, ValueError):
        pass
    try:
        return deskmod._write_json(os.path.dirname(target), FILE, data)
    except OSError as e:
        logging.warning("[REMINDWIN] cannot write the window style: %s", type(e).__name__)
        return None


# ── 讀（視窗）───────────────────────────────────────────────────────────

def read(data_dir: str) -> dict:
    try:
        with open(path(data_dir), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and data.get("v") == VERSION else {}


def system_dark() -> bool:
    """Windows 的「應用程式模式」是深色嗎（讀不到＝淺色）。"""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return int(value) == 0
    except (OSError, ValueError):
        return False


def _clamp(v: float) -> int:
    return max(0, min(255, int(round(v))))


def _channel(text: str) -> float:
    return float(text[:-1]) * 2.55 if text.endswith("%") else float(text)


def _alpha(text: Optional[str]) -> float:
    if text is None:
        return 1.0
    a = float(text[:-1]) / 100 if text.endswith("%") else float(text)
    return max(0.0, min(1.0, a))


def _split_args(text: str):
    """color-mix 的兩個參數（括號裡的逗號不算）。"""
    depth, start, out = 0, 0, []
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append(text[start:i])
            start = i + 1
    out.append(text[start:])
    return [p.strip() for p in out]


def parse_color(value: str, tokens: Dict[str, str], depth: int = 0) -> Optional[RGBA]:
    """一個 token 值 → (r, g, b, a)；看不懂＝None。tokens 給 var(--x) 查。"""
    v = " ".join(str(value or "").split()).strip()
    if not v or depth > 8:
        return None
    low = v.lower()
    if low == "transparent":
        return (0, 0, 0, 0.0)
    m = _HEX_RE.match(v)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)
    m = _RGB_RE.match(low)
    if m:
        try:
            return (_clamp(_channel(m.group(1))), _clamp(_channel(m.group(2))), _clamp(_channel(m.group(3))),
                    _alpha(m.group(4)))
        except ValueError:
            return None
    m = _VAR_RE.match(low)
    if m:
        ref = tokens.get(m.group(1))
        got = parse_color(ref, tokens, depth + 1) if ref is not None else None
        if got is None and m.group(2):
            got = parse_color(m.group(2), tokens, depth + 1)
        return got
    m = _MIX_RE.match(low)
    if m:
        parts = _split_args(m.group(1))
        if len(parts) != 2:
            return None
        stops = []
        for part in parts:
            sm = _STOP_RE.match(part)
            color = parse_color(sm.group(1).strip(), tokens, depth + 1) if sm else None
            if color is None:
                return None
            stops.append((color, float(sm.group(2)) / 100 if sm.group(2) else None))
        (c1, p1), (c2, p2) = stops
        if p1 is None and p2 is None:
            p1, p2 = 0.5, 0.5
        elif p1 is None:
            p1 = 1 - p2
        elif p2 is None:
            p2 = 1 - p1
        total = (p1 + p2) or 1.0
        p1, p2 = p1 / total, p2 / total
        a = c1[3] * p1 + c2[3] * p2                     # 跟 CSS 一樣：先乘上透明度再混
        if a <= 0:
            return (0, 0, 0, 0.0)
        rgb = [(c1[i] * c1[3] * p1 + c2[i] * c2[3] * p2) / a for i in range(3)]
        return (_clamp(rgb[0]), _clamp(rgb[1]), _clamp(rgb[2]), a)
    return None


def hex_of(color: RGBA, under: Optional[RGBA] = None) -> str:
    """(r, g, b, a) → #rrggbb；透明的混到 under（卡片底色）上。"""
    r, g, b, a = color
    if a < 1 and under is not None:
        r, g, b = (c * a + u * (1 - a) for c, u in zip((r, g, b), under[:3]))
    return "#%02x%02x%02x" % (_clamp(r), _clamp(g), _clamp(b))


def mix(c1: str, c2: str, p: float) -> str:
    """兩個 #rrggbb 混：p＝c1 的比例（0–1）。按鈕的滑過、按下用。"""
    a = parse_color(c1, {}) or (0, 0, 0, 1.0)
    b = parse_color(c2, {}) or (0, 0, 0, 1.0)
    return hex_of(tuple(x * p + y * (1 - p) for x, y in zip(a[:3], b[:3])) + (1.0,))


def palette(mode: str, tokens: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """mode（light｜dark）＋外觀包那一邊的 token → 視窗用的 {名字: #rrggbb}。"""
    base = DEFAULTS["dark" if mode == "dark" else "light"]
    given = {k: v for k, v in (tokens or {}).items() if isinstance(k, str) and isinstance(v, str)}
    merged: Dict[str, str] = dict(base)
    if given:                                    # 套了外觀包：沒寫的進階 token 照 DERIVED 從它的核心色算
        merged.update({k: v for k, v in DERIVED.items()})
        merged.update(given)
    surface = parse_color(merged.get("surface", ""), merged) or parse_color(base["surface"], base)
    if surface[3] < 1:
        surface = parse_color(base["surface"], base)
    out: Dict[str, str] = {}
    for name in base:
        color = parse_color(merged.get(name, ""), merged)
        if color is None:
            color = parse_color(base[name], base)
        out[name] = hex_of(color, surface)
    out["surface"] = hex_of(surface)
    return out


def radius_px(tokens: Optional[Dict[str, str]]) -> int:
    raw = str((tokens or {}).get("radius", "") or "")
    m = re.match(r"^(\d{1,3}(?:\.\d+)?)(px|rem|em)?$", raw.strip())
    if not m:
        return DEFAULT_RADIUS
    n = float(m.group(1)) * (16 if m.group(2) in ("rem", "em") else 1)
    return int(max(0, min(24, n)))


def font_choices(font_ui: str = "") -> list:
    """font-ui 名單（CSS 寫法）→ 要試的字型名字（有中文字的在前、最後補微軟正黑體這幾個）。"""
    names = [n.strip().strip("\"'") for n in str(font_ui or "").split(",")]
    names = [n for n in names if n and n.lower() not in ("system-ui", "sans-serif", "serif", "ui-sans-serif",
                                                          "monospace", "cursive", "fantasy")]
    cjk = [n for n in names if n in CJK_FONTS]
    out = []
    for n in cjk + list(DEFAULT_FONTS):
        if n not in out:
            out.append(n)
    return out


def pick_font(font_ui: str, installed: Iterable[str]) -> str:
    have = {str(f) for f in installed}
    for name in font_choices(font_ui):
        if name in have:
            return name
    return DEFAULT_FONTS[0]


@dataclass
class Look:
    mode: str                                   # light｜dark（已經照 auto 決定好）
    colors: Dict[str, str]
    radius: int = DEFAULT_RADIUS
    font_ui: str = ""                           # CSS 的字型名單；真的用哪一個由 pick_font 決定
    theme: str = ""
    extra: Dict[str, str] = field(default_factory=dict)


def look(data: dict, *, dark_system: Optional[bool] = None) -> Look:
    """style.json 的內容 → Look。dark_system：mode=auto 時系統是不是深色（None＝去讀 Windows 設定）。"""
    mode = data.get("mode") if data.get("mode") in MODES else "auto"
    if mode == "auto":
        mode = "dark" if (system_dark() if dark_system is None else dark_system) else "light"
    tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
    mine = dict(tokens.get(mode) or {}) if isinstance(tokens.get(mode), dict) else {}
    if mode == "dark":                           # 深色沒寫字型／圓角：跟淺色同一個（同 theme.tokens.token_css）
        light = tokens.get("light") if isinstance(tokens.get("light"), dict) else {}
        for name in ("radius", "font-ui"):
            if name not in mine and name in light:
                mine[name] = light[name]
    return Look(mode=mode, colors=palette(mode, mine), radius=radius_px(mine), font_ui=str(mine.get("font-ui", "")),
                theme=str(data.get("theme") or ""))


def load(data_dir: str, *, dark_system: Optional[bool] = None) -> Look:
    return look(read(data_dir), dark_system=dark_system)


__all__ = ["DEFAULTS", "FILE", "Look", "font_choices", "hex_of", "load", "look", "mix", "palette", "parse_color",
           "path", "pick_font", "radius_px", "read", "system_dark", "write"]
