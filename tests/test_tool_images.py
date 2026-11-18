"""工具回覆帶圖（web/chatmedia.py、WebChannel.send_image／edit_image、kit.send_image、GET /api/chat/<段>/image/<id>）：
類型看內容、SVG 白名單重寫（惡意 SVG 一律不收）、存進對話紀錄（重開還在）、訊息不見圖一起刪、AI 路徑、Telegram 退回照片。"""

import os
import struct
import zlib

import pytest

from synox.agent.capture import CaptureApi
from synox.packs import kit
from synox.web import chatmedia
from synox.web.channel import WebChannel, html_blocks
from synox.web.chatmedia import ChatMedia, Refused, sanitize_svg
from synox.web.chats import ChatStore

from test_web import Client, ui_of

GOOD_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 150" width="120" height="150">'
            '<title>D/F#</title><rect x="0" y="0" width="120" height="150" fill="#ffffff"/>'
            '<line x1="20" y1="30" x2="20" y2="130" stroke="#333" stroke-width="1.2"/>'
            '<circle cx="20" cy="40" r="7" fill="#8A4A22"/><text x="60" y="16" font-size="14" text-anchor="middle">D/F#</text>'
            '</svg>')


def png(w=2, h=2):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


# ── 檢查 ─────────────────────────────────────────────────────────────

def test_good_svg_is_rewritten_from_the_whitelist():
    data, w, h = sanitize_svg(GOOD_SVG.encode())
    assert (w, h) == (120, 150)
    text = data.decode()
    assert text.startswith('<svg xmlns="http://www.w3.org/2000/svg"') and "<circle" in text and "D/F#" in text


@pytest.mark.parametrize("evil", [
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><script>alert(1)</script></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" onload="alert(1)"/>',
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="5" height="5" onclick="x()"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10">'
    '<image xlink:href="https://evil.example/a.png" width="5" height="5"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10">'
    '<use xlink:href="#a"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><a href="javascript:alert(1)"><text>x</text></a></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><foreignObject><div>x</div></foreignObject></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><style>@import url(https://evil.example)</style></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="5" height="5" fill="url(https://e.x/#a)"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="5" height="5" style="fill:red"/></svg>',
    '<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x "xxxxxxxx">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><animate attributeName="href" to="javascript:x"/></svg>',
    '<html><script>alert(1)</script></html>',
    '<svg viewBox="0 0 10 10"><rect width="5" height="5"/></svg>',                     # 沒有 SVG 命名空間
    '<svg xmlns="http://www.w3.org/2000/svg"><rect width="5" height="5"/></svg>',     # 沒有大小
])
def test_malicious_or_unknown_svg_is_refused(evil):
    with pytest.raises(Refused):
        sanitize_svg(evil.encode())


def test_comments_and_processing_instructions_are_not_kept():
    data, _w, _h = sanitize_svg(('<?xml-stylesheet href="https://evil.example/x.css"?>' + GOOD_SVG.replace(
        "<title>", "<!-- <script>x</script> --><title>")).encode())
    assert b"evil" not in data and b"script" not in data and b"<?" not in data


def test_raster_type_comes_from_content_and_size_is_capped():
    prepared, problems = chatmedia.prepare([png(3, 2), b"not an image", {"data": b"GIF89a" + bytes(4)}])
    assert [(p.mime, p.w, p.h) for p in prepared] == [("image/png", 3, 2)] and len(problems) == 2
    with pytest.raises(Refused):
        chatmedia.prepare_one(png(5000, 10))
    with pytest.raises(Refused):
        chatmedia.prepare_one(b"\x89PNG\r\n\x1a\n" + bytes(chatmedia.MAX_BYTES))
    many, problems = chatmedia.prepare([png()] * (chatmedia.MAX_IMAGES + 2))
    assert len(many) == chatmedia.MAX_IMAGES and problems


def test_bad_svg_falls_back_to_the_png():
    p = chatmedia.prepare_one({"svg": "<svg onload='x'/>", "png": png(), "alt": "x" * 500})
    assert p.mime == "image/png" and len(p.alt) == chatmedia.MAX_ALT


# ── 存檔、對話紀錄 ──────────────────────────────────────────────────

def store_at(tmp_path, keep=50):
    store = ChatStore(str(tmp_path / "web_chats"), None, keep=keep)
    store.media = ChatMedia(str(tmp_path / "web_chats" / "media"))
    store.new_chat(42, "t", "c1")
    return store


def test_send_image_is_one_message_kept_with_the_history(tmp_path):
    store = store_at(tmp_path)
    ch = WebChannel(store, 42, "c1")
    out = ch.send_image(42, [{"svg": GOOD_SVG, "png": png(), "alt": "D/F#"}], caption="D/F#：2 x 0 2 3 2",
                        reply_markup={"inline_keyboard": [[{"text": "下一個 ›", "callback_data": "gt:1"}]]})
    assert out["ok"]
    msg = store.events(42, "c1")[0][0]
    assert msg["text"] == "D/F#：2 x 0 2 3 2" and msg["buttons"][0][0]["data"] == "gt:1"
    meta = msg["images"][0]
    assert meta["type"] == "image/svg+xml" and meta["alt"] == "D/F#" and (meta["w"], meta["h"]) == (120, 150)
    again = ChatStore(str(tmp_path / "web_chats"), None)                 # 重開（重新整理）還在
    again.media = ChatMedia(str(tmp_path / "web_chats" / "media"))
    assert again.events(42, "c1")[0][0]["images"] == msg["images"]
    mime, data = again.media.get(42, meta["id"])
    assert mime == "image/svg+xml" and data.startswith(b"<svg")
    assert again.media.get(43, meta["id"]) is None                       # 別人的資料夾沒有
    assert ch.send_image(42, [b"nope"])["ok"] is False and len(store.events(42, "c1")[0]) == 1   # 全部不收＝什麼都不存


def test_edit_image_replaces_and_old_files_are_removed(tmp_path):
    store = store_at(tmp_path)
    ch = WebChannel(store, 42, "c1")
    mid = ch.send_image(42, [png()], caption="1／2")["result"]["message_id"]
    old = store.find(42, mid)[1]["images"][0]["id"]
    assert ch.edit_image(42, mid, [png(4, 4)], caption="2／2")["ok"]
    msg = store.find(42, mid)[1]
    assert msg["text"] == "2／2" and msg["images"][0]["id"] != old and msg["images"][0]["w"] == 4
    assert store.media.get(42, old) is None


def test_images_go_away_with_their_messages(tmp_path):
    store = store_at(tmp_path, keep=2)
    ch = WebChannel(store, 42, "c1")
    ch.send_image(42, [png()])
    first = store.events(42, "c1")[0][0]["images"][0]["id"]
    ch.send_message(42, "a")
    ch.send_message(42, "b")                                              # 第一則被擠掉
    assert store.media.get(42, first) is None
    ch.send_image(42, [png()])
    second = store.events(42, "c1")[0][-1]["images"][0]["id"]
    store.clear(42, "c1")
    assert store.media.get(42, second) is None
    assert os.listdir(str(tmp_path / "web_chats" / "media" / "42")) == []


def test_send_photo_from_a_path_is_shown_on_the_web(tmp_path):
    store = store_at(tmp_path)
    path = tmp_path / "x.png"
    path.write_bytes(png())
    assert WebChannel(store, 42, "c1").send_photo(42, str(path), caption="圖")["ok"]
    msg = store.events(42, "c1")[0][0]
    assert msg["images"][0]["type"] == "image/png" and msg["text"] == "圖"


def test_html_pre_becomes_a_code_block_on_the_web(tmp_path):
    from isdtelekit.core.richtext import Html
    store = store_at(tmp_path)
    WebChannel(store, 42, "c1").send_message(42, Html("TAB：\n<pre>e|--1--|\nB|-1---|</pre>\nT：拇指"))
    msg = store.events(42, "c1")[0][0]
    assert [b["type"] for b in msg["blocks"]] == ["paragraph", "code", "paragraph"]
    assert msg["blocks"][1]["code"] == "e|--1--|\nB|-1---|" and "<pre>" not in msg["text"]
    assert html_blocks("plain") is None and html_blocks(Html("<b>x</b>")) is None


# ── kit：AI 路徑、Telegram 退回照片 ─────────────────────────────────

class PhotoOnly:
    """像 Telegram：只有 send_photo／send_media_group（本機路徑）。"""

    def __init__(self):
        self.sent = []

    def send_photo(self, chat_id, photo, caption=""):
        with open(photo, "rb") as f:
            self.sent.append(("photo", f.read(), caption))
        return {"ok": True}

    def send_media_group(self, chat_id, paths, caption="", kind="photo"):
        self.sent.append(("group", len(paths), caption))
        return {"ok": True}

    def send_message(self, chat_id, text, reply_markup=None, **kw):
        self.sent.append(("text", text, reply_markup))
        return {"ok": True}


def test_kit_falls_back_to_a_png_photo_and_cleans_up():
    api = PhotoOnly()
    assert kit.send_image(api, 1, [{"svg": GOOD_SVG, "png": png()}], caption="D/F#")["ok"]
    kind, data, caption = api.sent[0]
    assert kind == "photo" and data == png() and caption == "D/F#"
    assert kit.send_image(api, 1, [{"svg": GOOD_SVG}])["ok"] is False      # 只有 SVG：Telegram 送不了，呼叫的人改送文字
    assert kit.send_image(api, 1, [png(), png()], caption="兩張")["ok"] and api.sent[-1][:2] == ("group", 2)
    assert not kit.can_show_images(api)


def test_ai_path_gives_the_user_the_image_and_tells_the_ai(tmp_path):
    store = store_at(tmp_path)
    cap = CaptureApi(WebChannel(store, 42, "c1"), 42)
    assert kit.can_show_images(cap)
    cap.send_message(42, "D/F#：2 x 0 2 3 2")
    kit.send_image(cap, 42, [{"svg": GOOD_SVG, "png": png()}], caption="D/F# 和弦圖")
    seen = cap.close()
    assert "D/F#：2 x 0 2 3 2" in seen and "已直接傳給使用者 1 張圖" in seen
    assert store.events(42, "c1")[0][0]["images"]                          # 使用者看得到圖


# ── 網址：只給本人、這段對話、安全標頭 ─────────────────────────────

def test_image_url_serves_with_strict_headers_and_only_to_its_owner(make_bot, owner):
    bot = make_bot()
    ui = ui_of(bot)
    c = Client(ui)
    c.login(owner)
    ui.chats.new_chat(owner, "t", "c5")
    ch = ui.channel(bot.app.users.get_or_create(owner, "o"), "c5")
    ch.send_image(owner, [{"svg": GOOD_SVG, "png": png()}])
    meta = ui.chats.events(owner, "c5")[0][0]["images"][0]
    status, headers, body = c.raw("GET", f"/api/chat/c5/image/{meta['id']}")
    h = dict(headers)
    assert status == 200 and h["Content-Type"] == "image/svg+xml" and body.startswith(b"<svg")
    assert "default-src 'none'" in h["Content-Security-Policy"] and "sandbox" in h["Content-Security-Policy"]
    assert h["X-Content-Type-Options"] == "nosniff"
    assert c.raw("GET", f"/api/chat/tools/image/{meta['id']}")[0] == 404        # 別段對話
    assert c.raw("GET", "/api/chat/c5/image/AAAAAAAAAAAAAAAA")[0] == 404
    anon = Client(ui)
    assert anon.raw("GET", f"/api/chat/c5/image/{meta['id']}")[0] in (401, 403)
