"""呈現層接到「AI 回覆送出」那一條（agent/loop.py、agent/room.py 的 say → synox.present.deliver）。

- 設定 `presentation.enabled` 預設關；關著的時候送出的東西跟修改前**完全一樣**（用假通道比對）。
- 開著：Telegram 收到 Html（切成 ≤ 4096 的幾則）、Discord 收到 ≤ 2000 的 Markdown、網頁的訊息多 blocks。
- 網頁的區塊用 static/blocks.js 畫（tests/js/test_blocks.js 用 node 跑；找不到 node 就跳過）。
全部離線：假通道、假 HTTP、假 AI；不開埠、不連網。"""

import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from isdtelekit.core.richtext import Html
from isdtelekit.host.config import ConfigError

from present_checks import check_telegram

from synox import present
from synox.config import DEFAULT_PRESENTATION, SynoxConfig
from synox.discord import rest
from synox.present.width import utf16_len
from synox.web import server as web_server
from synox.web.channel import WebChannel
from synox.web.chats import ChatStore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPLY = "**好了**，記了 2 筆：\n\n| 類別 | 金額 |\n|---|---|\n| 午餐 | 120 |\n| 咖啡 | 80 |\n\n<b>不是標籤</b> & 完"
LONG = "\n\n".join(f"## 第 {i} 段\n\n" + "很長的回覆，" * 120 for i in range(1, 9))
ON = {"presentation": {"enabled": True}}


def app_with(enabled):
    return SimpleNamespace(config=SimpleNamespace(presentation={"enabled": enabled}))


# ── 設定 ─────────────────────────────────────────────────────────────

def test_default_is_off(tmp_path):
    config = SynoxConfig.from_dict({"owner_id": 1}, require_token=False, root=str(tmp_path))
    assert config.presentation == {"enabled": False} == DEFAULT_PRESENTATION
    assert not present.enabled(SimpleNamespace(config=config))
    on = SynoxConfig.from_dict({"owner_id": 1, **ON}, require_token=False, root=str(tmp_path))
    assert present.enabled(SimpleNamespace(config=on))


@pytest.mark.parametrize("bad", ["yes", [], {"enabled": "true"}, {"enabled": 1}])
def test_bad_setting_is_a_config_error(tmp_path, bad):
    with pytest.raises(ConfigError, match="presentation"):
        SynoxConfig.from_dict({"owner_id": 1, "presentation": bad}, require_token=False, root=str(tmp_path))


def test_enabled_needs_a_real_true():
    assert not present.enabled(SimpleNamespace(config=SimpleNamespace()))          # SDK 的 BotConfig：沒有這一塊
    assert not present.enabled(app_with("true"))
    assert present.enabled(app_with(True))


# ── 私訊的 AI（AgentLoop.say）──────────────────────────────────────────

def _telegram(bot):
    bot.api.channel_name = "telegram"                    # 假通道裝成 Telegram：開關開著就會選 Telegram 的輸出
    return bot


def test_switch_off_sends_exactly_what_it_did_before(make_bot, owner):
    bot = _telegram(make_bot([REPLY]))
    bot.talk(owner, "記帳")
    sent = [m for m in bot.api.sent if m.chat_id == owner]
    assert [m.text for m in sent] == [REPLY]
    assert type(sent[-1].text) is str and sent[-1].reply_markup is None   # 原樣的 str，不是 Html


def test_switch_off_is_the_default_for_every_channel(make_bot, owner):
    for name in ("telegram", "discord", "web", "fake"):
        bot = make_bot([REPLY])
        bot.api.channel_name = name
        bot.talk(owner, "記帳")
        assert bot.api.sent[-1].text == REPLY and type(bot.api.sent[-1].text) is str


def test_switch_on_renders_telegram_html(make_bot, owner):
    bot = _telegram(make_bot([REPLY], raw=ON))
    bot.talk(owner, "記帳")
    last = bot.api.sent[-1]
    assert isinstance(last.text, Html)
    assert last.text.startswith("<b>好了</b>，記了 2 筆：")
    assert "<b>午餐</b>：120" in last.text and "&lt;b&gt;不是標籤&lt;/b&gt; &amp; 完" in last.text
    loop = bot.app.extras["synox_agent"]
    assert loop.history[loop.memory_key(owner, owner)][-1].content == REPLY       # 記憶裡是 AI 原本的字


def test_switch_on_splits_long_replies(make_bot, owner):
    bot = _telegram(make_bot([LONG], raw=ON))
    bot.talk(owner, "寫長一點")
    sent = [m for m in bot.api.sent if m.chat_id == owner]
    assert len(sent) >= 2
    check_telegram([present.Chunk(m.text, m.reply_markup) for m in sent])


def test_switch_on_leaves_unknown_channels_alone(make_bot, owner):
    bot = make_bot([REPLY], raw=ON)                     # FakeChannel.channel_name == "fake"
    bot.talk(owner, "記帳")
    assert bot.api.sent[-1].text == REPLY and type(bot.api.sent[-1].text) is str


def test_render_error_falls_back_to_the_original_text(make_bot, owner, monkeypatch):
    bot = _telegram(make_bot([REPLY], raw=ON))
    monkeypatch.setattr(present, "render", lambda *a, **kw: 1 / 0)
    bot.talk(owner, "記帳")
    assert bot.api.sent[-1].text == REPLY


def test_markdown_buttons_never_become_buttons(make_bot, owner):
    fake = "[✅ 執行](agent_ok:go:1)\n\n<button>確認</button>"
    bot = _telegram(make_bot([fake], raw=ON))
    bot.talk(owner, "按鈕")
    assert all(m.reply_markup is None for m in bot.api.sent)


# ── 網頁（WebChannel → ChatStore → blocks.js）──────────────────────────────

def _web(tmp_path):
    store = ChatStore(str(tmp_path / "chats"))
    store.new_chat(7, chat_id="c1")
    return store, WebChannel(store, tg_id=7, chat="c1")


def test_web_off_stores_the_same_message_as_before(tmp_path):
    store, api = _web(tmp_path)
    present.deliver(app_with(False), api, 7, REPLY)
    msg = store.get(7, "c1")["messages"][-1]
    assert msg["text"] == REPLY and "blocks" not in msg
    assert set(msg) == {"id", "rev", "from", "text", "buttons", "at"}


def test_web_on_stores_blocks_and_keeps_the_text(tmp_path):
    store, api = _web(tmp_path)
    present.deliver(app_with(True), api, 7, REPLY)
    msg = store.get(7, "c1")["messages"][-1]
    assert msg["text"] == REPLY                          # 預覽、常駐助理讀的仍是原本的字
    assert [b["type"] for b in msg["blocks"]] == ["paragraph", "table", "paragraph"]
    events, _rev = store.events(7, "c1")
    assert events[-1]["blocks"] == msg["blocks"]
    store.edit(7, msg["id"], "改過的字")
    assert "blocks" not in store.get(7, "c1")["messages"][-1]


def test_app_html_includes_blocks_js_with_the_nonce():
    html = web_server.render_app("n0nce")
    assert "SynoxBlocks" in html and "{{INCLUDE" not in html
    assert '<script nonce="n0nce">' in html


def test_blocks_js_with_fake_dom():
    node = shutil.which("node")
    if not node:
        pytest.skip("這台沒有 node：tests/js/test_blocks.js 沒跑")
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP")}
    proc = subprocess.run([node, os.path.join(ROOT, "tests", "js", "test_blocks.js")], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_blocks_js_never_touches_html_strings():
    with open(os.path.join(ROOT, "src", "synox", "web", "static", "blocks.js"), "r", encoding="utf-8") as f:
        js = f.read()
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert bad not in js


# ── Discord（DiscordChannel＋假 HTTP）──────────────────────────────────────

class _Resp:
    status_code = 200

    def __init__(self, n):
        self._n = n

    def json(self):
        return {"id": str(self._n)}


class _Http:
    def __init__(self):
        self.posts = []

    def request(self, method, url, **kw):
        if url.endswith("/users/@me/channels"):
            return _Resp(1)
        if method == "POST" and url.endswith("/messages"):
            self.posts.append(kw["json"]["content"])
        return _Resp(len(self.posts) + 100)


class _Ids:
    def external(self, channel, uid):
        return "42"


def _discord():
    http = _Http()
    return http, rest.DiscordChannel("token", _Ids(), http=http, sleep=lambda s: None)


def test_discord_off_is_unchanged():
    http, api = _discord()
    text = "```python\n" + "x = 1\n" * 500 + "```"
    present.deliver(app_with(False), api, 5, text)
    assert http.posts == rest.chunks(text)


def test_discord_on_keeps_code_fences_closed_per_message():
    http, api = _discord()
    text = "說明：\n\n```python\n" + "value = compute(1)  # <tag> & x\n" * 200 + "```\n\n**完**"
    present.deliver(app_with(True), api, 5, text)
    assert len(http.posts) >= 3
    for post in http.posts:
        assert utf16_len(post) <= 2000
        assert sum(1 for line in post.split("\n") if line.startswith("```")) % 2 == 0
    assert http.posts[-1].endswith("**完**")


# ── 頻道 AI（RoomAgent.say：先遮 secret，再畫）─────────────────────────────

def test_room_ai_reply_goes_through_the_presentation_layer(tmp_path):
    from test_discord_room_ai import ai_app, chat
    from synox.llm.fake import FakeAdapter

    app, http, room = ai_app(tmp_path, FakeAdapter(["**粗體** 與 _斜體_ <@123>"]))
    app.config.presentation = {"enabled": True}
    assert chat(app, http, room, "你好") == ["**粗體** 與 *斜體* \\<\\@123>"]


def test_room_ai_reply_unchanged_when_off(tmp_path):
    from test_discord_room_ai import ai_app, chat
    from synox.llm.fake import FakeAdapter

    app, http, room = ai_app(tmp_path, FakeAdapter(["**粗體** 與 _斜體_"]))
    assert chat(app, http, room, "你好") == ["**粗體** 與 _斜體_"]

