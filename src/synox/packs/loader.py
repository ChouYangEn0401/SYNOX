"""
掃 packs/*/pack.json 與 connectors/*/pack.json，一個資料夾一個 pack，裝進 app。

  kind=python     import 資料夾裡的 pack.py，呼叫 install(app, pack)
  kind=cli        pack.json 的 cli.argv＋cli.commands → isdtelekit.packs.service.install（會印 JSON 的命令列程式）
  kind=connector  只登記：一個群組、一個葉節點，說「還沒接上」（v0 不連外）

群組（/help 的一頁）由 loader 依 pack.json 定義（title、summary、access），pack 只往裡面掛葉節點；
access=owner（預設）＝整組只有機器擁有者看得到、用得到（別人打了跟不存在一樣）。
一個 pack 壞掉（pack.json 不合、install 丟例外）只跳過那一個，記在 LoadReport，doctor 會印出來。
pack 拿到的 Pack 物件：.manifest、.store（storage=vault → 密文 data/<name>.json.enc；plain → data/<name>.json）、
.path(...)（data/packs/<name>/... 給 pack 自己的檔案）、.group（指令群組的 Group handle）。
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from isdtelekit.core import jsonstore
from isdtelekit.core.registry import DANGER, READ, WRITE, Field

from synox.config import ROOT
from synox.packs.manifest import Manifest, ManifestError, missing_requirements, read

PACK_DIRS = (os.path.join(ROOT, "packs"), os.path.join(ROOT, "connectors"))
EFFECTS = {"read": READ, "write": WRITE, "danger": DANGER}


class PackStore:
    """pack 的資料：load/save 一份 JSON。storage=vault 時落地是密文（Vault），否則 SDK 的 jsonstore。"""

    def __init__(self, name: str, data_dir: str, vault=None):
        self.name = name
        self._data_dir = data_dir
        self._vault = vault
        self.lock = threading.RLock()           # 讀改寫同一份資料時用（update() 已經包好）

    @property
    def encrypted(self) -> bool:
        return self._vault is not None

    def _key(self, key: Optional[str]) -> str:
        return self.name if not key else f"{self.name}.{key}"

    def file(self, key: Optional[str] = None) -> str:
        if self._vault is not None:
            return self._vault.path(self._key(key))
        return os.path.join(self._data_dir, self._key(key) + ".json")

    def load(self, default: Any = None, key: Optional[str] = None) -> Any:
        if self._vault is not None:
            return self._vault.load_json(self._key(key), default)
        return jsonstore.load_json(self.file(key), default)

    def save(self, data: Any, key: Optional[str] = None) -> None:
        if self._vault is not None:
            self._vault.save_json(self._key(key), data)
        else:
            jsonstore.save_json(self.file(key), data)

    def update(self, fn: Callable[[Any], Any], default: Any, key: Optional[str] = None) -> Any:
        """讀 → fn(data) 原地改 → 存；回 fn 的回傳值。整段持鎖。"""
        with self.lock:
            data = self.load(default, key)
            result = fn(data)
            self.save(data, key)
            return result


@dataclass
class Pack:
    manifest: Manifest
    store: PackStore
    app: Any = field(repr=False, default=None)
    data_dir: str = ""

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def group(self):
        return self.app.registry.group(self.manifest.group)

    def path(self, *parts: str) -> str:
        folder = os.path.join(self.data_dir, "packs", self.manifest.name)
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, *parts)


@dataclass
class PackStatus:
    name: str
    folder: str
    status: str                 # loaded｜connector｜disabled｜invalid｜missing｜error
    detail: str = ""
    kind: str = ""
    version: str = ""


@dataclass
class LoadReport:
    items: List[PackStatus] = field(default_factory=list)

    def by_status(self, status: str) -> List[PackStatus]:
        return [i for i in self.items if i.status == status]

    @property
    def ok(self) -> bool:
        return not any(i.status in ("invalid", "error") for i in self.items)


def discover(dirs=PACK_DIRS) -> List[str]:
    folders = []
    for base in dirs:
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            folder = os.path.join(base, name)
            if os.path.isfile(os.path.join(folder, "pack.json")):
                folders.append(folder)
    return folders


def _order(folder: str) -> tuple:
    try:
        m = read(folder)
        return (0 if m.kind != "connector" else 1, int(m.raw.get("order", 100)), m.name)
    except (ManifestError, ValueError, TypeError):
        return (2, 0, folder)


def _drop_group(registry, group: str) -> None:
    node = registry.node(group)
    if node is None:
        return
    for leaf in [n for n in node.walk() if not n.is_group]:
        registry.remove(leaf.path)
    registry.remove(group)


def _install_python(app, pack: Pack) -> None:
    m = pack.manifest
    module_name = m.python.get("module", "pack")
    path = os.path.join(m.folder, f"{module_name}.py")
    spec = importlib.util.spec_from_file_location(f"synox_pack_{m.name.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if not callable(getattr(module, "install", None)):
        raise ManifestError(f"{module_name}.py 沒有 install(app, pack)")
    module.install(app, pack)


def _cli_argv(m: Manifest) -> List[str]:
    out = []
    for part in m.cli["argv"]:
        part = str(part)
        if part == "{python}":
            part = sys.executable
        elif part.startswith("./") or part.startswith(".\\"):
            part = os.path.join(m.folder, part[2:])
        out.append(part)
    return out


def _install_cli(app, pack: Pack) -> None:
    from isdtelekit.jobs.cli import JsonCli
    from isdtelekit.packs import service

    m = pack.manifest
    cwd = m.cli.get("cwd") or "."
    cli = JsonCli(app.jobs, _cli_argv(m), cwd=os.path.normpath(os.path.join(m.folder, cwd)), name=m.name,
                  timeout=float(m.cli.get("timeout", 120)), json_flag=m.cli.get("json_flag", "--json"))
    commands = []
    for c in m.cli["commands"]:
        fields = [Field(f["name"], f.get("ask", f["name"]), required=bool(f.get("required")),
                        default=str(f.get("default", "")), choices=tuple(f.get("choices") or ()))
                  for f in c.get("fields") or []]
        commands.append(service.ServiceCommand(c["name"], c["argv"], c.get("summary", c["name"]), fields=fields,
                                               effect=EFFECTS.get(c.get("effect", "read"), READ),
                                               background=bool(c.get("background")), default=bool(c.get("default")),
                                               timeout=c.get("timeout")))
    service.install(app, cli, commands, group=m.group, title=m.title, summary=m.summary)


def _install_connector(app, pack: Pack) -> None:
    m = pack.manifest

    def status(api, chat_id, user, args):
        api.send_message(chat_id, f"🔌 {m.title} 還沒接上（SYNOX v0 只登記 connector，不連外）。\n"
                                  f"接法的設計寫在 connectors/{os.path.basename(m.folder)}/README.md。")

    pack.group.leaf("status", status, "還沒接上（打了看說明）", default=True, ai=False)


def load_all(app, config, vault=None, dirs=PACK_DIRS) -> LoadReport:
    report = LoadReport()
    packs: List[Pack] = app.extras.setdefault("synox_packs", [])
    for folder in sorted(discover(dirs), key=_order):
        try:
            m = read(folder)
        except ManifestError as e:
            report.items.append(PackStatus(os.path.basename(folder), folder, "invalid", str(e)))
            logging.error("[PACKS] %s: %s", folder, e)
            continue
        item = PackStatus(m.name, folder, "loaded", kind=m.kind, version=m.version)
        report.items.append(item)
        if not config.pack_enabled(m.name):
            item.status = "disabled"
            continue
        missing = missing_requirements(m, config)
        if missing:
            item.status, item.detail = "missing", f"缺 {missing}"
            continue
        if app.registry.node(m.group) is not None:
            item.status, item.detail = "error", f"群組 {m.group} 已經被別的 pack 用了"
            continue
        use_vault = m.storage == "vault"
        if use_vault and vault is None:
            item.status, item.detail = "error", "這個 pack 要保管箱（storage=vault），但保管箱沒有打開"
            continue
        pack = Pack(m, PackStore(m.name, config.data_dir, vault if use_vault else None), app, config.data_dir)
        app.registry.define_group(m.group, m.title, m.summary, owner_only=(m.access == "owner"))
        try:
            {"python": _install_python, "cli": _install_cli, "connector": _install_connector}[m.kind](app, pack)
        except Exception as e:
            logging.exception("[PACKS] %s failed to install", m.name)
            _drop_group(app.registry, m.group)
            item.status, item.detail = "error", f"{type(e).__name__}: {e}"
            continue
        if m.kind == "connector":
            item.status = "connector"
        packs.append(pack)
    app.extras["synox_pack_report"] = report
    return report
