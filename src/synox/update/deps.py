"""
啟動時把套件補齊（docs/adr/0047 §2）：這版 SYNOX 的 `pyproject.toml` 要的套件 vs `.venv` 裡裝著的。

- **要什麼**：`[project] dependencies` ＋ 使用者選的選裝組（`[project.optional-dependencies]`，`dev` 不算）。
  `name @ <wheel 網址>` 的版本從 wheel 檔名讀；`name>=x` 照範圍。
- **選了哪幾組**：`data/deps.json` 記著的 ∪ `.venv` 裡看得出來有裝的（那一組的每個套件都在；帶選裝組的要求
  例如 `ntu_easy_llm[llop]` 要它的 llop 那幾個相依也都在）。換版本、重建 .venv 都不會忘。
- **比**：沒有＝要裝；比要的舊＝要升；比要的新＝不動（不降級）；帶選裝組的少了那幾個相依＝要裝。只讀套件的版本資訊，不連網、不 import。
- **補**：有要補的才叫 `.venv` 的 pip（`--timeout 20 --retries 1`，最多 10 分鐘），裝完再比一次。
- **失敗也照常啟動**：每個沒補到的一句白話＋怎麼補；存進 `data/deps.json`（網頁卡片讀）。同一組要求失敗後 BACKOFF 內啟動不再自動重試
  （沒網路時不要每次啟動都卡在 pip）；`force=True`（網頁「再試一次」、`synox deps sync`）不受限制。
- **只看不裝**：不是 SYNOX 自己的 `.venv`（開發環境、測試）、Docker、`SYNOX_DEPS_SYNC=off`、讀不出版本規則（沒有 packaging）。

測試一律換 `have`（套件 → 版本）、`requires`（套件 → Requires-Dist）、`run`（假的 pip），不跑真的 pip、不連網。
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Tuple

STATE_FILE = "deps.json"                 # data/ 裡：{"schema_version": 1, "extras": [...], "last": {...}}
SCHEMA_VERSION = 1
SKIP_EXTRAS = ("dev",)
BACKOFF = 6 * 3600                       # 秒：同一組要求自動補失敗之後，這段時間內啟動不再自動試
PIP_TIMEOUT = 600
ENV_SWITCH = "SYNOX_DEPS_SYNC"           # off＝只看不裝
LOG_NAME = "deps-pip.log"                # data/logs/ 裡：上一次 pip 的完整輸出

Have = Callable[[str], Optional[str]]
Requires = Callable[[str], Optional[List[str]]]

TEXT = {
    "fixing": "🔧 這版 SYNOX 要的套件跟裝著的不一樣，補裝：{items}（要網路，可能要幾分鐘）…",
    "fixed": "✅ 套件補好了：{items}",
    "problem": "{name} 沒有更新到 {need}（現在是 {have}）：{why}",
    "problem_missing": "{name} 沒有裝上（這版要 {need}）：{why}",
    "how": "怎麼補：網頁「設定 → 💻 電腦與備份 → SYNOX 更新」按「再試一次」，或在 SYNOX 資料夾打 {cmd}；下次啟動 SYNOX 也會再試。",
    "how_manual": "這個 SYNOX 不是用自己的 .venv 跑的，不會自動裝。要用的話自己裝：{cmd}",
    "how_docker": "在 Docker 裡：重新建置映像檔（docker compose build）就會裝好。",
    "how_off": "自動補裝關掉了（SYNOX_DEPS_SYNC=off）。要裝：{cmd}",
    "backoff": "上次自動補裝沒成功，{h} 小時內啟動時不再自動試（不然每次啟動都要等）。",
    "why_offline": "連不到網路（或公司網路擋住了下載）",
    "why_locked": "檔案被占用或沒有權限（可能有別的程式正在用 SYNOX 的 Python）",
    "why_disk": "磁碟空間不夠",
    "why_timeout": "下載太久，先停了",
    "why_pip": "pip 安裝失敗（細節在 data/logs/" + LOG_NAME + "）",
    "why_still": "裝完版本還是不對（細節在 data/logs/" + LOG_NAME + "）",
    "why_no_pip": "叫不動 pip（{e}）",
    "unknown_have": "沒有裝",
}


# ── 要求 ──────────────────────────────────────────────────────────────

@dataclass
class Req:
    raw: str
    name: str
    extras: Tuple[str, ...] = ()
    spec: str = ""                        # ">=2.28" 之類（可以是空的）
    url: str = ""                         # name @ <url>
    marker: str = ""
    group: str = ""                       # 哪一組選裝組（""＝必要的相依）

    @property
    def key(self) -> str:
        return canonical(self.name)

    def need(self) -> str:
        """給人看的「要多少」：網址的 wheel 版本，或範圍。"""
        return url_version(self.url) or self.spec or "任何版本"


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", str(name)).lower()


_REQ_RE = re.compile(r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*(\[[^\]]*\])?\s*(.*)$")
_WHEEL_RE = re.compile(r"/([A-Za-z0-9_.]+)-([0-9][A-Za-z0-9.+!]*)-[^/]+\.whl$")


def parse_req(raw: str, group: str = "") -> Optional[Req]:
    """一行 PEP 508 要求 → Req（看不懂回 None）。只認這個專案用得到的長相：name[extras] (spec|@ url) ; marker。"""
    if not isinstance(raw, str) or not raw.strip():
        return None
    body, _sep, marker = raw.partition(";")
    m = _REQ_RE.match(body)
    if not m:
        return None
    name, extras, rest = m.group(1), m.group(2) or "", m.group(3).strip()
    ex = tuple(sorted({e.strip() for e in extras.strip("[]").split(",") if e.strip()}))
    url = spec = ""
    if rest.startswith("@"):
        url = rest[1:].strip()
        if not url:
            return None
    else:
        spec = rest.strip().strip("()").replace(" ", "")
    return Req(raw=raw.strip(), name=name, extras=ex, spec=spec, url=url, marker=marker.strip(), group=group)


def url_version(url: str) -> str:
    """wheel 網址的版本（`…/ntu_easy_llm-0.6.0a2-py3-none-any.whl` → `0.6.0a2`）；不是 wheel 回 ""。"""
    if not url:
        return ""
    m = _WHEEL_RE.search(url.split("#", 1)[0].split("?", 1)[0])
    return m.group(2) if m else ""


def project(root: str) -> Optional[dict]:
    """SYNOX 資料夾的 pyproject.toml → {"base": [Req], "extras": {組: [Req]}}；沒有或讀不了回 None。"""
    path = os.path.join(root, "pyproject.toml")
    try:
        import tomllib
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, ValueError, ImportError):
        return None
    proj = data.get("project") if isinstance(data, dict) else None
    if not isinstance(proj, dict):
        return None
    base = [r for r in (parse_req(x) for x in (proj.get("dependencies") or [])) if r]
    extras: Dict[str, List[Req]] = {}
    opt = proj.get("optional-dependencies") or {}
    if isinstance(opt, dict):
        for group, items in opt.items():
            if group in SKIP_EXTRAS or not isinstance(items, list):
                continue
            extras[group] = [r for r in (parse_req(x, group) for x in items) if r]
    return {"base": base, "extras": extras}


# ── 版本規則（packaging；pip 一定附一份）────────────────────────────────

def _packaging():
    try:
        from packaging.markers import Marker
        from packaging.specifiers import SpecifierSet
        from packaging.version import InvalidVersion, Version
    except ImportError:                                     # pragma: no cover - 看環境
        try:
            from pip._vendor.packaging.markers import Marker
            from pip._vendor.packaging.specifiers import SpecifierSet
            from pip._vendor.packaging.version import InvalidVersion, Version
        except ImportError:
            return None
    return Version, InvalidVersion, SpecifierSet, Marker


def _applies(req: Req, pk) -> bool:
    """marker（例如 `python_version < "3.12"`）在這台成不成立；看不懂＝當作要。"""
    if not req.marker or pk is None:
        return True
    try:
        return bool(pk[3](req.marker).evaluate({"extra": ""}))
    except Exception:
        return True


def _compare(have: str, req: Req, pk) -> str:
    """ok｜old（要升）｜unknown（比不出來）。網址形式：裝著的 ≥ wheel 的版本＝ok（不降級）。"""
    if pk is None:
        return "unknown"
    Version, InvalidVersion, SpecifierSet, _m = pk
    try:
        hv = Version(have)
        if req.url:
            want = url_version(req.url)
            return "unknown" if not want else ("ok" if hv >= Version(want) else "old")
        if not req.spec:
            return "ok"
        return "ok" if SpecifierSet(req.spec, prereleases=True).contains(hv, prereleases=True) else "old"
    except (InvalidVersion, ValueError, TypeError):
        return "unknown"


def _extra_reqs(name: str, extra: str, requires: Requires) -> List[Req]:
    """裝著的那個套件，它的某一組選裝組要哪些（Requires-Dist 裡 marker 寫 extra == "<組>" 的那幾行）。"""
    try:
        lines = requires(name) or []
    except Exception:
        lines = []
    out = []
    pat = re.compile(r"""extra\s*==\s*["']%s["']""" % re.escape(extra))
    for line in lines:
        body, _s, marker = str(line).partition(";")
        if pat.search(marker):
            r = parse_req(body)
            if r:
                out.append(r)
    return out


def _default_have(name: str) -> Optional[str]:
    from importlib import metadata
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None
    except Exception:
        return None


def _default_requires(name: str) -> Optional[List[str]]:
    from importlib import metadata
    try:
        return metadata.requires(name)
    except Exception:
        return None


# ── 選了哪幾組 ────────────────────────────────────────────────────────

def _present(req: Req, have: Have, requires: Requires) -> bool:
    """這個要求的套件「有裝」（不管版本）；帶選裝組的，那一組至少要有一個相依、而且都在
    （舊的 ntu_easy_llm 沒有 llop 這一組 → 不算裝了 llop）。"""
    if have(req.name) is None:
        return False
    for ex in req.extras:
        subs = _extra_reqs(req.name, ex, requires)
        if not subs or any(have(s.name) is None for s in subs):
            return False
    return True


def inferred_extras(proj: dict, have: Have, requires: Requires) -> List[str]:
    """`.venv` 裡看得出來有裝的選裝組：那一組的每個要求都 _present。"""
    out = []
    for group, reqs in (proj.get("extras") or {}).items():
        if reqs and all(_present(r, have, requires) for r in reqs):
            out.append(group)
    return sorted(out)


def chosen_extras(proj: dict, state: dict, have: Have, requires: Requires) -> List[str]:
    """記著的 ∪ 看得出來有裝的；這版沒有的組不算（但記錄留著，之後的版本又有了還會用）。"""
    known = set((proj.get("extras") or {}).keys())
    recorded = [x for x in (state.get("extras") or []) if isinstance(x, str)]
    return sorted((set(recorded) & known) | set(inferred_extras(proj, have, requires)))


# ── 比 ────────────────────────────────────────────────────────────────

@dataclass
class Item:
    name: str
    need: str
    have: str                              # 裝著的版本（沒有＝""）
    why: str                               # missing｜old｜extra_missing｜unknown
    reqs: List[Req] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name, "need": self.need, "have": self.have, "why": self.why}


def plan(proj: dict, extras: Iterable[str], have: Have, requires: Requires, pk="auto") -> List[Item]:
    """要補的套件（同一個套件的好幾個要求合成一項）。unknown（比不出版本）不算要補。"""
    pk = _packaging() if pk == "auto" else pk
    reqs = list(proj.get("base") or [])
    for group in extras:
        reqs += (proj.get("extras") or {}).get(group, [])
    rank = {"missing": 0, "old": 1, "extra_missing": 2}
    items: Dict[str, Item] = {}
    for req in reqs:
        if not _applies(req, pk):
            continue
        cur = have(req.name)
        if cur is None:
            why = "missing"
        else:
            why = _compare(cur, req, pk)
            if why == "ok":
                for ex in req.extras:
                    subs = _extra_reqs(req.name, ex, requires)
                    if not subs or any(have(s.name) is None for s in subs):
                        why = "extra_missing"
        if why in ("ok", "unknown"):
            if why == "unknown":
                logging.info("[DEPS] cannot compare %s %s with %s", req.name, cur, req.need())
            continue
        item = items.get(req.key)
        if item is None:
            items[req.key] = Item(name=req.name, need=req.need(), have=cur or "", why=why, reqs=[req])
        else:
            item.reqs.append(req)
            if rank[why] < rank[item.why]:
                item.why = why
            if url_version(req.url):
                item.need = req.need()
    return list(items.values())


def pip_args(items: Iterable[Item]) -> List[str]:
    """要交給 pip 的要求：同一個套件合成一行（選裝組合起來；有網址用網址，否則把範圍接起來）。"""
    out = []
    for item in items:
        extras = sorted({e for r in item.reqs for e in r.extras})
        ex = f"[{','.join(extras)}]" if extras else ""
        urls = sorted({r.url for r in item.reqs if r.url})
        if len(urls) == 1:
            out.append(f"{item.reqs[0].name}{ex} @ {urls[0]}")
        elif urls:                                           # 兩個不一樣的網址：各自一行，交給 pip 說
            out += [f"{item.reqs[0].name}{ex} @ {u}" for u in urls]
        else:
            specs = ",".join(sorted({r.spec for r in item.reqs if r.spec}))
            out.append(f"{item.reqs[0].name}{ex}{specs}")
    return out


def plan_key(items: Iterable[Item]) -> str:
    return "|".join(sorted(pip_args(items)))


# ── 狀態檔（data/deps.json）──────────────────────────────────────────────

def load_state(data_dir: str) -> dict:
    try:
        with open(os.path.join(data_dir, STATE_FILE), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("schema_version") not in (None, SCHEMA_VERSION):
        return {}                                            # 比較新的版本寫的：不讀、也不覆蓋（save_state 看這個）
    return data


def save_state(data_dir: str, state: dict) -> None:
    path = os.path.join(data_dir, STATE_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            old = json.load(f)
        if isinstance(old, dict) and isinstance(old.get("schema_version"), int) and old["schema_version"] > SCHEMA_VERSION:
            logging.warning("[DEPS] %s was written by a newer SYNOX: not overwritten", path)
            return
    except (OSError, ValueError):
        pass
    os.makedirs(data_dir, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({**state, "schema_version": SCHEMA_VERSION}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def set_extras(data_dir: str, add: Iterable[str] = (), remove: Iterable[str] = ()) -> List[str]:
    """改記著的選裝組（synox deps sync --add／--remove）。回傳改完的。"""
    state = load_state(data_dir)
    now = set(x for x in (state.get("extras") or []) if isinstance(x, str))
    now = (now | {a for a in add if a}) - {r for r in remove if r}
    removed = sorted(set(state.get("removed") or []) - set(add) | set(remove))
    state["extras"], state["removed"] = sorted(now), removed
    save_state(data_dir, state)
    return state["extras"]


# ── 能不能自己裝 ──────────────────────────────────────────────────────

def own_venv(root: str, prefix: Optional[str] = None) -> bool:
    """現在跑的 Python 是不是這個 SYNOX 資料夾自己的 .venv。"""
    here = os.path.normcase(os.path.abspath(prefix if prefix is not None else sys.prefix))
    return here == os.path.normcase(os.path.abspath(os.path.join(root, ".venv")))


def venv_python_hint(root: str) -> str:
    return r".venv\Scripts\python.exe" if os.name == "nt" else ".venv/bin/python"


def install_mode(root: str, prefix: Optional[str] = None, environ=None) -> str:
    """auto（自己裝）｜off（SYNOX_DEPS_SYNC=off）｜docker｜manual（不是自己的 .venv）。"""
    env = os.environ if environ is None else environ
    if str(env.get(ENV_SWITCH, "")).strip().lower() in ("off", "0", "no", "false"):
        return "off"
    if env.get("SYNOX_IN_DOCKER") == "1" or env.get("SYNOX_IN_CONTAINER") == "1":
        return "docker"
    return "auto" if own_venv(root, prefix) else "manual"


def _why_from_output(text: str) -> str:
    t = text or ""
    if re.search(r"NewConnectionError|Failed to establish|Could not resolve|getaddrinfo|Name or service not known|"
                 r"ConnectionError|No route to host|Network is unreachable|ProxyError|ConnectTimeout", t):
        return TEXT["why_offline"]
    if re.search(r"Permission denied|WinError 5|Access is denied|WinError 32|being used by another process", t):
        return TEXT["why_locked"]
    if re.search(r"No space left|WinError 112|not enough space", t, re.I):
        return TEXT["why_disk"]
    if re.search(r"Read timed out|timed out", t):
        return TEXT["why_timeout"]
    return TEXT["why_pip"]


def _problem_line(item: Item, why: str) -> str:
    if not item.have:
        return TEXT["problem_missing"].format(name=item.name, need=item.need, why=why)
    return TEXT["problem"].format(name=item.name, need=item.need, have=item.have, why=why)


def _items_text(items: Iterable[Item]) -> str:
    return "、".join(f"{i.name} {i.have or TEXT['unknown_have']} → {i.need}" for i in items)


def _write_log(data_dir: str, text: str) -> None:
    try:
        folder = os.path.join(data_dir, "logs")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, LOG_NAME), "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass


# ── 主流程 ────────────────────────────────────────────────────────────

def sync(root: str, data_dir: str, *, say: Callable[[str], None] = print, run=subprocess.run,
         have: Optional[Have] = None, requires: Optional[Requires] = None, python: Optional[str] = None,
         prefix: Optional[str] = None, environ=None, clock=time.time, force: bool = False, pk="auto") -> dict:
    """比 → （需要、而且可以的話）補 → 再比。**從不丟例外**（出錯＝回 ok False 的結果、記 log），所以 SYNOX 照常啟動。
    回傳（也存進 data/deps.json 的 last）：
      {"at", "ok", "mode", "extras", "fixed": [Item], "problems": [Item＋line], "lines": [給人看的], "how", "key"}"""
    try:
        return _sync(root, data_dir, say=say, run=run, have=have or _default_have,
                     requires=requires or _default_requires, python=python or sys.executable, prefix=prefix,
                     environ=environ, clock=clock, force=force, pk=pk)
    except Exception as e:                                   # 什麼都不能讓 SYNOX 起不來
        logging.exception("[DEPS] dependency check failed")
        return {"at": clock(), "ok": False, "mode": "error", "extras": [], "fixed": [], "problems": [],
                "lines": [f"⚠️ 檢查套件時出錯，先照常啟動（{type(e).__name__}）。"], "how": "", "key": ""}


def _sync(root, data_dir, *, say, run, have, requires, python, prefix, environ, clock, force, pk) -> dict:
    now = clock()
    result = {"at": now, "ok": True, "mode": "", "extras": [], "fixed": [], "problems": [], "lines": [], "how": "",
              "key": ""}
    proj = project(root)
    if proj is None:
        result["mode"] = "skipped"
        return result
    state = load_state(data_dir)
    extras = [x for x in chosen_extras(proj, state, have, requires) if x not in (state.get("removed") or [])]
    result["extras"] = extras
    if extras != state.get("extras"):
        state["extras"] = extras
    pk = _packaging() if pk == "auto" else pk
    todo = plan(proj, extras, have, requires, pk=pk)
    mode = install_mode(root, prefix, environ)
    result["mode"] = mode
    if not todo:
        state["last"] = result
        _save_quietly(data_dir, state)
        return result
    args = pip_args(todo)
    key = "|".join(sorted(args))
    result["key"] = key
    cmd_hint = f"{venv_python_hint(root)} -m synox deps sync"
    if mode != "auto":
        pip_cmd = f'{venv_python_hint(root)} -m pip install ' + " ".join(f'"{a}"' for a in args)
        how = {"off": TEXT["how_off"].format(cmd=pip_cmd), "docker": TEXT["how_docker"]}.get(
            mode, TEXT["how_manual"].format(cmd=pip_cmd))
        return _finish(data_dir, state, result, todo, {i.name: "沒有自動裝" for i in todo}, how, say, log=mode != "manual")
    last = state.get("last") if isinstance(state.get("last"), dict) else {}
    if not force and last.get("key") == key and not last.get("ok") and isinstance(last.get("at"), (int, float)) \
            and now - float(last["at"]) < BACKOFF:
        hours = max(1, int(round((BACKOFF - (now - float(last["at"]))) / 3600)))
        whys = {p.get("name"): p.get("reason") for p in last.get("problems") or [] if isinstance(p, dict)}
        result["at"] = last["at"]                            # 退避從第一次失敗算
        res = _finish(data_dir, state, result, todo, {i.name: whys.get(i.name) or TEXT["why_pip"] for i in todo},
                      TEXT["how"].format(cmd=cmd_hint), say)
        res["lines"].append(TEXT["backoff"].format(h=hours))
        say(res["lines"][-1])
        return res

    say(TEXT["fixing"].format(items=_items_text(todo)))
    cmd = [python, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--timeout", "20",
           "--retries", "1", *args]
    env = dict(os.environ if environ is None else environ)
    env["PIP_NO_INPUT"] = "1"
    env.pop("PIP_USER", None)
    output, why = "", ""
    try:
        proc = run(cmd, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
                   timeout=PIP_TIMEOUT, env=env)
        output = f"$ {' '.join(cmd)}\n{proc.stdout or ''}\n{proc.stderr or ''}"
        if proc.returncode != 0:
            why = _why_from_output(output)
    except subprocess.TimeoutExpired as e:
        output, why = f"$ {' '.join(cmd)}\ntimeout\n{e}", TEXT["why_timeout"]
    except OSError as e:
        output, why = f"$ {' '.join(cmd)}\n{e}", TEXT["why_no_pip"].format(e=e)
    _write_log(data_dir, output)
    logging.info("[DEPS] pip install %s -> %s", args, why or "ok")
    after = plan(proj, extras, have, requires, pk=pk)
    left = {canonical(i.name) for i in after}
    fixed = [i for i in todo if canonical(i.name) not in left]
    result["fixed"] = [i.to_dict() for i in fixed]
    if fixed:
        result["lines"].append(TEXT["fixed"].format(items=_items_text(fixed)))
        say(result["lines"][-1])
    if not after:
        state["last"] = result
        _save_quietly(data_dir, state)
        return result
    reasons = {i.name: (why or TEXT["why_still"]) for i in after}
    return _finish(data_dir, state, result, after, reasons, TEXT["how"].format(cmd=cmd_hint), say)


def _finish(data_dir, state, result, items, reasons, how, say, log=True) -> dict:
    result["ok"] = False
    result["how"] = how
    for item in items:
        why = reasons.get(item.name) or TEXT["why_pip"]
        line = _problem_line(item, why)
        result["problems"].append({**item.to_dict(), "reason": why, "line": line})
        result["lines"].append("⚠️ " + line)
        if log:
            say("⚠️ " + line)
        logging.warning("[DEPS] %s", line)
    result["lines"].append(how)
    if log:
        say(how)
    state["last"] = result
    _save_quietly(data_dir, state)
    return result


def _save_quietly(data_dir: str, state: dict) -> None:
    try:
        save_state(data_dir, state)
    except OSError:
        logging.warning("[DEPS] cannot save %s", STATE_FILE, exc_info=True)


def last_result(data_dir: str) -> Optional[dict]:
    """網頁卡片用：上一次的結果（沒有＝None）。"""
    last = load_state(data_dir).get("last")
    return last if isinstance(last, dict) else None


def status(root: str, data_dir: str, *, have: Optional[Have] = None, requires: Optional[Requires] = None,
           pk="auto") -> dict:
    """只看（synox deps）：這版要的、選了哪幾組、哪些要補。不寫檔、不裝。"""
    have, requires = have or _default_have, requires or _default_requires
    proj = project(root)
    if proj is None:
        return {"ok": True, "extras": [], "todo": [], "available": [], "note": "沒有 pyproject.toml"}
    state = load_state(data_dir)
    extras = [x for x in chosen_extras(proj, state, have, requires) if x not in (state.get("removed") or [])]
    todo = plan(proj, extras, have, requires, pk=pk)
    return {"ok": not todo, "extras": extras, "available": sorted((proj.get("extras") or {}).keys()),
            "todo": [{**i.to_dict(), "pip": pip_args([i])} for i in todo]}


__all__ = ["Item", "Req", "STATE_FILE", "SCHEMA_VERSION", "TEXT", "chosen_extras", "inferred_extras", "install_mode",
           "last_result", "load_state", "own_venv", "parse_req", "pip_args", "plan", "project", "save_state",
           "set_extras", "status", "sync", "url_version"]
