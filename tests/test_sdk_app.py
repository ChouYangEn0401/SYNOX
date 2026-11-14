"""SDK 的工具服務範本（計畫 WP6）：synox-sdk init --app 產生的工具過第 1、2 關、掛得起來、AppClient 進得去；不加 --app 跟以前一樣。"""

import json
import os
import re

import pytest

from synox import sdk
from synox.packs import scan, tier
from synox.packs.manifest import read
from synox.web.apps.testing import AppClient

from conftest import FIXTURE_PACKS

pytestmark = pytest.mark.usefixtures("no_sockets")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_init_app_passes_gates_and_runs(tmp_path, make_bot, owner):
    folder = tmp_path / "packs" / "demo-app"
    written = sdk.init_pack(str(folder), "python", "demo-app", "示範畫面", app=True)
    assert {"app/index.html", "app/app.js", "app/app.css", "pack.py", "pack.json"} <= set(written)
    m = read(str(folder), strict=True)
    report = scan.scan(m)
    assert report.problems(m) == [] and not [f for f in report.findings if f.kind.startswith("app")]
    assert tier.assess(m, report)["tier"] == "T1"
    bot = make_bot(pack_dirs=(FIXTURE_PACKS, str(tmp_path / "packs")))
    from synox.web import apps
    from synox.web.apps.testing import FakeListen
    manager = apps.of(bot.app)
    manager.listen = FakeListen()
    assert "demo-app" in manager.specs() and manager.problems() == {}
    manager.start("demo-app", by=owner, via="web")
    client = AppClient(manager, "demo-app")
    client.enter(client.open_from_console(owner))
    assert client.do("add", {"text": "買牛奶"}) == (200, {"ok": True, "data": {"count": 1}})
    assert client.read("items")[1]["data"] == {"items": ["買牛奶"]}


def test_init_without_app_is_unchanged(tmp_path):
    folder = tmp_path / "plain"
    written = sdk.init_pack(str(folder), "python", "plain", "一般")
    assert not any(w.startswith("app/") for w in written) and not (folder / "app").exists()
    manifest = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    assert manifest["web"] == {"panel": "panel.html", "api": ["GET /summary"]}
    assert (folder / "pack.py").read_text(encoding="utf-8") == sdk.PACK_PY.format(title="一般")
    with pytest.raises(ValueError):
        sdk.init_pack(str(tmp_path / "x"), "cli", "x", "x", app=True)


def test_single_file_matches_source():
    with open(os.path.join(ROOT, "sdk", "synox_sdk.py"), encoding="utf-8") as f:
        assert f.read() == sdk.single_file_source()
    from synox.sdk import author
    assert author.SDK_VERSION == "0.2.3"


@pytest.mark.parametrize("name", ["docs/tool-apps.md", "docs/security.md"])
def test_docs_do_not_overpromise(name):
    text = open(os.path.join(ROOT, name), encoding="utf-8").read()
    if name.endswith("security.md"):
        text = text.split("## 工具服務", 1)[1].split("\n## ", 1)[0]
    for word in ("改不了", "繞不過", "無法繞過"):
        assert word not in text, word


def test_doc_example_matches_template():
    """tool-apps.md 的三分鐘範例用的就是 init --app 產生的那一份（名字對得上）。"""
    doc = open(os.path.join(ROOT, "docs", "tool-apps.md"), encoding="utf-8").read()
    assert "synox-sdk init my-notes --kind python --name my-notes" in doc and "--app" in doc
    for needle in ('pack.app_read("items"', 'pack.app_action("add"', 'SynoxApp.form("add"'):
        assert needle in doc and re.sub(r"\s+", "", needle) in re.sub(r"\s+", "", sdk.PACK_APP_PY + sdk.APP_JS)
