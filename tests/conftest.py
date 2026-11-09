"""共用的假東西：整支 SYNOX（真的 packs、真的 vault 加密）跑在記憶體裡，不連 Telegram、不連網、不開埠。"""

import os

import pytest

from isdtelekit.testing import OWNER_ID, BotHarness, FakeChannel

from synox.app import build
from synox.config import SynoxConfig
from synox.llm.fake import FakeAdapter
from synox.vault import Vault

OTHER_ID = 555


class SynoxBot(BotHarness):
    """BotHarness ＋ 等 AI 那一輪（app.tasks）做完。"""

    def talk(self, user_id, text, **kw):
        route = self.say(user_id, text, **kw)
        assert self.app.tasks.wait(10), "AI turn did not finish"
        return route

    def press_and_wait(self, user_id, data, **kw):
        route = self.press(user_id, data, **kw)
        self.app.tasks.wait(10)
        return route


@pytest.fixture
def make_bot(tmp_path):
    def factory(script=None, *, adapter=None, llm=None, raw=None, supports_tools=True, pack_dirs=None):
        data = tmp_path / "data"
        cfg = {"owner_id": OWNER_ID, "data_dir": str(data), "vault": {"mode": "file"},
               "llm": llm or {"kind": "fake"}, **(raw or {})}
        config = SynoxConfig.from_dict(cfg, require_token=False, root=str(tmp_path))
        api = FakeChannel()
        vault = Vault(b"k" * 32, str(data))
        if adapter is None and (llm or {}).get("kind") != "none":
            adapter = FakeAdapter(script, supports_tools=supports_tools)
        kw = {"pack_dirs": pack_dirs} if pack_dirs is not None else {}
        app = build(config, home=api, adapter=adapter, vault=vault, **kw)
        return SynoxBot(app, api)
    return factory


@pytest.fixture
def owner():
    return OWNER_ID


def trust_core(data_dir, *folders):
    """把 tmp 裡手放的 pack 鎖成 trust=core（擁有者安裝時選「核心」）：伺服器版沒鎖的 python pack＝third-party、
    只給擁有者（PERM-8），測成員可見性的測試要先這樣核准。"""
    from synox.packs import lock
    from synox.packs.manifest import read
    for folder in folders:
        lock.approve(str(data_dir), read(folder), None, OWNER_ID, via="test", trust="core")


def enc_files(bot):
    return sorted(f for f in os.listdir(bot.app.config.data_dir) if f.endswith(".json.enc"))
