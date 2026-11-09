"""
pack.json 的格式與檢查（docs/pack-format.md 是人看的版本）。

    {
      "name": "money", "title": "💰 記帳", "summary": "記一筆、看這個月、設預算",
      "version": "0.1.0", "kind": "python",
      "group": "money",                          指令群組（/money、/money_list…）；沒寫＝name
      "access": "owner",                         owner（預設：只有你）｜everyone（任何傳訊息給 bot 的人）
      "python": {"module": "pack"},              kind=python：資料夾裡的 pack.py，有 install(app, pack)
      "cli": {"argv": ["python", "-m", "x"], "cwd": ".", "commands": [...]},   kind=cli
      "auth": "oauth",                           kind=connector：oauth｜token｜caldav
      "requires": {"pip": [], "config": [], "env": {}},
      "skill": "SKILL.md",
      "storage": "vault"                         vault（pack.store 落地是密文）｜plain
    }
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

KINDS = ("python", "cli", "connector")
AUTHS = ("oauth", "token", "caldav")
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
GROUP_RE = re.compile(r"^[a-z][a-z0-9]{0,15}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([.-][0-9A-Za-z.-]+)?$")


class ManifestError(ValueError):
    pass


@dataclass
class Manifest:
    name: str
    title: str
    summary: str
    version: str
    kind: str
    folder: str
    group: str = ""
    access: str = "owner"
    skill: str = "SKILL.md"
    storage: str = "plain"
    python: dict = field(default_factory=dict)
    cli: dict = field(default_factory=dict)
    auth: str = ""
    requires: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def skill_path(self) -> str:
        return os.path.join(self.folder, self.skill)


def validate(raw: dict, folder: str) -> Manifest:
    """raw（pack.json 的內容）→ Manifest；不合就丟 ManifestError（訊息說哪裡不對）。"""
    problems: List[str] = []
    if not isinstance(raw, dict):
        raise ManifestError("pack.json 最外層要是 {…} 物件")
    for key in ("name", "title", "summary", "version", "kind"):
        if not isinstance(raw.get(key), str) or not raw.get(key).strip():
            problems.append(f"少了 {key}")
    name = str(raw.get("name", ""))
    if name and not NAME_RE.match(name):
        problems.append(f"name {name!r} 只能用小寫英數字、-、_（32 字內）")
    version = str(raw.get("version", ""))
    if version and not VERSION_RE.match(version):
        problems.append(f"version {version!r} 要像 0.1.0")
    kind = raw.get("kind")
    if kind and kind not in KINDS:
        problems.append(f"kind 只能是 {'、'.join(KINDS)}（現在是 {kind!r}）")
    group = str(raw.get("group") or name.replace("-", "").replace("_", ""))
    if group and not GROUP_RE.match(group):
        problems.append(f"group {group!r} 只能用小寫英數字（16 字內）")
    access = raw.get("access", "owner")
    if access not in ("owner", "everyone"):
        problems.append("access 只能是 owner 或 everyone")
    storage = raw.get("storage", "plain")
    if storage not in ("vault", "plain"):
        problems.append("storage 只能是 vault 或 plain")
    skill = raw.get("skill", "SKILL.md")
    if not isinstance(skill, str) or not os.path.isfile(os.path.join(folder, skill)):
        problems.append(f"找不到 skill 檔 {skill}")
    if kind == "python":
        module = (raw.get("python") or {}).get("module", "pack")
        if not os.path.isfile(os.path.join(folder, f"{module}.py")):
            problems.append(f"kind=python 但找不到 {module}.py")
    if kind == "cli":
        cli = raw.get("cli") or {}
        if not isinstance(cli.get("argv"), list) or not cli.get("argv"):
            problems.append("kind=cli 要有 cli.argv（命令列程式的前幾段）")
        if not isinstance(cli.get("commands"), list) or not cli.get("commands"):
            problems.append("kind=cli 要有 cli.commands（至少一個子指令）")
    if kind == "connector" and raw.get("auth") not in AUTHS:
        problems.append(f"kind=connector 要寫 auth（{'、'.join(AUTHS)}）")
    requires = raw.get("requires") or {}
    if not isinstance(requires, dict):
        problems.append("requires 要是物件")
    if problems:
        raise ManifestError("；".join(problems))
    return Manifest(name=name, title=raw["title"], summary=raw["summary"], version=version, kind=kind,
                    folder=folder, group=group, access=access, skill=skill, storage=storage,
                    python=dict(raw.get("python") or {}), cli=dict(raw.get("cli") or {}), auth=raw.get("auth", ""),
                    requires=dict(requires), raw=dict(raw))


def read(folder: str) -> Manifest:
    path = os.path.join(folder, "pack.json")
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)
    except OSError as e:
        raise ManifestError(f"讀不到 pack.json：{e}")
    except ValueError as e:
        raise ManifestError(f"pack.json 不是合法的 JSON：{e}")
    return validate(raw, folder)


def missing_requirements(m: Manifest, config) -> Optional[str]:
    """requires.config（config.json 要有的欄位）、requires.env（環境變數）缺了哪些；沒缺回 None。"""
    missing = [k for k in (m.requires.get("config") or []) if not config.get(k)]
    missing += [f"環境變數 {k}" for k in (m.requires.get("env") or {}) if not os.environ.get(k)]
    return "、".join(missing) if missing else None
