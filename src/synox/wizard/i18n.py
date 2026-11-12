"""
安裝精靈的語言（只管安裝／解除安裝畫面；bot、網頁介面的字不在這裡）。

    from synox.wizard.i18n import t, set_lang
    set_lang("en")
    t("step", n=1, total=4)        # "Step 1 of 4"

字串在 synox/wizard/lang/<代號>.py（zh_TW.py 是原文、預設；其他語言是模型翻的，要母語者校對）。
zh-TW 以外的語言少了哪個 key 先退回 en，再退回 zh-TW。
選過的語言存在 SYNOX 資料夾的 lang.txt（一行語言代號），Setup.bat／Uninstall.bat／精靈共用
（PowerShell 那邊在 setup/lang.ps1，選單順序跟 LANGS 一樣）。
"""

from __future__ import annotations

import importlib
import os
from typing import Optional

DEFAULT = "zh-TW"
# 選單順序
LANGS = ("zh-TW", "zh-CN", "en", "es", "fr", "de", "pt-BR", "ru", "ar", "hi", "ja", "ko")
LANG_NAMES = {"zh-TW": "繁體中文", "zh-CN": "简体中文", "en": "English", "es": "Español", "fr": "Français",
              "de": "Deutsch", "pt-BR": "Português (Brasil)", "ru": "Русский", "ar": "العربية", "hi": "हिन्दी",
              "ja": "日本語", "ko": "한국어"}
LATIN_NAMES = {"zh-TW": "Traditional Chinese", "zh-CN": "Simplified Chinese", "en": "English", "es": "Spanish",
               "fr": "French", "de": "German", "pt-BR": "Portuguese (Brazil)", "ru": "Russian", "ar": "Arabic",
               "hi": "Hindi", "ja": "Japanese", "ko": "Korean"}
RTL = ("ar",)
_LATIN = ("Segoe UI", "Tahoma", "Arial")
# 精靈視窗的字型：依序試，這台電腦有哪個用哪個（都沒有就用 Tk 預設）
FONTS = {
    "zh-TW": ("Microsoft JhengHei UI", "Microsoft JhengHei", "Segoe UI"),
    "zh-CN": ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"),
    "ja": ("Yu Gothic UI", "Meiryo UI", "MS UI Gothic", "Segoe UI"),
    "ko": ("Malgun Gothic", "Segoe UI"),
    "hi": ("Nirmala UI", "Mangal", "Segoe UI"),
    **{code: _LATIN for code in ("en", "es", "fr", "de", "pt-BR", "ru", "ar")},
}
LANG_FILE = "lang.txt"
_ALIASES = {"zh": "zh-TW", "tw": "zh-TW", "zh-hant": "zh-TW", "zh-hk": "zh-TW",
            "cn": "zh-CN", "zh-hans": "zh-CN", "zh-sg": "zh-CN", "pt": "pt-BR", "br": "pt-BR"}

_current = DEFAULT
_tables: dict = {}


def normalize(lang) -> Optional[str]:
    """"EN"／"en-US"／"english" → "en"；"zh_tw" → "zh-TW"；"pt" → "pt-BR"；不認得 → None。"""
    s = str(lang or "").strip().lower().replace("_", "-")
    if not s:
        return None
    for code in LANGS:
        if s == code.lower() or s == LATIN_NAMES[code].lower():
            return code
    if s in _ALIASES:
        return _ALIASES[s]
    base = s.split("-")[0]
    if base in LANGS and base != "zh":
        return base
    return None


def table(lang: str) -> dict:
    """那個語言的字串表（synox/wizard/lang/<代號>.py 的 STRINGS）；沒有那個檔 → {}。"""
    if lang not in _tables:
        try:
            mod = importlib.import_module("synox.wizard.lang." + lang.replace("-", "_"))
            _tables[lang] = dict(mod.STRINGS)
        except ImportError:
            _tables[lang] = {}
    return _tables[lang]


def set_lang(lang) -> str:
    global _current
    _current = normalize(lang) or DEFAULT
    return _current


def get_lang() -> str:
    return _current


def t(key: str, **fmt) -> str:
    chain = (_current,) if _current == DEFAULT else (_current, "en", DEFAULT)
    text = key
    for lang in chain:
        found = table(lang).get(key)
        if found is not None:
            text = found
            break
    return text.format(**fmt) if fmt else text


def is_rtl(lang: Optional[str] = None) -> bool:
    return (lang or _current) in RTL


def font_family(available=(), lang: Optional[str] = None) -> str:
    """這個語言第一個裝在這台電腦上的字型；available 是空的（不知道有哪些）就回第一個候選。"""
    candidates = FONTS.get(lang or _current, FONTS[DEFAULT])
    if not available:
        return candidates[0]
    have = {f.lower() for f in available}
    for name in candidates:
        if name.lower() in have:
            return name
    return "TkDefaultFont"


def lang_path(root: str) -> str:
    return os.path.join(root, LANG_FILE)


def read_lang(path: str) -> Optional[str]:
    """lang.txt 裡存的語言；沒有檔案、讀不了、內容不認得 → None。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return normalize(f.read())
    except OSError:
        return None


def write_lang(path: str, lang) -> str:
    lang = normalize(lang) or DEFAULT
    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write(lang + "\n")
    return lang
