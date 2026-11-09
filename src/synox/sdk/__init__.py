# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The SYNOX authors
"""
synox.sdk：給 pack 作者（寫工具的人）的小工具。工具是什麼都行（exe、npm、別的語言的程式），跟 SYNOX 的接口只有 CLI：
子指令＋`--json`，**最後一行印一個 JSON 物件**，結束碼 0＝成功。這裡給三樣東西：

1. 三種 JSON 信封（Python 工具直接用；別的語言照下面的形狀印就好）

       reply_ok(data, message="")        → {"ok": true,  "message": "…", "data": {…}}                         結束碼 0
       reply_error(code, message)        → {"ok": false, "error": "…", "code": "not_found"}                   結束碼 1
       reply_confirm(summary, token)     → {"ok": true,  "needs_confirm": true, "summary": "…",
                                            "confirm_token": "…", "message": "…"}                           結束碼 0

   SYNOX 把 message 直接回給使用者；沒有 message 就把 data 的簡單欄位列出來。失敗回「❌ <error>」。
   reply_confirm：SYNOX 出核准卡（why＝summary）；按 ✅ 用同一組參數重跑，那一次環境變數有 SYNOX_CONFIRMED=1、
   SYNOX_CONFIRM_TOKEN＝這裡給的 token（SYNOX 驗過一次性憑證才給；見 docs/sdk.md「確認來回」）。
   每個函式都印出來並回結束碼：`sys.exit(reply_ok({...}))`。

2. 檢查與打包：`Pack.load(dir)` 跑安全管線第 1、2 關（宣告＋靜態掃描），`zip_pack(dir)` 打成 `.synoxpack`（算好
   `integrity.sha256` 寫進 zip 裡的 pack.json）。

3. 範本：`init_pack(dir, kind, name, title)` 產生 pack.json、SKILL.md、README.md、panel.html（＋python 的 pack.py、
   cli 的範例工具 tool.py）。

4. 作者端（synox.sdk.author，單檔版 sdk/synox_sdk.py）：`@tool`、`serve()`、`secret()`、`context()`、`ToolError`、`Confirm`。
   `init_from(tool.py, …)` 從 @tool 函式產生 pack.json＋SKILL.md；`run_command(資料夾, 指令, 參數)` 本機試跑
   （照 loader 的代換與第 4 關驗參數，不用開 SYNOX）。

命令列：`synox-sdk init <資料夾> --kind cli --name x --title "…"`｜`synox-sdk init --from tool.py --name x --title "…"`｜
`synox-sdk check <資料夾>`｜`synox-sdk zip <資料夾>`｜`synox-sdk run <指令> [參數…] [--pack 資料夾]`
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

from synox.sdk import author
from synox.sdk.author import (Confirm, Context, Ok, SpecError, ToolError, confirm_envelope, confirmed, context,  # noqa: F401
                              error_envelope, ok_envelope, secret, serve, tool)

EXIT_OK, EXIT_ERROR = 0, 1


def _emit(obj: dict, out=None) -> None:
    stream = out or sys.stdout
    stream.write(json.dumps(obj, ensure_ascii=False) + "\n")
    stream.flush()


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
    # __pycache__ 不打包（P7：SYNOX 安裝時也不解出來；本機跑過留下的快取不是 pack 的一部分）
    hashes = {k: v for k, v in sorted(check.hashes.items()) if "__pycache__" not in k.split("/")[:-1]}
    raw["integrity"] = {"sha256": {k: v for k, v in hashes.items() if k != "pack.json"}}
    out_dir = out_dir or os.path.join(os.getcwd(), "dist")
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, f"{m.name}-{m.version}.synoxpack")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("pack.json", json.dumps(raw, ensure_ascii=False, indent=2) + "\n")
        for rel in sorted(hashes):
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
                "version": "0.1.0", "kind": kind, "access": "owner", "surfaces": ["dm"],
                "data": "user" if kind == "python" else "none", "skill": "SKILL.md",
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


# ── 單檔版 synox_sdk.py ────────────────────────────────────────────────

SINGLE_FILE_NAME = "synox_sdk.py"
SINGLE_FILE_HEADER = ("# synox_sdk.py：SYNOX 工具 SDK 的單檔版（只用標準函式庫，可以直接複製進你的 repo）。\n"
                      "# 由 scripts/build_synox_sdk.py 從 src/synox/sdk/author.py 產生；要改請改正本再重產，不要直接改這個檔。\n")


def single_file_source() -> str:
    """單檔版的內容＝說明兩行＋author.py 原文（換行一律 \\n）。"""
    with open(author.__file__, "r", encoding="utf-8") as f:
        text = f.read()
    return SINGLE_FILE_HEADER + text.replace("\r\n", "\n")


def write_single_file(path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(single_file_source())


# ── init --from tool.py ────────────────────────────────────────────────

@dataclass
class InitResult:
    folder: str
    written: List[str]
    notes: List[str]
    check: Optional[PackCheck] = None


def load_tools(tool_path: str):
    """在這個程序裡 import 作者的 tool.py（不跑 `if __name__ == "__main__"` 那段），回 (模組, [@tool 函式…])。
    tool.py 旁邊沒有 synox_sdk.py 時，`import synox_sdk` 暫時指到 synox.sdk.author。"""
    import importlib.util
    tool_path = os.path.abspath(tool_path)
    if not os.path.isfile(tool_path):
        raise ValueError(f"找不到 {tool_path}")
    tool_dir = os.path.dirname(tool_path)
    saved_sdk = sys.modules.get("synox_sdk")
    if saved_sdk is None and not os.path.isfile(os.path.join(tool_dir, SINGLE_FILE_NAME)):
        sys.modules["synox_sdk"] = author
    mod_name = "_synox_author_tool_" + os.path.splitext(os.path.basename(tool_path))[0]
    sys.path.insert(0, tool_dir)
    try:
        spec = importlib.util.spec_from_file_location(mod_name, tool_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except SystemExit as e:
        raise ValueError(f"載入 {os.path.basename(tool_path)} 時程式結束了（{e}）：serve() 要放在 if __name__ == \"__main__\": 底下")
    except Exception as e:
        raise ValueError(f"載入 {os.path.basename(tool_path)} 失敗：{type(e).__name__}: {e}")
    finally:
        sys.path.remove(tool_dir)
        if saved_sdk is None:
            sys.modules.pop("synox_sdk", None)
        else:
            sys.modules["synox_sdk"] = saved_sdk
    tools = []
    for value in vars(module).values():
        if callable(value) and author._raw_spec(value) is not None and value not in tools:
            tools.append(value)
    return module, tools


def _skill_md(name: str, title: str, group: str, commands: List[dict]) -> str:
    lines = [f"---\nname: {name}\ndescription: 使用者想要……的時候使用（改成什麼時候該用 {title}）。\n---\n",
             f"# {title}\n", "## 什麼時候用"]
    for c in commands:
        if c.get("ai") is False:
            continue
        params = "、".join(f"{f['name']}（{f['ask']}{'，必填' if f.get('required') else ''}）" for f in c.get("fields", []))
        lines.append(f"- 「……」→ `{group}__{c['name']}`：{c['summary'].rstrip('。.')}" + (f"。參數：{params}" if params else ""))
    lines += ["", "## 注意", "- 參數名就是欄位名；值一律是字串（SYNOX 會先檢查格式）。", "- （寫下 AI 該注意的事：什麼時候要先問使用者、哪些不要做。）", ""]
    return "\n".join(lines)


def _merge_commands(old: List[dict], new: List[dict]) -> List[dict]:
    """重跑 init --from：指令照函式重產，作者手動加的鍵（stdin、background、positional、timeout…）留著。"""
    generated = ("name", "effect", "summary", "argv", "fields", "default", "ai", "confirm")
    old_by = {c.get("name"): c for c in old if isinstance(c, dict)}
    out = []
    for c in new:
        extra = {k: v for k, v in old_by.get(c["name"], {}).items() if k not in generated}
        out.append({**c, **extra})
    return out


def init_from(tool_path: str, name: str, title: str = "", folder: Optional[str] = None) -> InitResult:
    """從 tool.py 的 @tool 函式產生 kind=cli 的 pack：pack.json（cli.commands、fields、requires.synox；capabilities 空著）
    ＋SKILL.md 骨架（已經有就不蓋）。pack.json 已經有＝只重產 cli.commands（其他照舊）。
    宣告不合（沒寫 effect…）丟 ValueError，什麼都不寫。"""
    from synox.packs.manifest import NAME_RE
    if not NAME_RE.match(name or ""):
        raise ValueError("name 只能用小寫英數字、-、_（32 字內，英文字母開頭）")
    tool_path = os.path.abspath(tool_path)
    module, tools = load_tools(tool_path)
    try:
        commands = author.commands_for(tools)
    except SpecError as e:
        raise ValueError(f"{os.path.basename(tool_path)} 的 @tool 宣告不合，沒有產生 pack：\n{e}")
    folder = os.path.abspath(folder or os.path.dirname(tool_path))
    os.makedirs(folder, exist_ok=True)
    title = title or name
    group = name.replace("-", "").replace("_", "")[:16]
    rel = os.path.relpath(tool_path, folder).replace(os.sep, "/")
    notes: List[str] = []
    if rel.startswith("../"):
        notes.append(f"⚠️ {os.path.basename(tool_path)} 不在 pack 資料夾裡：可以在這台跑，但 synox-sdk zip 不會把它打包進去")
    written: List[str] = []
    manifest_path = os.path.join(folder, "pack.json")
    doc = (module.__doc__ or "").strip().splitlines()
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)
        cli = raw.setdefault("cli", {})
        cli["commands"] = _merge_commands(cli.get("commands") or [], commands)
        notes.append("pack.json 已經有了：只重產 cli.commands（其他欄位沒動）")
    else:
        raw = {"name": name, "title": title, "summary": (doc[0] if doc else f"{title}（改成你的說明）"),
               "version": "0.1.0", "kind": "cli", "skill": "SKILL.md", "publisher": "", "capabilities": [],
               "requires": {"synox": author.SYNOX_REQUIRES},
               "cli": {"argv": ["{python}", "./" + rel], "cwd": ".", "json_flag": "--json", "timeout": 60,
                       "commands": commands}}
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(raw, ensure_ascii=False, indent=2) + "\n")
    written.append("pack.json")
    skill_path = os.path.join(folder, "SKILL.md")
    if not os.path.exists(skill_path):
        with open(skill_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(_skill_md(name, title, group, commands))
        written.append("SKILL.md")
    with open(tool_path, "r", encoding="utf-8-sig") as f:
        uses_single = "synox_sdk" in f.read()
    sdk_copy = os.path.join(os.path.dirname(tool_path), SINGLE_FILE_NAME)
    if uses_single and not os.path.exists(sdk_copy):
        write_single_file(sdk_copy)
        written.append(os.path.relpath(sdk_copy, folder).replace(os.sep, "/"))
    check = None
    try:
        check = Pack.load(folder)
    except ValueError as e:
        notes.append(f"❌ pack.json 檢查沒過：{e}")
    if check is not None:
        needed = sorted({f.capability for f in check.report.undeclared(check.manifest)})
        if needed:
            notes.append(f"🔍 掃描看到程式用了：{'、'.join(needed)}——確認是你要的，再寫進 pack.json 的 capabilities（不然拒裝）")
        else:
            notes.append("capabilities 先空著：程式要連網、開別的程式、讀寫檔案時要寫進去（synox-sdk check 會說缺什麼）")
        if not raw.get("publisher"):
            notes.append("publisher 空著：填上你的名字（給安裝的人看）")
    return InitResult(folder, written, notes, check)


# ── run：本機試跑一個指令 ───────────────────────────────────────────────

class _LocalSecrets:
    """synox-sdk run 用：「保管箱裡的 secret」＝作者自己在這個終端機設好的那幾個環境變數。"""

    def __init__(self, values: List[str]):
        self._values = values

    def secret_values(self, user=None) -> List[str]:
        return list(self._values)


def run_command(folder: str, command: str, args: List[str], *, data_dir: Optional[str] = None,
                as_ai: bool = True, confirmed: bool = False, out=None) -> int:
    """照 SYNOX 的 loader 跑一次 kind=cli 的指令：照位置填／key=value → 欄位格式（typed_check）→ 第 4 關（check_call）
    → 代換 argv／env／cwd → 子程序 → 讀最後一行 JSON，印出 SYNOX 會怎麼顯示。
    工具回 needs_confirm：印出 SYNOX 會出的確認卡；confirmed=True（--confirmed）＝當作按了 ✅，用同一組參數帶
    SYNOX_CONFIRMED=1／SYNOX_CONFIRM_TOKEN 再跑一次。
    回 0＝工具回 ok、1＝工具回失敗、2＝SYNOX 不會讓它執行（參數不合、少必填、secret 沒設）。"""
    import subprocess
    import tempfile
    from types import SimpleNamespace

    from isdtelekit.core.registry import Field
    from isdtelekit.jobs.cli import clean_env, last_json
    from isdtelekit.packs import service

    from synox.agent import validate as gate4
    from synox.packs import kit, loader, render
    from synox.packs import secrets as pack_secrets
    from synox.packs.manifest import ManifestError, read, secret_env_names

    def say(text: str) -> None:
        (out or sys.stdout).write(text + "\n")

    try:
        m = read(os.path.abspath(folder), strict=True)
    except ManifestError as e:
        raise ValueError(str(e))
    if m.kind != "cli":
        raise ValueError(f"{m.name} 是 kind={m.kind}；run 只跑 kind=cli 的 pack")
    by_name = {c["name"]: c for c in m.commands}
    c = by_name.get(command)
    if c is None:
        raise ValueError(f"{m.name} 沒有 {command} 這個指令（有：{'、'.join(by_name)}）")
    specs = c.get("fields") or []
    kinds = {f["name"]: f.get("kind", "text") for f in specs}
    choices = {f["name"]: tuple(f.get("choices") or ()) for f in specs}
    fields = tuple(Field(f["name"], f.get("ask", f["name"]), required=bool(f.get("required")),
                         default=str(f.get("default", "")), choices=choices[f["name"]],
                         check=gate4.typed_check(kinds[f["name"]], choices[f["name"]])) for f in specs)
    fields = tuple(service._no_dash(f) for f in fields)           # 跟 loader 一樣：值以 - 開頭一律拒
    n_required = sum(1 for f in fields if f.required)
    try:
        n_pos = int(c.get("positional", n_required))
    except (TypeError, ValueError):
        n_pos = n_required
    values, missing, errors = kit.parse_args(fields, args, max(0, min(n_pos, len(fields))))
    if errors:
        say("❌ " + "；".join(errors))
        return 2
    if missing:
        say(f"❌ 少了：{'、'.join(f.ask for f in missing)}（用法：{kit.usage_of(fields, n_pos)}）")
        return 2
    data_dir = os.path.abspath(data_dir or os.path.join(tempfile.gettempdir(), "synox-sdk-run", m.name))
    os.makedirs(data_dir, exist_ok=True)
    config = SimpleNamespace(data_dir=data_dir, mode="personal", owner_id=0)
    auth_fields = pack_secrets.fields_of(m)
    env_secrets = {f["env"]: os.environ.get(f["env"], "") for f in auth_fields if f["env"]}
    absent = [f["label"] for f in auth_fields if f["required"] and f["env"] and not env_secrets.get(f["env"])]
    if absent:
        say(f"🔌 要先連接：缺 {'、'.join(absent)}。本機試跑請先設環境變數 "
            f"{'、'.join(f['env'] for f in auth_fields if f['env'] and not env_secrets.get(f['env']))}")
        return 2
    if as_ai:                                                   # 第 4 關：AI 呼叫時 SYNOX 在執行前做的檢查
        group = m.group or m.name.replace("-", "").replace("_", "")[:16]
        node = SimpleNamespace(fields=fields, path=f"{group}.{command}")
        stored = [v for f in auth_fields if f["secret"] for v in [env_secrets.get(f["env"], "")] if v]
        app = SimpleNamespace(config=config, extras={
            "synox_config": config, "synox_pack_secrets": _LocalSecrets(stored),
            "synox_tool_meta": {node.path: {"argv": True, "kinds": kinds,
                                            "positional": [n for n in kinds if f"{{{n}}}" in c.get("argv", [])]}}})
        problem = gate4.check_call(app, node, dict(values), SimpleNamespace(tg_id=0), f"{group}__{command}")
        if problem:
            say(f"❌ 第 4 關：{problem}")
            return 2
    values = {k: gate4.normalize(kinds.get(k, "text"), v, choices.get(k, ())) for k, v in values.items()}
    ph = loader.placeholders(m, config)
    if not os.path.isfile(ph["python"]):
        ph["python"] = sys.executable                          # runtime auto 的環境還沒建：用這個 Python
    argv = loader.cli_prefix(m, ph) + loader.build_argv(c["argv"], {**values, **ph})
    json_flag = m.cli.get("json_flag", "--json")
    if json_flag:
        argv.append(json_flag)
    env = loader.cli_env(m, ph)
    env.update(loader.context_env(m, config, ph, auth_fields))
    env.update({k: v for k, v in env_secrets.items() if v})
    cwd = os.path.normpath(os.path.join(m.folder, loader.substitute(m.cli.get("cwd") or ".", ph)))
    stdin = loader.substitute(c["stdin"], {**values, **ph}) if isinstance(c.get("stdin"), str) else None
    from synox.packs import confirm as tool_confirm
    keep = list(secret_env_names(m)) + list(tool_confirm.ENV_NAMES)

    def run_once(confirm_token: Optional[str]):
        """回 (結束碼, reply)；叫不起來或沒有 JSON 回 (1, None)。"""
        say("▶ " + " ".join(json.dumps(a, ensure_ascii=False) if (" " in a or not a) else a for a in argv)
            + ("　（SYNOX_CONFIRMED=1：當作按了 ✅ 的重跑）" if confirm_token is not None else ""))
        try:
            proc = subprocess.run(argv, cwd=cwd, env=clean_env({**env, **tool_confirm.env_for(confirm_token)}, keep=keep),
                                  input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=float(c.get("timeout") or m.cli.get("timeout", 120)))
        except (OSError, subprocess.TimeoutExpired) as e:
            say(f"❌ 叫不起來：{e}")
            return 1, None
        if proc.stderr.strip():
            say("（stderr）" + proc.stderr.strip()[-1500:])
        reply = last_json(proc.stdout)
        if reply is None:
            say(f"❌ 沒有回 JSON（結束碼 {proc.returncode}）：{' '.join(proc.stdout.split())[-300:] or '沒有輸出'}")
            return 1, None
        say("◀ " + json.dumps(reply, ensure_ascii=False))
        return proc.returncode, reply

    code, reply = run_once(None)
    if reply is None:
        return 1
    if code == 0 and reply.get("ok", True) is not False and tool_confirm.is_needs_confirm(reply):
        say(f"SYNOX 會出確認卡：{tool_confirm.summary_of(reply)}　[✅ 執行] [❌ 取消]")
        if not confirmed:
            say("（按 ✅ 之後 SYNOX 用同一組參數重跑，這一次 confirmed() 是 True；本機模擬：加 --confirmed）")
            return 0
        code, reply = run_once(tool_confirm.tool_token(reply))
        if reply is None:
            return 1
        if code == 0 and tool_confirm.is_needs_confirm(reply):
            say("SYNOX 會回：" + tool_confirm.AGAIN.format(name=command))
            return 1
    if code != 0 or reply.get("ok", True) is False:
        say(f"SYNOX 會回：❌ {command}：{reply.get('reason') or reply.get('error') or reply.get('message') or f'結束碼 {code}'}")
        return 1
    say("SYNOX 會回：" + (render.render(reply) or "（沒有輸出）"))
    return 0


# ── 命令列 ─────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(prog="synox-sdk", description="SYNOX pack 作者的工具：產生、檢查、試跑、打包")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("init", help="產生一個新的 pack 資料夾；--from tool.py＝從 @tool 函式產生 pack.json")
    p.add_argument("folder", nargs="?", default="", help="pack 資料夾（--from 時預設＝tool.py 所在的資料夾）")
    p.add_argument("--from", dest="source", default="", help="用 synox_sdk 的 @tool 寫的 Python 檔")
    p.add_argument("--kind", choices=KINDS, default="cli")
    p.add_argument("--name", required=True)
    p.add_argument("--title", default="")
    p = sub.add_parser("run", help="本機試跑一個指令（照 SYNOX 的代換與參數檢查，不用開 SYNOX）")
    p.add_argument("command")
    p.add_argument("args", nargs="*", help="跟在 Telegram 打的一樣：照位置填，或 key=value")
    p.add_argument("--pack", default=".", help="pack 資料夾（預設：現在的資料夾）")
    p.add_argument("--data", default="", help="當作 SYNOX data/ 的資料夾（預設：暫存資料夾）")
    p.add_argument("--typed", action="store_true", help="當作人自己打字（不跑 AI 呼叫才有的第 4 關檢查）")
    p.add_argument("--confirmed", action="store_true", help="工具要確認時當作按了 ✅（同一組參數帶 SYNOX_CONFIRMED=1 重跑）")
    p = sub.add_parser("check", help="跑 SYNOX 安裝時的宣告檢查與靜態掃描")
    p.add_argument("folder")
    p = sub.add_parser("zip", help="打成 dist/<name>-<version>.synoxpack")
    p.add_argument("folder")
    p.add_argument("--out", default="", help="輸出資料夾（預設 ./dist）")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "init" and args.source:
            result = init_from(args.source, args.name, args.title, args.folder or None)
            print(f"✅ {result.folder}：寫了 {'、'.join(result.written)}")
            for note in result.notes:
                print(f"  {note}")
            return 0
        if args.cmd == "init":
            if not args.folder:
                print("❌ 要給資料夾（或用 --from tool.py）")
                return 2
            written = init_pack(args.folder, args.kind, args.name, args.title or args.name)
            print(f"✅ 寫了 {len(written)} 個檔：{'、'.join(written) or '（都已經存在，沒動）'}")
            return 0
        if args.cmd == "check":
            check = Pack.load(args.folder)
            print(check.format())
            return 0 if check.ok else 2
        if args.cmd == "run":
            return run_command(args.pack, args.command, args.args, data_dir=args.data or None, as_ai=not args.typed,
                               confirmed=args.confirmed)
        if args.cmd == "zip":
            path = zip_pack(args.folder, args.out or None)
            print(f"📦 {path}")
            return 0
    except ValueError as e:
        print(f"❌ {e}")
        return 2
    parser.print_help()
    return 1
