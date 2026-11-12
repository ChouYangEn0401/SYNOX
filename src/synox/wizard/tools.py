"""
工具庫（SYNOX_Libs 打包好的 `.synoxpack`＋目錄 `index.json`）：找位置、讀目錄、驗雜湊、挑要裝的。

`synox init`（init_cli.py）與 `synox tools list｜install`（__main__.py）共用；安裝本身照舊走 packs/admin.py 的五關，
這裡只負責「從目錄找到那個檔、確認檔案跟目錄寫的一樣」。

- 工具庫的位置：config.json 的 `packs.library`（相對於 SYNOX 資料夾，或絕對路徑；網址只能顯示，不會自動下載）；
  沒寫時預設是發佈物旁邊的 `tools/`（DEFAULT_FOLDER；packs/library.py 的 `library_location` 同一個規則）。
- 不連網、不自動全裝：一律由使用者挑（名字或建議組合 `bundles`）。
- 檔名只收目錄同層的 `<名字>-<版本>.synoxpack`（不准子資料夾、`..`）；sha256 跟 `index.json` 不一樣＝拒。
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

DEFAULT_FOLDER = "tools"          # 發佈物（zip／安裝程式）旁邊附的工具庫資料夾；相對於 SYNOX 資料夾
INDEX = "index.json"
PACK_EXT = ".synoxpack"
MAX_INDEX_BYTES = 2 * 1024 * 1024


class LibraryError(ValueError):
    """給人看的錯誤（位置不對、目錄壞了、檔案對不上）。"""


@dataclass
class Entry:
    name: str
    version: str
    title: str
    summary: str
    file: str
    sha256: str
    bundles: List[str] = field(default_factory=list)
    requires: Dict[str, str] = field(default_factory=dict)
    capabilities: List[str] = field(default_factory=list)


@dataclass
class Library:
    folder: str
    entries: List[Entry]
    bundles: Dict[str, dict]
    version: str = ""

    def by_name(self) -> Dict[str, Entry]:
        return {e.name: e for e in self.entries}


def is_url(location: str) -> bool:
    return location.strip().lower().startswith(("https://", "http://"))


def resolve(location: str, root: str) -> str:
    """config 寫的位置 → 絕對路徑（相對的以 SYNOX 資料夾為準）；網址原樣。"""
    location = (location or "").strip()
    if not location or is_url(location):
        return location
    return os.path.normpath(location if os.path.isabs(location) else os.path.join(root, location))


def default_location(root: str) -> str:
    """SYNOX 資料夾旁邊附的 tools/（有 index.json 才算）；沒有回 ""。"""
    folder = os.path.join(root, DEFAULT_FOLDER)
    return folder if os.path.isfile(os.path.join(folder, INDEX)) else ""


def configured(config_packs: Optional[dict], root: str) -> str:
    """config.json packs.library → 絕對路徑或網址；沒寫就看預設的 tools/；都沒有回 ""。"""
    raw = (config_packs or {}).get("library") or ""
    if isinstance(raw, str) and raw.strip():
        return resolve(raw, root)
    return default_location(root)


def to_config_value(folder: str, root: str) -> str:
    """寫進 config.json 的值：在 SYNOX 資料夾裡面就寫相對路徑（搬整個資料夾也不會斷），外面才寫絕對路徑。"""
    if is_url(folder):
        return folder.strip()
    folder = os.path.abspath(folder)
    try:
        rel = os.path.relpath(folder, os.path.abspath(root))
    except ValueError:                       # 不同磁碟機
        return folder
    if rel == os.curdir:
        return "."
    if rel.startswith(os.pardir):
        return folder
    return rel.replace(os.sep, "/")


def why_not_library(folder: str) -> str:
    """這個資料夾不是打包好的工具庫的原因（給人看）；是的話回 ""。"""
    if is_url(folder):
        return ("工具庫是網址：SYNOX 不會自動下載。請用瀏覽器下載整個 tools 資料夾（.synoxpack＋index.json）"
                "放到 SYNOX 資料夾裡的 tools\\，再跑一次")
    if not os.path.isdir(folder):
        return f"資料夾不存在：{folder}"
    if os.path.isfile(os.path.join(folder, INDEX)):
        return ""
    if os.path.isdir(os.path.join(folder, "packs")) and os.path.isdir(os.path.join(folder, "scripts")):
        return (f"{folder} 看起來是工具庫的原始碼（SYNOX_Libs repo），不是打包好的工具：先在那裡跑 "
                "scripts\\build.py 產生 dist\\，再指到 dist\\；或下載發佈好的 tools 資料夾")
    if os.path.isfile(os.path.join(folder, "dist", INDEX)):
        return f"{folder} 底下有 dist\\{INDEX}：請指到 {os.path.join(folder, 'dist')}"
    return f"{folder} 裡沒有 {INDEX}（工具庫的目錄）"


def _str(value) -> str:
    return value if isinstance(value, str) else ""


def read(folder: str) -> Library:
    """讀 index.json；格式不對丟 LibraryError（不執行、不解壓任何東西）。"""
    problem = why_not_library(folder)
    if problem:
        raise LibraryError(problem)
    path = os.path.join(folder, INDEX)
    try:
        if os.path.getsize(path) > MAX_INDEX_BYTES:
            raise LibraryError(f"{path} 太大，不像工具庫的目錄")
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        raise LibraryError(f"讀不了 {path}：{e}")
    if not isinstance(raw, dict) or not isinstance(raw.get("packs"), list):
        raise LibraryError(f"{path} 不是工具庫的目錄（要有 packs 清單）")
    entries: List[Entry] = []
    for item in raw["packs"]:
        if not isinstance(item, dict) or not _str(item.get("name")) or not _str(item.get("file")):
            continue
        entries.append(Entry(name=item["name"], version=_str(item.get("version")), title=_str(item.get("title")),
                             summary=_str(item.get("summary")), file=item["file"], sha256=_str(item.get("sha256")),
                             bundles=[b for b in item.get("bundles") or [] if isinstance(b, str)],
                             requires={k: v for k, v in (item.get("requires") or {}).items()
                                       if isinstance(k, str) and isinstance(v, str)},
                             capabilities=[c for c in item.get("capabilities") or [] if isinstance(c, str)]))
    bundles = {k: v for k, v in (raw.get("bundles") or {}).items() if isinstance(k, str) and isinstance(v, dict)}
    return Library(folder=folder, entries=entries, bundles=bundles, version=_str(raw.get("library_version")))


def file_of(lib: Library, entry: Entry) -> str:
    """那個工具的 .synoxpack 的完整路徑；檔名不安全、檔案不在、雜湊不合丟 LibraryError。"""
    name = entry.file
    if (os.path.basename(name) != name or name in (".", "..") or "/" in name or "\\" in name
            or not name.lower().endswith(PACK_EXT)):
        raise LibraryError(f"目錄裡 {entry.name} 的檔名不合規定：{name!r}")
    path = os.path.join(lib.folder, name)
    if not os.path.isfile(path):
        raise LibraryError(f"目錄列了 {name}，但工具庫資料夾裡沒有這個檔")
    if not entry.sha256:
        raise LibraryError(f"目錄裡 {entry.name} 沒有寫 sha256，不裝（拿不準檔案有沒有被換過）")
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    if digest.hexdigest().lower() != entry.sha256.lower():
        raise LibraryError(f"{name} 的雜湊跟目錄寫的不一樣（檔案被換過或沒下載完整），不裝")
    return path


def pick(lib: Library, words: Iterable[str]) -> Tuple[List[Entry], List[str]]:
    """使用者打的字（工具名字、建議組合的代號，逗號或空白分開）→ (要裝的工具, 不認得的字)。
    "none"／空白＝一個都不裝；不支援「全部」——要什麼自己挑。"""
    names = lib.by_name()
    chosen: List[Entry] = []
    unknown: List[str] = []
    for raw in words:
        for word in raw.replace("，", ",").replace(",", " ").split():
            key = word.strip()
            if not key or key.lower() in ("none", "no", "skip"):
                continue
            if key in names:
                targets = [key]
            elif key in lib.bundles:
                targets = [n for n in lib.bundles[key].get("packs") or [] if n in names]
            else:
                unknown.append(key)
                continue
            for n in targets:
                if names[n] not in chosen:
                    chosen.append(names[n])
    return chosen, unknown


def installed_names(packs_dir: str) -> set:
    """使用者裝的工具（packs/ 底下有 pack.json 的資料夾；_removed 之類 _ 開頭的不算）→ 名字。"""
    out = set()
    if not os.path.isdir(packs_dir):
        return out
    for name in os.listdir(packs_dir):
        folder = os.path.join(packs_dir, name)
        if name.startswith("_") or not os.path.isfile(os.path.join(folder, "pack.json")):
            continue
        try:
            with open(os.path.join(folder, "pack.json"), "r", encoding="utf-8-sig") as f:
                out.add(json.load(f).get("name") or name)
        except (OSError, ValueError, AttributeError):
            out.add(name)
    return out


def list_lines(lib: Library, installed: Iterable[str] = ()) -> List[str]:
    """`synox tools list`／init 的清單（給人看）。"""
    have = set(installed)
    lines = [f"工具庫：{lib.folder}" + (f"（版本 {lib.version}）" if lib.version else "")]
    for e in lib.entries:
        mark = "✅ 已裝" if e.name in have else "  "
        sdk = e.requires.get("sdk")
        lines.append(f"  {mark} {e.name} {e.version}　{e.title or ''}　{e.summary or ''}".rstrip()
                     + (f"（SDK {sdk}）" if sdk else ""))
    if lib.bundles:
        lines.append("建議組合（打代號就一次選好裡面的工具；只是建議）：")
        for key, b in lib.bundles.items():
            packs = "、".join(p for p in b.get("packs") or [] if isinstance(p, str))
            lines.append(f"  {key}：{b.get('title') or ''}（{packs}）")
    return lines
