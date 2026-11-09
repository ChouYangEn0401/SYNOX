"""
信任層級（SDK P7）：這個 pack 的程式，第 2 關的靜態掃描看得到多少。

    T0  只有宣告：connector、只登記的 mcp（遠端 MCP）——沒有程式在這台跑（有附程式檔第 2 關就拒）
    T1  原始碼：會被執行的只有第 2 關掃過的 .py／.pyw（{python} 只准跑 pack 裡的 .py，審查 C #C1）；
        其他檔第 2 關當資料（沒有副檔名、ast 解析得過的也當 .py 掃）。掃描是提醒不是門：T1 不等於「安全」
    T2  二進位或外部相依（掃不到）：資料夾裡有掃不到內容的檔（scan.opaque_files：.exe .dll .bat .sh .so .pyc、
        .pyz .zip .whl .egg、
        別的語言的原始碼 .js .ts .rb .php .go…（scan.SOURCE_EXT）、node_modules、MZ／ELF 檔頭…）、
        argv 指到 pack 外的程式（scan.externals：{node}、npx、node、git、絕對路徑、{python} -m 外部模組、
        {python} 解析到 pack 外的直譯器（cli.python、"venv"、runtime.python 指到外面））、
        argv 直接執行程式碼（{python} -c、powershell -Command、cmd /c、node -e…；scan.inline_code，另外要宣告 exec）、
        或 runtime auto 會裝套件（envs.all_pins：requires.pip、package-lock.json）

T2 要多的：
- 第 2 關：資料夾裡掃不到內容的檔要宣告 exec（scan.py）；外部程式、套件不擋，但報告列出來
- 安裝：安裝者要「明確輸入 pack.json 的 publisher」（網頁勾選＋輸入、終端機 --trust-publisher <名字>）才裝；
  寫進 packs.lock 的 trusted_publisher／trusted_at（confirm_problem）
- 升級：publisher 變了、新增 exec、或可執行的東西變多 → 紅字，要重新輸入（reconfirm_reasons）；都沒有就沿用舊的確認
- 執行期：伺服器版一律要真隔離（sandbox.required：T2 一定命中，不管 trust、required_for）；沒有＝只對擁有者可見；
  python pack 在 SYNOX 程序裡跑、沙盒包不到，T2 python pack 在伺服器版一律只給擁有者。個人版照用，doctor 提醒

**T2 不是沙盒保證，只是讓你知道你在信任誰**（docs/security.md「信任層級」）。publisher 是作者自己寫的字，
沒有簽章驗證之前，它只是「你明確說了你信這個名字」，不能證明檔案真的出自那個人。
"""

from __future__ import annotations

import time
from typing import List, Optional

T0, T1, T2 = "T0", "T1", "T2"
TIERS = (T0, T1, T2)
TEXT = {T0: "T0 只有宣告（沒有程式在這台跑）", T1: "T1 原始碼（會執行的只有第 2 關掃過的 .py）",
        T2: "T2 二進位或外部相依（第 2 關掃不到）"}


def assess(m, report=None, exec_bits=()) -> dict:
    """這個 pack 是哪一層＋T2 的細節。report（ScanReport）有給就用它的 opaque／external，沒給現算（只讀檔頭、不執行）。
    回 {"tier", "text", "opaque", "external", "packages", "runs", "publisher", "needs_publisher"}；
    runs＝會執行、掃不到內容的東西（資料夾裡的檔路徑＋外部程式），升級時比「變多了沒」用這個。"""
    from synox.packs import envs
    from synox.packs import scan as pack_scan
    opaque = list(report.opaque) if report is not None else pack_scan.opaque_files(m.folder, exec_bits)
    external = list(report.external) if report is not None else pack_scan.externals(m)
    try:
        packages = envs.all_pins(m)
    except Exception:                                # pack.json 怪怪的：當作沒有套件（第 1 關會擋）
        packages = []
    if getattr(m, "registered_only", False) or getattr(m, "mcp_http", False):
        tier = T0                                    # 遠端 MCP（http）也是：這台不跑它的程式，附程式檔第 2 關就拒
    elif opaque or external or packages:
        tier = T2
    else:
        tier = T1
    runs = [o["path"] for o in opaque] + [e["program"] for e in external]
    return {"tier": tier, "text": TEXT[tier], "opaque": opaque, "external": external, "packages": packages,
            "runs": runs, "publisher": getattr(m, "publisher", "") or "", "needs_publisher": tier == T2}


def is_t2(m) -> bool:
    try:
        return assess(m)["tier"] == T2
    except OSError:
        return True                                  # 讀不了就不能說它掃得到


PIN_NOT_SOURCE = ("版本釘選不等於來源可信：沒有 --hash 的套件，裝到的是 PyPI 當下給的那個檔"
                  "（被換掉、被搶註名字都看不出來）；請作者在 requires.pip 補 --hash=sha256:…")


def hash_lines(pkgs: List[dict]) -> List[str]:
    """pip 套件逐一列「有／沒有雜湊」；有沒寫雜湊的 → 再加一行 PIN_NOT_SOURCE（審查 B #C）。npm 的照 package-lock 的 integrity，不列。"""
    pip = [p for p in pkgs if p.get("source") == "pip"]
    if not pip:
        return []
    marks = "、".join(f"{p['name']} {p['version']}（{'有雜湊' if p.get('hashed') else '沒有雜湊'}）" for p in pip[:30])
    out = [f"pip 套件的雜湊：{marks}" + ("…" if len(pip) > 30 else "")]
    if any(not p.get("hashed") for p in pip):
        out.append(PIN_NOT_SOURCE)
    return out


def warning_lines(info: dict) -> List[str]:
    """安裝報告（終端機、網頁）的紅字那一段；不是 T2 回 []。"""
    if info.get("tier") != T2:
        return []
    out: List[str] = []
    runs = info.get("runs") or []
    if runs:
        out.append("這個 pack 會執行：" + "、".join(runs[:20]) + ("…" if len(runs) > 20 else "") + "（掃不到內容）")
    for e in info.get("external") or []:
        if e.get("inline"):
            out.append(f"argv 直接執行程式碼：{e['resolved']}（{e.get('where', '')}；第 2 關掃不到這段程式碼）")
            continue
        kind = f"直譯器 {e['interpreter']}" if e.get("interpreter") else "pack 外的程式"
        out.append(f"{kind} {e['program']} → {e['resolved']}（未鎖定執行環境：不在 packs.lock 的雜湊裡）")
    pkgs = info.get("packages") or []
    if pkgs:
        names = "、".join(f"{p['name']} {p['version']}" for p in pkgs[:30]) + ("…" if len(pkgs) > 30 else "")
        out.append(f"會安裝 {len(pkgs)} 個套件（來自 runtime auto）：{names}")
        out += hash_lines(pkgs)
    publisher = info.get("publisher") or ""
    if publisher:
        out.append(f"要裝就明確輸入發行者「{publisher}」（終端機 --trust-publisher \"{publisher}\"；網頁勾選後輸入）——"
                   "T2 不是沙盒保證，只是讓你知道你在信任誰")
    else:
        out.append("pack.json 沒寫 publisher：T2 pack 不能裝（請作者補上 publisher）")
    out.append("第三方的執行檔／npm 套件建議在別台機器或隔離環境先測過")
    return out


def confirm_problem(info: dict, m, typed: Optional[str]) -> Optional[str]:
    """T2 的安裝確認：typed 要跟 pack.json 的 publisher 一字不差（前後空白不算）。不是 T2 回 None；合格回 None。"""
    if info.get("tier") != T2:
        return None
    publisher = (getattr(m, "publisher", "") or "").strip()
    runs = "、".join((info.get("runs") or [])[:5]) or "runtime auto 的套件"
    if not publisher:
        return f"這是 T2 pack（會執行掃不到內容的東西：{runs}），pack.json 沒寫 publisher，不能裝（請作者補上 publisher）"
    if not typed or not str(typed).strip():
        return (f"這是 T2 pack（會執行掃不到內容的東西：{runs}）：要明確輸入發行者「{publisher}」才裝"
                f"（終端機加 --trust-publisher \"{publisher}\"；網頁勾選「我信任這個發行者」並輸入名字）")
    if str(typed).strip() != publisher:
        return f"輸入的發行者 {str(typed).strip()!r} 跟 pack.json 的 publisher {publisher!r} 不一樣，不裝"
    return None


def reconfirm_reasons(old_lock: Optional[dict], old_m, new_m, info: dict) -> List[str]:
    """升級（或重新核准）時要不要重新輸入發行者：新版是 T2，而且（舊的鎖沒有確認過發行者｜publisher 變了｜
    新增了 exec｜可執行的東西變多）→ 每個原因一句；[]＝沿用舊的確認（或新版不是 T2）。"""
    if info.get("tier") != T2:
        return []
    old_lock = old_lock or {}
    trusted = old_lock.get("trusted_publisher") or ""
    if not trusted:
        before = old_lock.get("tier") or "沒有鎖"
        return [f"新版是 T2（會執行掃不到內容的東西），舊的那一份（{before}）沒有確認過發行者"]
    out: List[str] = []
    publisher = getattr(new_m, "publisher", "") or ""
    if publisher != trusted:
        out.append(f"發行者變了：{trusted} → {publisher or '（沒寫）'}")
    old_caps = list(getattr(old_m, "capabilities", []) or []) if old_m is not None else []
    if "exec" in (getattr(new_m, "capabilities", []) or []) and "exec" not in old_caps:
        out.append("新增了 exec（會執行掃不到內容的東西）")
    old_runs = set(((old_lock.get("t2") or {}).get("runs")) or [])
    added = [r for r in info.get("runs") or [] if r not in old_runs]
    if added:
        out.append("可執行的東西變多了：" + "、".join(added[:10]) + ("…" if len(added) > 10 else ""))
    return out


def lock_fields(info: dict, trusted_publisher: Optional[str], *, previous: Optional[dict] = None,
                now: Optional[float] = None) -> dict:
    """寫進 packs.lock 的那幾個欄位：tier、t2（opaque／external／packages／runs）、trusted_publisher、trusted_at。
    trusted_publisher=None 而且 previous（舊鎖）有確認過 → 沿用舊的（呼叫的人先確認過不用重新確認）。"""
    out = {"tier": info.get("tier", T1)}
    if info.get("tier") != T2:
        return out
    out["t2"] = {"opaque": info.get("opaque") or [], "external": info.get("external") or [],
                 "packages": info.get("packages") or [], "runs": info.get("runs") or []}
    if trusted_publisher:
        out["trusted_publisher"] = str(trusted_publisher).strip()
        out["trusted_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now))
    elif previous and previous.get("trusted_publisher"):
        out["trusted_publisher"] = previous["trusted_publisher"]
        out["trusted_at"] = previous.get("trusted_at", "")
    return out
