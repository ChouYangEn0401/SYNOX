"""
「auto」開關的共用判斷：小模型 harness 的新行為（完成宣稱檢查、步數總結、每輪工具數上限、系統提示尾端的本輪規則…）
預設只對**本地／較弱的來源**開，雲端與 Claude Code 的結果不變（docs/adr/0008、0014）。

    weak_source(adapter)          kind=local，或 kind=openai_compat 指到 loopback／私網＝True
    parse_switch(value, name)     llm.<name>：auto｜on｜off（true／false 也收）；寫錯丟 ValueError
    resolve(mode, adapter)        on＝開；auto＝weak_source；off＝關
    switch_on(llm, name, adapter) 讀 llm.<name> 再 resolve；寫錯＝關（config.py 會先擋下）

只看 adapter 的 kind 與 base_url（不呼叫它、不連網）。新的「auto」設定一律用這裡，不要自己再判斷一次。
"""

from __future__ import annotations

from typing import Optional

MODES = ("auto", "on", "off")
LOCAL_KINDS = ("local",)


def weak_source(adapter) -> bool:
    """auto 的判斷：本地／較弱的來源（kind=local；openai_compat 指到 loopback／私網）。claude_code、雲端＝False。"""
    kind = getattr(adapter, "kind", "") or ""
    if kind in LOCAL_KINDS:
        return True
    if kind == "openai_compat":
        from synox.llm.local import is_local_url
        return is_local_url(str(getattr(adapter, "base_url", "") or ""))
    return False


def parse_switch(value, name: str) -> str:
    """auto｜on｜off 的開關，true／false 也收。沒寫＝auto。"""
    if value is None or value == "":
        return "auto"
    if isinstance(value, bool):
        return "on" if value else "off"
    mode = str(value).strip().lower()
    if mode not in MODES:
        raise ValueError(f"llm.{name} 只能是 auto、on、off（或 true／false）。")
    return mode


def resolve(mode: str, adapter) -> bool:
    return mode == "on" or (mode == "auto" and weak_source(adapter))


def switch_on(llm: Optional[dict], name: str, adapter) -> bool:
    try:
        mode = parse_switch((llm or {}).get(name), name)
    except ValueError:
        return False
    return resolve(mode, adapter)
