"""每個宣告了 web.app 的工具 → AppSpec（計畫 WP2）。從 `app.extras["synox_packs"]` 現算，不快取。

核對：reads／exports 每個都掛了函式；actions 每個都掛了函式、`registry.node(f"{group}.{name}")` 存在、
`node.effect` 等於宣告——一個動作＝一個指令。任何一條不合 → 這個 app 進 problems、不能開。
沒有 web.app 的工具沒有任何 app 表面：不在 specs、也不在 problems。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

TEXT = {
    "no_read": "畫面的讀取 {n} 宣告了但工具沒有掛上函式",
    "no_export": "畫面的匯出 {n} 宣告了但工具沒有掛上函式",
    "no_action": "畫面的動作 {n} 宣告了但工具沒有掛上函式",
    "no_node": "畫面的動作 {n} 沒有同名的指令 /{g}_{n}",
    "effect": "畫面的動作 {n} 宣告是 {a}，但指令 /{g}_{n} 是 {b}",
}


@dataclass
class AppSpec:
    name: str
    group: str
    title: str
    app_title: str
    version: str
    entry: str
    root: str
    reads: List[str]
    actions: Dict[str, str]
    exports: List[str]
    files: List[str]
    remote: bool = False
    pack: object = field(default=None, repr=False)


def specs_of(app) -> Tuple[Dict[str, AppSpec], Dict[str, str]]:
    specs: Dict[str, AppSpec] = {}
    problems: Dict[str, str] = {}
    registry = app.registry
    for pack in (getattr(app, "extras", None) or {}).get("synox_packs", []):
        m = pack.manifest
        decl = (m.web or {}).get("app")
        if not decl:
            continue
        why: List[str] = []
        for n in decl.get("reads") or []:
            if n not in getattr(pack, "app_reads", {}):
                why.append(TEXT["no_read"].format(n=n))
        for n in decl.get("exports") or []:
            if n not in getattr(pack, "app_exports", {}):
                why.append(TEXT["no_export"].format(n=n))
        for n, eff in (decl.get("actions") or {}).items():
            node = registry.node(f"{m.group}.{n}")
            if n not in getattr(pack, "app_actions", {}):
                why.append(TEXT["no_action"].format(n=n))
            elif node is None or node.is_group:
                why.append(TEXT["no_node"].format(n=n, g=m.group))
            elif str(node.effect).lower() != eff:
                why.append(TEXT["effect"].format(n=n, g=m.group, a=eff.upper(), b=str(node.effect).upper()))
        if why:
            problems[m.name] = "；".join(why)
            continue
        specs[m.name] = AppSpec(name=m.name, group=m.group, title=m.title, app_title=decl.get("title") or m.title,
                                version=m.version, entry=decl["entry"], root=decl["root"],
                                reads=list(decl.get("reads") or []), actions=dict(decl.get("actions") or {}),
                                exports=list(decl.get("exports") or []), files=list(decl.get("files") or []),
                                remote=bool(decl.get("remote")), pack=pack)
    return specs, problems
