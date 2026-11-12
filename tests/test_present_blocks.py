"""呈現層的區塊模型與安全規則（synox.present）：信任等級、按鈕群／確認卡只有 system 才是真的按鈕、
連結只收 http／https、狀態標籤、表格降級、切割的不變量。黃金檔案在 test_present_golden.py。"""

import time

import pytest

from present_checks import WEB_TAGS, check_all, check_discord, check_html, check_telegram

from synox import present
from synox.present import blocks as B
from synox.present import discord as discord_out
from synox.present import tables
from synox.present import telegram as telegram_out
from synox.present import web as web_out
from synox.present.markdown import parse, parse_inline
from synox.present.width import clip, pad, utf16_len, width


def system_doc(*blocks, trust=B.SYSTEM):
    return B.Document(list(blocks), trust=trust)


GO = B.Buttons([[B.Button("✅ 執行", data="agent_ok:go:1"), B.Button("說明", url="https://example.com/help")]])
CARD = B.confirm_card("AI 想執行：/note_clear", ["會刪掉全部筆記"], "agent_ok:go:9", "agent_ok:no:9")


# ── 信任等級 ─────────────────────────────────────────────────────────

def test_trust_levels():
    assert B.lowest(B.SYSTEM, B.ASSISTANT) == B.ASSISTANT
    assert B.lowest(B.ASSISTANT, B.EXTERNAL) == B.EXTERNAL
    assert B.lowest(B.SYSTEM, "weird") == "weird"            # 不認得的＝最低
    with pytest.raises(ValueError):
        present.document("x", trust="root")
    doc = parse("一段字", trust=B.EXTERNAL)
    assert doc.trust == B.EXTERNAL and all(b.trust == B.EXTERNAL for b in doc.blocks)


def test_system_buttons_become_reply_markup_on_the_last_message_only():
    long = B.Paragraph(B.text("很長的說明。" * 2000), trust=B.SYSTEM)
    doc = system_doc(B.Status("完成", "ok"), long, GO)
    for channel, check in (("telegram", check_telegram), ("discord", check_discord)):
        chunks = present.render(doc, channel)
        assert len(chunks) >= 2
        check(chunks)
        assert chunks[-1].reply_markup == {"inline_keyboard": [[
            {"text": "✅ 執行", "callback_data": "agent_ok:go:1"}, {"text": "說明", "url": "https://example.com/help"}]]}
    web = present.render(doc, "web")
    assert len(web) == 1 and web[0].reply_markup and not any(b["type"] == "buttons" for b in web[0].text.blocks)


@pytest.mark.parametrize("doc_trust,block_trust", [(B.ASSISTANT, B.SYSTEM), (B.EXTERNAL, B.SYSTEM),
                                                   (B.SYSTEM, B.ASSISTANT), (B.SYSTEM, B.EXTERNAL)])
def test_buttons_and_cards_below_system_are_only_text(doc_trust, block_trust):
    buttons = B.Buttons(GO.rows, trust=block_trust)
    card = B.ConfirmCard(CARD.title, CARD.lines, CARD.ok_data, CARD.cancel_data, trust=block_trust)
    doc = B.Document([buttons, card], trust=doc_trust)
    for channel in present.CHANNELS:
        chunks = present.render(doc, channel)
        assert all(c.reply_markup is None for c in chunks), channel
        assert "〔✅ 執行〕" in "".join(str(c.text) for c in chunks) or channel == "web"
    assert B.reply_markup(doc) is None
    wire = web_out.wire(doc)
    assert [b["type"] for b in wire] == ["paragraph", "paragraph"]
    assert "agent_ok" not in str(wire)
    check_all(doc)


def test_confirm_card_from_the_approval_flow_renders():
    doc = system_doc(CARD)
    tg = present.render(doc, "telegram")
    assert tg[0].text == "<b>AI 想執行：/note_clear</b>\n會刪掉全部筆記"
    assert tg[0].reply_markup == {"inline_keyboard": [[{"text": "✅ 執行", "callback_data": "agent_ok:go:9"},
                                                       {"text": "❌ 取消", "callback_data": "agent_ok:no:9"}]]}
    dc = present.render(doc, "discord")
    assert dc[0].text == "**AI 想執行：/note\\_clear**\n會刪掉全部筆記" and dc[0].reply_markup
    wire = present.render(doc, "web")[0].text.blocks
    assert wire == [{"type": "confirm", "trust": "system", "title": "AI 想執行：/note_clear", "lines": ["會刪掉全部筆記"]}]
    check_all(doc)


def test_button_urls_must_be_http():
    doc = system_doc(B.Buttons([[B.Button("壞", url="javascript:alert(1)"), B.Button("好", data="x:1")]]))
    assert B.reply_markup(doc) == {"inline_keyboard": [[{"text": "好", "callback_data": "x:1"}]]}


def test_status_block():
    doc = system_doc(B.Status("等待中", "pending"), B.Status("<怪>", "nope"))
    assert present.render(doc, "telegram")[0].text == "⏳ <b>等待中</b>\n\nℹ️ <b>&lt;怪&gt;</b>"
    assert present.render(doc, "discord")[0].text == "⏳ **等待中**\n\nℹ️ **\\<怪>**"
    assert web_out.to_html(doc) == ('<p><span class="status status-pending">⏳ 等待中</span></p>\n'
                                    '<p><span class="status status-info">ℹ️ &lt;怪&gt;</span></p>')
    check_html(web_out.to_html(doc), WEB_TAGS)


# ── 連結 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", ["javascript:alert(1)", "JavaScript:alert(1)", " javascript:x", "data:text/html,x",
                                 "file:///etc/passwd", "/admin", "admin.html", "//evil.example/x", "ftp://x.example",
                                 "https://", "https://a.example/\"onmouseover=x", "https://a.example/ x",
                                 "https://a.example/\nx", "vbscript:x", "https://a.example/<script>", ""])
def test_unsafe_urls_are_rejected(url):
    assert B.safe_url(url) is None
    spans = parse_inline(f"[點我]({url})")
    assert not any(s.href and "點我" in s.text for s in spans)                 # 不會變成「點我」的連結
    assert all(B.safe_url(s.href) == s.href for s in spans if s.href)         # 裸網址自動連結也只收安全的


def test_safe_urls():
    assert B.safe_url("https://example.com/a?b=1&c=2#d") == "https://example.com/a?b=1&c=2#d"
    assert B.safe_url("HTTP://EXAMPLE.COM") == "HTTP://EXAMPLE.COM"


def test_external_links_show_the_real_address():
    doc = parse("看 [官方網站](https://phish.example/login)", trust=B.EXTERNAL)
    tg = present.render(doc, "telegram")[0].text
    assert tg == '看 官方網站 <a href="https://phish.example/login">https://phish.example/login</a>'
    assert present.render(doc, "discord")[0].text == "看 官方網站 https://phish.example/login"
    same = parse("看 [官方網站](https://example.com/)", trust=B.ASSISTANT)
    assert present.render(same, "telegram")[0].text == '看 <a href="https://example.com/">官方網站</a>'
    assert present.render(same, "discord")[0].text == "看 [官方網站](https://example.com/)"


# ── 表格降級 ─────────────────────────────────────────────────────────

def _table(md):
    return parse(md).blocks[0]


def test_table_layouts():
    assert tables.layout(_table("| a | b |\n|---|---|\n| 1 | 2 |")).form == "pairs"
    assert tables.layout(_table("| 名稱 | 數 | 單位 |\n|---|---|---|\n| 蘋果 | 3 | 顆 |")).form == "grid"
    wide = _table("| 日期 | 事件 | 地點 |\n|---|---|---|\n| 2026-01-05 | 很長很長很長的事件名稱 | 很遠很遠的地點 |")
    assert tables.layout(wide).form == "cards"
    rows = "\n".join(f"| {i} | x | y |" for i in range(40))
    long = tables.layout(_table("| n | a | b |\n|---|---|---|\n" + rows))
    assert len(long.rows) == tables.SHOW_ROWS and "共 40 列" in long.note
    assert tables.layout(_table("| a | b | c |\n|---|---|---|")).form == "header"


def test_grid_aligns_cjk_by_display_width():
    lines = tables.grid_lines(*[[B.text("名稱"), B.text("n")]], [[B.text("蘋果"), B.text("3")],
                                                                [B.text("ab"), B.text("12")]])
    assert lines == ["名稱  n", "----  --", "蘋果  3", "ab    12"]           # 中文算 2 格，第二欄對齊在第 7 格


def test_width_helpers():
    assert width("中a") == 3 and width("é") == 1 and width("👨‍👩") == 4
    assert pad("中", 4) == "中  "
    assert clip("中文字串", 5) == "中文…" and clip("ab", 5) == "ab"
    assert utf16_len("😀") == 2 and utf16_len("中") == 1


# ── 切割與長度 ───────────────────────────────────────────────────────

def test_one_long_line_without_spaces_is_hard_split():
    doc = parse("x" * 9000 + "&" * 3000)
    tg = present.render(doc, "telegram")
    check_telegram(tg)
    assert "".join(c.text for c in tg).replace("&amp;", "&") == "x" * 9000 + "&" * 3000
    dc = present.render(doc, "discord")
    check_discord(dc)
    assert "".join(c.text for c in dc) == "x" * 9000 + "&" * 3000


def test_split_bold_text_keeps_tags_paired():
    doc = parse("**" + "粗體字 " * 3000 + "結尾**")
    tg = present.render(doc, "telegram")
    assert len(tg) >= 2
    check_telegram(tg)
    assert all(c.text.startswith("<b>") and c.text.endswith("</b>") for c in tg)
    dc = present.render(doc, "discord")
    check_discord(dc)
    assert all(c.text.startswith("**") and c.text.endswith("**") for c in dc)


def test_long_code_block_reopens_its_fence():
    code = "\n".join(f"print({i})  # <{i}>" for i in range(800))
    doc = parse(f"```python\n{code}\n```")
    tg = present.render(doc, "telegram")
    check_telegram(tg)
    assert all(c.text.startswith('<pre><code class="language-python">') and c.text.endswith("</code></pre>")
               for c in tg)
    dc = present.render(doc, "discord")
    check_discord(dc)
    assert all(c.text.startswith("```python\n") and c.text.endswith("\n```") for c in dc)
    assert "\n".join(c.text[len("```python\n"):-len("\n```")] for c in dc) == code


def test_emoji_count_as_two_utf16_units():
    doc = parse("😀" * 5000)
    for c in present.render(doc, "telegram"):
        assert utf16_len(c.text) <= 4096
    for c in present.render(doc, "discord"):
        assert utf16_len(c.text) <= 2000


def test_empty_reply_still_sends_something():
    for channel in ("telegram", "discord"):
        assert [str(c.text) for c in present.render("", channel)] == ["·"]
        assert [str(c.text) for c in present.render("---", channel)] == ["·"]


def test_unknown_channel_is_an_error():
    with pytest.raises(ValueError):
        present.render("x", "line")


def test_plain_source_is_not_parsed():
    doc = present.document("**不是粗體**\n\n第二段", source="plain")
    assert [b.to_dict() for b in doc.blocks] == [
        {"type": "paragraph", "trust": "assistant", "spans": [{"text": "**不是粗體**"}]},
        {"type": "paragraph", "trust": "assistant", "spans": [{"text": "第二段"}]}]
    assert present.render(doc, "discord")[0].text == "\\*\\*不是粗體\\*\\*\n\n第二段"


def test_web_html_is_escaped_and_whitelisted():
    doc = parse("<script>x</script>\n\n| <a> | b |\n|---|---|\n| 1 | 2 |\n\n- [x](javascript:y)")
    html = web_out.to_html(doc)
    check_html(html, WEB_TAGS)
    assert "<script" not in html and "javascript:" in html and 'href="javascript' not in html


def test_rendering_is_fast_enough():
    text = ("**粗** *斜* `碼` [連](https://e.example/) | 表 |\n" * 3000)
    start = time.monotonic()
    for channel in present.CHANNELS:
        present.render(text, channel)
    assert time.monotonic() - start < 20
    assert telegram_out.LIMIT == 4096 and discord_out.LIMIT == 2000
