"""
synox.sdk：給 pack 作者（寫工具的人）的小工具。工具是什麼都行（exe、npm、別的語言的程式），跟 SYNOX 的接口只有 CLI：
子指令＋`--json`，**最後一行印一個 JSON 物件**，結束碼 0＝成功。這裡給三樣東西：

1. 三種 JSON 信封（Python 工具直接用；別的語言照下面的形狀印就好）

       reply_ok(data, message="")        → {"ok": true,  "message": "…", "data": {…}}                         結束碼 0
       reply_error(code, message)        → {"ok": false, "error": "…", "code": "not_found"}                   結束碼 1
       reply_confirm(summary, token)     → {"ok": true,  "needs_confirm": true, "summary": "…",
                                            "confirm_token": "…", "message": "…"}                           結束碼 0

   SYNOX 把 message 直接回給使用者；沒有 message 就把 data 的簡單欄位列出來。失敗回「❌ <error>」。
   reply_confirm：這一版 SYNOX 只把 summary 顯示給人（「要確認」的按鈕來回還沒做，見 docs/sdk.md）。
   每個函式都印出來並回結束碼：`sys.exit(reply_ok({...}))`。

2. 檢查與打包：`Pack.load(dir)` 跑安全管線第 1、2 關（宣告＋靜態掃描），`zip_pack(dir)` 打成 `.synoxpack`（算好
   `integrity.sha256` 寫進 zip 裡的 pack.json）。

3. 範本：`init_pack(dir, kind, name, title)` 產生 pack.json、SKILL.md、README.md、panel.html（＋python 的 pack.py、
   cli 的範例工具 tool.py）。

命令列：`synox-sdk init <資料夾> --kind cli --name x --title "…"`｜`synox-sdk check <資料夾>`｜`synox-sdk zip <資料夾>`
（沒有 synox-sdk 指令時：`python -m synox.sdk …`）。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import zipfile
from dataclasses import dataclass
from typing import Any, List, Optional

EXIT_OK, EXIT_ERROR = 0, 1


def _emit(obj: dict, out=None) -> None:
    stream = out or sys.stdout
    stream.write(json.dumps(obj, ensure_ascii=False) + "\n")
    stream.flush()


def ok_envelope(data: Any = None, message: str = "") -> dict:
    out = {"ok": True}
    if message:
        out["message"] = str(message)
    if data is not None:
        out["data"] = data
    return out


def error_envelope(code: str, message: str) -> dict:
    return {"ok": False, "error": str(message), "code": str(code)}


def confirm_envelope(summary: str, token: str) -> dict:
    return {"ok": True, "needs_confirm": True, "summary": str(summary), "confirm_token": str(token),
            "message": f"{summary}\n（要確認才會做）"}


def reply_ok(data: Any = None, message: str = "", *, out=None) -> int:
    _emit(ok_envelope(data, message), out)
    return EXIT_OK


def reply_error(code: str, message: str, *, out=None) -> int:
    _emit(error_envelope(code, message), out)
    return EXIT_ERROR


def reply_confirm(summary: str, token: str, *, out=None) -> int:
    _emit(confirm_envelope(summary, token), out)
    return EXIT_OK


# ── 檢查 ───────────────────────────────────────────────────────────────

@dataclass
class PackCheck:
    manifest: Any
    report: Any
    hashes: dict
    problems: List[str]

    @property
    def ok(self) -> bool:
        return not self.problems

    def format(self) -> str:
        text = self.report.format(self.manifest)
        extra = [p for p in self.problems if p.startswith("integrity")]
        return text + ("".join(f"\n❌ {p}" for p in extra))


class Pack:
    """`Pack.load(dir)`：跑 SYNOX 安裝時的第 1 關（嚴格的宣告檢查）與第 2 關（靜態掃描）。
    pack.json 本身不合丟 ValueError；掃描的問題在回傳的 PackCheck.problems。"""

    @staticmethod
    def load(folder: str) -> PackCheck:
        from synox.packs.admin import PackAdminError, run_gates
        try:
            m, report, hashes, problems = run_gates(os.path.abspath(folder))
        except PackAdminError as e:
            raise ValueError(str(e))
        return PackCheck(m, report, hashes, problems)


def zip_pack(folder: str, out_dir: Optional[str] = None) -> str:
    """pack 資料夾 → <out_dir>/<name>-<version>.synoxpack（zip，pack.json 在最上層）。
    先跑第 1、2 關；沒過丟 ValueError。zip 裡的 pack.json 多一段 integrity.sha256（每個檔的雜湊；原始檔不改）。"""
    check = Pack.load(folder)
    problems = [p for p in check.problems if not p.startswith("integrity")]
    if problems:
        raise ValueError("檢查沒過，不打包：" + "；".join(problems))
    m = check.manifest
    folder = os.path.abspath(folder)
    with open(os.path.join(folder, "pack.json"), "r", encoding="utf-8-sig") as f:
        raw = json.load(f)
    raw["integrity"] = {"sha256": {k: v for k, v in sorted(check.hashes.items()) if k != "pack.json"}}
    out_dir = out_dir or os.path.join(os.getcwd(), "dist")
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, f"{m.name}-{m.version}.synoxpack")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("pack.json", json.dumps(raw, ensure_ascii=False, indent=2) + "\n")
        for rel in sorted(check.hashes):
            if rel != "pack.json":
                z.write(os.path.join(folder, *rel.split("/")), rel)
    with open(target, "wb") as f:
        f.write(buf.getvalue())
    return target


# ── 範本 ───────────────────────────────────────────────────────────────

KINDS = ("python", "cli")

PANEL = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ --bg: #ffffff; --fg: #1d2330; --muted: #5d6675; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg: #171b22; --fg: #e7eaf0; --muted: #9aa3b2; }} }}
  body {{ margin: 0; padding: 12px; background: var(--bg); color: var(--fg);
         font: 15px/1.5 system-ui, "Microsoft JhengHei", "PingFang TC", sans-serif; }}
  .muted {{ color: var(--muted); font-size: 13px; }}
</style>
</head>
<body>
<div class="muted">{title}</div>
<div id="out">讀取中…</div>
<script>
(function () {{
  // 只打自己在 pack.json web.api 宣告的那幾個（GET /api/packs/{name}/<route>）；字一律 textContent
  fetch("/api/packs/{name}/summary", {{ credentials: "same-origin" }})
    .then(function (r) {{ if (!r.ok) {{ throw new Error(r.status); }} return r.json(); }})
    .then(function (d) {{ document.getElementById("out").textContent = d.message || JSON.stringify(d.data || d); }})
    .catch(function (e) {{ document.getElementById("out").textContent = "讀不到（" + e.message + "）"; }});
}})();
</script>
</body>
</html>
"""

PACK_PY = '''"""{title}：SYNOX python pack。install(app, pack) 在 pack.group 底下掛指令。"""

from isdtelekit.core.registry import WRITE, Field
from synox.packs import kit


def install(app, pack):
    def add(api, chat_id, user, values):
        n = pack.store.of(user).update(lambda d: (d.setdefault("items", []).append(values["text"]),
                                                  len(d["items"]))[1], {{"items": []}})
        api.send_message(chat_id, f"記下了（第 {{n}} 筆）")

    def summary(user):
        items = pack.store.of(user).load({{"items": []}})["items"]
        return {{"message": f"共 {{len(items)}} 筆", "data": {{"count": len(items)}}}}

    kit.command(pack.group, "add", add, "記一筆", default=True, effect=WRITE,
                fields=[Field("text", "要記的內容", required=True)])
    pack.web_route("summary", summary)
'''

TOOL_PY = '''"""範例工具：任何語言都可以，只要最後一行印一個 JSON 物件。這支用 synox.sdk 的信封（沒裝 SYNOX 也能照形狀自己印）。"""

import json
import sys

try:
    from synox.sdk import reply_error, reply_ok
except ImportError:                                   # 工具獨立執行時
    def reply_ok(data=None, message=""):
        print(json.dumps({{"ok": True, "message": message, "data": data}}, ensure_ascii=False)); return 0

    def reply_error(code, message):
        print(json.dumps({{"ok": False, "error": message, "code": code}}, ensure_ascii=False)); return 1


def main(argv):
    args = [a for a in argv if a != "--json"]
    if args[:1] == ["summary"]:
        return reply_ok({{"count": 0}}, "{title}：目前沒有東西")
    if args[:1] == ["echo"] and len(args) > 1:
        return reply_ok({{"text": args[1]}}, f"你說：{{args[1]}}")
    return reply_error("usage", "用法：summary｜echo <字>")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
'''


def init_pack(folder: str, kind: str, name: str, title: str) -> List[str]:
    """產生一個新的 pack 資料夾（已存在的檔不蓋）。回寫了哪些檔。"""
    if kind not in KINDS:
        raise ValueError(f"kind 只能是 {'、'.join(KINDS)}")
    from synox.packs.manifest import NAME_RE
    if not NAME_RE.match(name or ""):
        raise ValueError("name 只能用小寫英數字、-、_（32 字內，英文字母開頭）")
    os.makedirs(folder, exist_ok=True)
    manifest = {"name": name, "title": title, "summary": f"{title}（用 synox-sdk init 產生，改成你的說明）",
                "version": "0.1.0", "kind": kind, "access": "owner", "skill": "SKILL.md",
                "publisher": "", "capabilities": [],
                "web": {"panel": "panel.html", "api": ["GET /summary"]}}
    files = {}
    if kind == "python":
        manifest.update({"python": {"module": "pack"}, "storage": "vault"})
        files["pack.py"] = PACK_PY.format(title=title)
    else:
        manifest["cli"] = {"argv": ["{python}", "./tool.py"], "cwd": ".", "json_flag": "--json", "timeout": 60,
                           "commands": [
                               {"name": "summary", "effect": "READ", "default": True, "argv": ["summary"],
                                "summary": "看現在的狀態"},
                               {"name": "echo", "effect": "READ", "argv": ["echo", "{text}"], "summary": "回聲",
                                "fields": [{"name": "text", "ask": "要說什麼", "required": True}]}]}
        files["tool.py"] = TOOL_PY.format(title=title)
    group = name.replace("-", "").replace("_", "")[:16]
    files["pack.json"] = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    files["SKILL.md"] = (f"---\nname: {name}\ndescription: 使用者想要……的時候使用（改成什麼時候該用這個 pack）。\n---\n\n"
                         f"# {title}\n\n## 什麼時候用\n- 「……」→ `{group}__summary`\n\n## 注意\n- 參數名就是欄位名。\n")
    files["README.md"] = (f"# {title}\n\nSYNOX pack（kind: {kind}）。\n\n- 檢查：`synox-sdk check .`\n"
                          f"- 打包：`synox-sdk zip .` → `dist/{name}-0.1.0.synoxpack`\n"
                          "- 安裝：在 SYNOX 的網頁設定頁上傳，或點兩下 .synoxpack\n")
    files["panel.html"] = PANEL.format(title=title, name=name)
    written = []
    for rel, text in files.items():
        path = os.path.join(folder, rel)
        if os.path.exists(path):
            continue
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        written.append(rel)
    return written


# ── 命令列 ─────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(prog="synox-sdk", description="SYNOX pack 作者的工具：產生、檢查、打包")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("init", help="產生一個新的 pack 資料夾")
    p.add_argument("folder")
    p.add_argument("--kind", choices=KINDS, default="cli")
    p.add_argument("--name", required=True)
    p.add_argument("--title", default="")
    p = sub.add_parser("check", help="跑 SYNOX 安裝時的宣告檢查與靜態掃描")
    p.add_argument("folder")
    p = sub.add_parser("zip", help="打成 dist/<name>-<version>.synoxpack")
    p.add_argument("folder")
    p.add_argument("--out", default="", help="輸出資料夾（預設 ./dist）")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "init":
            written = init_pack(args.folder, args.kind, args.name, args.title or args.name)
            print(f"✅ 寫了 {len(written)} 個檔：{'、'.join(written) or '（都已經存在，沒動）'}")
            return 0
        if args.cmd == "check":
            check = Pack.load(args.folder)
            print(check.format())
            return 0 if check.ok else 2
        if args.cmd == "zip":
            path = zip_pack(args.folder, args.out or None)
            print(f"📦 {path}")
            return 0
    except ValueError as e:
        print(f"❌ {e}")
        return 2
    parser.print_help()
    return 1
