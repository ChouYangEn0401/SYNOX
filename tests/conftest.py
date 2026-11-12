"""共用的假東西：整支 SYNOX（測試用的 pack、真的 vault 加密）跑在記憶體裡，不連 Telegram、不連網、不開埠。

SYNOX 出廠不帶工具（2026-11-12，legacy/builtin-packs.md、legacy/connectors.md）。測試期間 `loader.PACK_DIRS`（「SYNOX 自己的 pack 資料夾」）
一律換成 tests/fixtures/packs/（money、notes、remind：下架前內建版本的凍結複本，正本在 SYNOX_Libs；以前還加 connectors/，
那 4 個連同測試搬到 SYNOX_Libs 了）
（_test_pack_dirs，autouse）：make_bot、doctor、/bot_status、web 的 reload 看到的都是這一份，不讀 repo 的 packs/
（那裡是使用者裝工具的地方，開發機上可能有東西）。伺服器版的 make_bot 先把這三個鎖成 trust=core
（以前它們是「出廠＝core」；現在要經安裝流程，見 trust_core）。要測「空的 host」就給 pack_dirs=() 或換 PACK_DIRS。"""

import os

import pytest

from isdtelekit.testing import OWNER_ID, BotHarness, FakeChannel

from synox.app import build
from synox.config import SynoxConfig
from synox.llm.fake import FakeAdapter
from synox.vault import Vault

OTHER_ID = 555
FIXTURE_PACKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "packs")
DEFAULT_PACK_DIRS = (FIXTURE_PACKS,)
FIXTURE_NAMES = ("money", "notes", "remind")


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
        if config.mode == "server":            # 以前「出廠＝core」；現在當作擁有者安裝時選了 core
            trust_core(data, *(os.path.join(FIXTURE_PACKS, n) for n in FIXTURE_NAMES))
        kw = {"pack_dirs": pack_dirs} if pack_dirs is not None else {}
        app = build(config, home=api, adapter=adapter, vault=vault, **kw)
        return SynoxBot(app, api)
    return factory


@pytest.fixture(autouse=True)
def _test_pack_dirs(monkeypatch):
    from synox.packs import loader
    monkeypatch.setattr(loader, "PACK_DIRS", DEFAULT_PACK_DIRS)


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
