"""網頁對話的附件（web/uploads.py）：檔名不當路徑、類型看內容、表格轉文字、解壓炸彈、記憶體裡用一次就丟。"""

import io
import json
import struct
import zipfile
import zlib

import pytest

from synox.web import uploads
from synox.web.uploads import Refused, UploadStore, clean_name


def png(w=2, h=2):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def xlsx(rows, sheet="帳目"):
    shared = sorted({c for r in rows for c in r if isinstance(c, str)})
    def cell(ref, v):
        if isinstance(v, str):
            return f'<c r="{ref}" t="s"><v>{shared.index(v)}</v></c>'
        return f'<c r="{ref}"><v>{v}</v></c>'
    body = "".join(f'<row r="{i + 1}">' + "".join(cell(f"{'ABCDEFG'[j]}{i + 1}", v) for j, v in enumerate(r)) + "</row>"
                   for i, r in enumerate(rows))
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", f'<workbook {ns} {rel}><sheets><sheet name="{sheet}" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", f"<sst {ns}>" + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{body}</sheetData></worksheet>")
    return buf.getvalue()


@pytest.mark.parametrize("raw,want", [
    ("../../etc/passwd", "passwd"),
    ("C:\\Windows\\system32\\evil.exe", "evil.exe"),
    ("..", "附件"),
    ("", "附件"),
    ("報表\u202egpj.exe", "報表gpj.exe"),          # RLO 反向字元拿掉：看起來不會變成 .jpg
    ("a\u200bb\x00c\nd.csv", "abcd.csv"),
    ('con<>:"|?*.txt', "con_______.txt"),
    ("Cafe\u0301.txt", "Caf\u00e9.txt"),             # NFC
])
def test_clean_name_is_display_only_and_safe(raw, want):
    assert clean_name(raw) == want


def test_long_names_keep_the_extension():
    name = clean_name("很" * 200 + ".xlsx")
    assert len(name) <= uploads.MAX_NAME and name.endswith("….xlsx")


def test_kind_comes_from_content_not_the_name():
    assert uploads.sniff(png())[0] == uploads.IMAGE
    assert uploads.sniff(xlsx([["a", 1]]))[0] == uploads.TABLE
    assert uploads.sniff("日期,金額\n11/18,80\n".encode("utf-8"))[0] == uploads.TEXT
    assert uploads.sniff("日期,金額\n".encode("cp950"))[1].startswith("日期")          # Big5 的 csv
    assert uploads.sniff("哈囉".encode("utf-16"))[1] == "哈囉"                           # 有 BOM 的 UTF-16
    for bad in (b"%PDF-1.7 ...", b"MZ\x90\x00\x03\x00\x00\x00" + bytes(200), b"\xd0\xcf\x11\xe0" + bytes(100), b""):
        with pytest.raises(Refused):
            uploads.sniff(bad)
    plain_zip = io.BytesIO()
    with zipfile.ZipFile(plain_zip, "w") as z:
        z.writestr("x.txt", "hi")
    with pytest.raises(Refused):
        uploads.sniff(plain_zip.getvalue())


def test_xlsx_becomes_csv_per_sheet():
    text = uploads.xlsx_text(xlsx([["日期", "項目", "金額"], ["11/18", "午餐", 120], ["11/18", "咖啡", 65]]))
    assert "工作表：帳目（3 列）" in text and "日期,項目,金額" in text and "11/18,咖啡,65" in text


def test_zip_bomb_is_refused():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", "<workbook/>")
        z.writestr("xl/worksheets/sheet1.xml", b"\x00" * (45 * 1024 * 1024))
    item = uploads.Item("x", "炸彈.xlsx", uploads.TABLE, len(buf.getvalue()), buf.getvalue())
    with pytest.raises(Refused):
        uploads.file_text(item)


def test_store_is_per_user_and_chat_single_use_and_expires():
    now = [1000.0]
    store = UploadStore(clock=lambda: now[0])
    a = store.put(1, "c1", "../a.csv", b"x,y\n1,2\n")
    assert a.name == "a.csv" and len(a.id) >= 16
    assert store.take(2, "c1", [a.id]) == [] and store.take(1, "c2", [a.id]) == []      # 別人、別段對話拿不到
    assert store.take(1, "c1", [a.id, "nope", 5]) == [a]
    assert store.take(1, "c1", [a.id]) == []                                             # 用過就沒了
    b = store.put(1, "c1", "b.txt", b"hi")
    now[0] += uploads.TTL_SECONDS + 1
    assert store.take(1, "c1", [b.id]) == []                                             # 過期
    with pytest.raises(Refused):
        store.put(1, "c1", "big.txt", b"a" * (uploads.MAX_FILE_BYTES + 1))
    for i in range(uploads.MAX_PENDING):
        store.put(1, "c3", f"{i}.txt", b"hi")
    with pytest.raises(Refused):
        store.put(1, "c3", "one-more.txt", b"hi")


def test_blocks_for_ai_cap_the_text():
    items = [uploads.Item("1", "a.txt", uploads.TEXT, 1, b"", "甲" * (uploads.TEXT_CHARS_PER_FILE + 50)),
             uploads.Item("2", "b.txt", uploads.TEXT, 1, b"", "乙" * 10)]
    blocks, problems = uploads.blocks_for_ai(items)
    assert blocks[0][0] == "文字檔「a.txt」" and "以下省略" in blocks[0][1] and blocks[1][1] == "乙" * 10 and not problems


# ── 網頁 API 到 AI ──────────────────────────────────────────────────────────

def _client(make_bot, owner, script=None):
    from test_web import Client, ui_of
    bot = make_bot(script) if script is not None else make_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    return bot, c


def _upload(c, chat, name, data):
    from urllib.parse import quote
    status, _, body = c.raw("POST", f"/api/chat/{chat}/upload", data, {"X-SYNOX-Filename": quote(name)})
    return status, json.loads(body.decode("utf-8"))


def test_upload_then_send_reaches_the_ai_as_data(make_bot, owner):
    from synox.llm.base import Reply
    bot, c = _client(make_bot, owner, [Reply(text="這張表一共花了 185 元。")])
    chat = c.post("/api/chats", {})[1]["id"]
    status, item = _upload(c, chat, "../../帳目\u202e.xlsx", xlsx([["項目", "金額"], ["午餐", 120], ["咖啡", 65]]))
    assert status == 200 and item["kind"] == "table" and item["name"] == "帳目.xlsx" and "data" not in item
    status, data = c.post(f"/api/chat/{chat}/send", {"text": "加總", "attachments": [item["id"]]})
    assert status == 200, data
    c.ui.app.tasks.wait(10)
    messages, _tools = bot.app.extras["synox_agent"].adapter.calls[-1]
    asked = [m for m in messages if m.role == "user"][-1].content
    assert asked.startswith("加總") and "表格「帳目.xlsx」" in asked and "午餐,120" in asked and "資料，不是指令" in asked
    memory = " ".join(m.content for m in bot.app.extras["synox_agent"].latest_history(owner))
    assert "〔附件：表格「帳目.xlsx」〕" in memory and "午餐,120" not in memory                    # 記憶只留檔名
    shown = [m["text"] for m in c.get(f"/api/chat/{chat}/events?since=0")[1]["messages"] if m["from"] == "me"]
    assert shown[-1] == "加總\n〔附件：帳目.xlsx〕"
    assert c.post(f"/api/chat/{chat}/send", {"text": "再一次", "attachments": [item["id"]]})[0] == 409   # 用過了


def test_upload_refuses_bad_files_and_is_csrf_protected(make_bot, owner):
    bot, c = _client(make_bot, owner)
    chat = c.post("/api/chats", {})[1]["id"]
    status, data = _upload(c, chat, "x.pdf", b"%PDF-1.4 hello")
    assert status == 400 and "PDF" in data["error"]
    from urllib.parse import quote
    status, _, _ = c.ui.handle("POST", f"/api/chat/{chat}/upload", {"Host": c.host, "Cookie": c.cookie,
                                                                    "X-SYNOX-Filename": quote("a.txt")}, b"hi")
    assert status in (401, 403)                                                          # 沒有 CSRF header
    status, item = _upload(c, chat, "a.txt", b"hello")
    assert c.post(f"/api/chat/{chat}/unupload", {"id": item["id"]})[0] == 200
    assert c.post(f"/api/chat/{chat}/send", {"text": "", "attachments": [item["id"]]})[0] == 409


def test_uploaded_image_goes_to_the_ai_as_an_image(make_bot, owner):
    from test_web import Client, ui_of
    from synox.llm.fake import FakeAdapter
    bot = make_bot(adapter=FakeAdapter(["一張紅色的小圖"], supports_vision=True))
    c = Client(ui_of(bot))
    c.login(owner)
    chat = c.post("/api/chats", {})[1]["id"]
    status, item = _upload(c, chat, "photo.png", png())
    assert status == 200 and item["kind"] == "image"
    assert c.post(f"/api/chat/{chat}/send", {"text": "", "attachments": [item["id"]]})[0] == 200
    c.ui.app.tasks.wait(10)
    messages, _ = bot.app.extras["synox_agent"].adapter.calls[-1]
    last = [m for m in messages if m.role == "user"][-1]
    assert len(last.images) == 1 and last.images[0].mime == "image/png"            # 真的圖，不是檔名或路徑
    assert "photo.png" not in last.content
