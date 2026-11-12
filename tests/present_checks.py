"""呈現層（synox.present）測試共用的不變量檢查與黃金檔案的讀寫。不是測試檔（pytest 不收）。"""

import json
import os
import re

from synox import present
from synox.present import web as web_out
from synox.present.width import utf16_len

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "present")
UPDATE = os.environ.get("SYNOX_UPDATE_GOLDEN") == "1"
OUTPUTS = ("blocks.json", "telegram.json", "discord.json", "web.html")

TELEGRAM_TAGS = {"b": (), "i": (), "code": ("class",), "pre": (), "a": ("href",), "blockquote": ()}
WEB_TAGS = {t: () for t in ("p", "h3", "h4", "h5", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td",
                            "pre", "code", "b", "i", "blockquote")}
WEB_TAGS.update({"a": ("href", "rel"), "span": ("class",), "ol": ("start",)})

_TAG = re.compile(r'<(/?)([a-z0-9]+)((?:\s+[a-z-]+="[^"<>]*")*)\s*>')
_ATTR = re.compile(r'([a-z-]+)="([^"<>]*)"')
_ENTITY = re.compile(r"&(amp|lt|gt|quot|#x27|#39);")


def cases():
    return sorted(d for d in os.listdir(FIXTURES) if os.path.isfile(os.path.join(FIXTURES, d, "source.md")))


def read(case, name):
    with open(os.path.join(FIXTURES, case, name), "r", encoding="utf-8") as f:
        return f.read()


def write(case, name, text):
    with open(os.path.join(FIXTURES, case, name), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def trust_of(case):
    path = os.path.join(FIXTURES, case, "meta.json")
    if not os.path.exists(path):
        return present.ASSISTANT
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f).get("trust", present.ASSISTANT)


def chunk_dicts(chunks):
    out = []
    for c in chunks:
        item = {"text": str(c.text)}
        if c.reply_markup:
            item["reply_markup"] = c.reply_markup
        out.append(item)
    return out


def dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def outputs(case):
    """這個案例現在的四種輸出（黃金檔比的就是這些字）。"""
    doc = present.document(read(case, "source.md"), trust=trust_of(case))
    return {
        "blocks.json": dump(doc.to_dict()),
        "telegram.json": dump(chunk_dicts(present.render(doc, "telegram"))),
        "discord.json": dump(chunk_dicts(present.render(doc, "discord"))),
        "web.html": web_out.to_html(doc) + "\n",
    }


# ── 不變量 ───────────────────────────────────────────────────────────

def check_html(text, allowed):
    """每個 < 都是白名單標籤的開頭、屬性只有白名單的、標籤成對且正確巢狀；每個 & 都是實體。"""
    stack = []
    for m in re.finditer("<", text):
        tag = _TAG.match(text, m.start())
        assert tag, f"unescaped '<' at {m.start()}: {text[m.start():m.start() + 40]!r}"
        closing, name, attrs = tag.group(1), tag.group(2), tag.group(3)
        assert name in allowed, f"tag <{name}> not allowed"
        for key, value in _ATTR.findall(attrs):
            assert key in allowed[name], f"attribute {key} not allowed on <{name}>"
            assert not key.startswith("on") and key != "style"
            if key == "href":
                assert value.startswith(("http://", "https://")), value
        if closing:
            assert stack and stack[-1] == name, f"unbalanced </{name}> (open: {stack})"
            stack.pop()
        else:
            stack.append(name)
    assert not stack, f"unclosed tags: {stack}"
    for m in re.finditer("&", text):
        assert _ENTITY.match(text, m.start()), f"raw '&' at {m.start()}: {text[m.start():m.start() + 12]!r}"
    assert ">" not in _TAG.sub("", text), "raw '>' outside a tag"


def check_telegram(chunks):
    assert chunks
    for i, c in enumerate(chunks):
        assert utf16_len(c.text) <= 4096
        assert c.text.strip()
        check_html(str(c.text), TELEGRAM_TAGS)
        if i < len(chunks) - 1:
            assert c.reply_markup is None, "buttons only on the last message"


def check_discord(chunks):
    assert chunks
    for i, c in enumerate(chunks):
        assert utf16_len(c.text) <= 2000
        assert c.text.strip()
        fences = [line for line in c.text.split("\n") if line.startswith("```")]
        assert len(fences) % 2 == 0, "every message closes its own code fence"
        if i < len(chunks) - 1:
            assert c.reply_markup is None, "buttons only on the last message"


def check_all(doc):
    """一份內容在三個通道都要守的不變量。"""
    check_telegram(present.render(doc, "telegram"))
    check_discord(present.render(doc, "discord"))
    check_html(web_out.to_html(doc), WEB_TAGS)
    if doc.trust != present.SYSTEM:
        for channel in present.CHANNELS:
            assert all(c.reply_markup is None for c in present.render(doc, channel)), channel
