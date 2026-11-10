# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ChouYangEn and the SYNOX Team
"""📋 備忘清單：kind=cli 的工具「不一定要用 SDK」的範例。

只用 Python 標準函式庫，**沒有 import synox_sdk**：自己讀 argv、自己讀 SYNOX 給的環境變數、自己印 JSON 信封。
任何語言（Go、Rust、C#、Node、shell…）照同樣的規則寫都可以，規則見同一層的 README.md。

    python tool.py list --json
    python tool.py add --text=買牛奶 --json
    python tool.py clear --json            → 先回 needs_confirm；SYNOX 讓人按 ✅ 後帶 SYNOX_CONFIRMED=1 重跑
"""

import hashlib
import json
import os
import sys

PACK = "any-language-cli"


def reply(obj, code=0):
    """信封：最後一行印一個 JSON 物件；結束碼 0＝成功、1＝失敗。"""
    print(json.dumps(obj, ensure_ascii=False))
    return code


def ok(message, data=None):
    return reply({"ok": True, "message": message, **({"data": data} if data is not None else {})})


def fail(code, message):
    return reply({"ok": False, "error": message, "code": code}, 1)


def parse(argv):
    """`<子指令> --欄位=值 … --json` → (子指令, {欄位: 值})。SYNOX 只會照 pack.json 的 argv 樣板組出這種形狀。"""
    words = [a for a in argv if a != "--json"]
    command = words[0] if words else ""
    values = {}
    for a in words[1:]:
        if a.startswith("--") and "=" in a:
            k, v = a[2:].split("=", 1)
            values[k] = v
    return command, values


def store_path():
    """這個人的資料夾：SYNOX 每次都放 SYNOX_USER_DATA_DIR（伺服器版每人一個）。檔放在 <那裡>/<pack 名>/。"""
    root = os.environ.get("SYNOX_USER_DATA_DIR", "")
    if not root:
        return None
    return os.path.join(root, PACK, "items.json")


def load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            items = json.load(f).get("items", [])
        return [str(i) for i in items] if isinstance(items, list) else []
    except (OSError, ValueError, AttributeError):
        return []


def save(path, items):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "items": items}, f, ensure_ascii=False)
    os.replace(tmp, path)


def digest(items):
    """把「看到的那份清單」綁進確認：按 ✅ 之前清單被改過，就不照舊的確認刪。"""
    return hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest()[:32]


def main(argv):
    command, values = parse(argv)
    path = store_path()
    if path is None:
        return fail("no_context", "要從 SYNOX 或 synox-sdk run 執行（沒有 SYNOX_USER_DATA_DIR）")
    items = load(path)
    if command == "list":
        if not items:
            return ok("清單是空的", {"count": 0})
        lines = [f"{i}. {t}" for i, t in enumerate(items, 1)]
        return ok("\n".join(lines), {"count": len(items)})
    if command == "add":
        text = values.get("text", "").strip()
        if not text:
            return fail("empty", "要給內容")
        items.append(text[:200])
        save(path, items)
        return ok(f"記下了（共 {len(items)} 筆）", {"count": len(items)})
    if command == "clear":
        if not items:
            return ok("清單本來就是空的", {"count": 0})
        key = digest(items)
        if os.environ.get("SYNOX_CONFIRMED") != "1":          # 第一次：要人確認（SYNOX 每次都明寫 0 或 1）
            return reply({"ok": True, "needs_confirm": True, "summary": f"要刪掉全部 {len(items)} 筆",
                          "confirm_token": key})
        if os.environ.get("SYNOX_CONFIRM_TOKEN") != key:      # 按 ✅ 之前清單變了：不照舊的確認做
            return fail("changed", "清單在你確認之後變了，沒有刪；要刪請重新下指令")
        save(path, [])
        return ok(f"刪掉了 {len(items)} 筆", {"count": 0})
    return fail("usage", "用法：list｜add --text=…｜clear")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
