# -*- coding: utf-8 -*-
"""cli pack 回來的 JSON 怎麼變成一則看得懂的訊息（Telegram、Web、終端機都用這一支）。

pack 的程式最好自己回 {"message": "…"} 或 {"text": "…"}——那就原樣給使用者。沒有的話照下面的規則把結構攤平：
- dict 裡有 message／text／summary → 那一句
- 其他 dict：一行一個 key: value；值是 list 就一行一項（每項是 dict 時挑幾個像名字的欄位），太長就截
- list → 一行一項
- 最多 MAX_LINES 行、每行 MAX_CHARS 字；超過就「…還有 N 項」

SDK 的 service.default_render 遇到 list 只印「N 筆」，手機上看不到內容，所以 SYNOX 自己渲染（2026-11-10 日記 pack 的整合測試發現）。"""

from __future__ import annotations

from typing import Any, List

MAX_LINES = 25
MAX_CHARS = 160
NAME_KEYS = ("name", "title", "label", "id", "date", "summary", "text", "message")
SKIP_KEYS = {"ok", "error", "raw"}


def _short(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        return f"{value:g}" if isinstance(value, float) else str(value)
    if isinstance(value, str):
        return value if len(value) <= MAX_CHARS else value[:MAX_CHARS - 1] + "…"
    if isinstance(value, list):
        return f"{len(value)} 項" if value else "（空）"
    if isinstance(value, dict):
        picked = [f"{k}={_short(v)}" for k, v in value.items() if k not in SKIP_KEYS][:4]
        return "、".join(picked) if picked else "{}"
    return str(value)


def _item_line(item: Any) -> str:
    """list 裡的一項變一行：dict 挑像名字的欄位，其他照 _short。"""
    if isinstance(item, dict):
        head = [str(item[k]) for k in NAME_KEYS if isinstance(item.get(k), (str, int, float)) and str(item[k]).strip()]
        rest = [f"{k}={_short(v)}" for k, v in item.items()
                if k not in NAME_KEYS and k not in SKIP_KEYS and not isinstance(v, (dict, list))][:3]
        line = "　".join(head[:3]) if head else _short(item)
        if rest:
            line += "（" + "、".join(rest) + "）"
        return line if len(line) <= MAX_CHARS else line[:MAX_CHARS - 1] + "…"
    return _short(item)


def render(data: Any) -> str:
    """把 JSON 結果變成一段文字。永遠回字串（空結果回「（沒有內容）」）。"""
    if data is None:
        return "（沒有內容）"
    if isinstance(data, str):
        return data.strip() or "（沒有內容）"
    if isinstance(data, dict):
        for key in ("message", "text", "summary"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        body = {k: v for k, v in data.items() if k not in SKIP_KEYS}
        if len(body) == 1 and isinstance(next(iter(body.values())), (list, dict)):
            data = next(iter(body.values()))                      # {"result": [...]} 這種信封：直接看裡面
            if isinstance(data, dict):
                return render(data)
        else:
            lines: List[str] = []
            for k, v in body.items():
                if isinstance(v, list):
                    lines.append(f"{k}：")
                    lines.extend(f"  • {_item_line(x)}" for x in v[:MAX_LINES])
                    if len(v) > MAX_LINES:
                        lines.append(f"  …還有 {len(v) - MAX_LINES} 項")
                elif isinstance(v, dict):
                    lines.append(f"{k}：{_short(v)}")
                else:
                    lines.append(f"{k}：{_short(v)}")
            return _cap(lines)
    if isinstance(data, list):
        if not data:
            return "（沒有內容）"
        lines = [f"{i}. {_item_line(x)}" for i, x in enumerate(data[:MAX_LINES], 1)]
        if len(data) > MAX_LINES:
            lines.append(f"…還有 {len(data) - MAX_LINES} 項")
        return "\n".join(lines)
    return _short(data)


def _cap(lines: List[str]) -> str:
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES] + [f"…還有 {len(lines) - MAX_LINES} 行"]
    return "\n".join(lines) if lines else "（沒有內容）"
