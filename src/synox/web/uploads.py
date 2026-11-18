"""
網頁對話的附件（圖片、表格、文字檔）：只放在記憶體、不寫硬碟、用完就丟（docs/adr/0021 的網頁版）。

    store.put(tg_id, chat, raw_name, data) -> (item 或 None, 錯誤一句話)
    store.take(tg_id, chat, ids) -> [item, ...]       送出訊息時拿走（拿了就刪，只能用一次）
    read(item) -> Attachment                           圖片 → ImagePart；表格／文字 → 給 AI 看的純文字

安全（擁有者 2026-11-18：（需求原文不公開））：
- **檔名從來不當路徑用**：附件不寫硬碟，存在記憶體的 dict，鑰匙是隨機 id（secrets.token_urlsafe）。
  檔名只拿來顯示：`clean_name` 去掉路徑（/ \\ 前面的全部）、控制字元、Unicode 格式字元（含 RLO 等反向字元、零寬字元）、
  Windows 保留字元 <>:"|?*，做 NFC 正規化、限長 80 字；清完是空的＝「附件」。
- **類型看內容，不信副檔名、不信瀏覽器給的 Content-Type**：圖片看檔頭（vision.sniff）；xlsx／docx 看 zip 裡有沒有
  `[Content_Types].xml` 和 `xl/`、`word/`；PDF 和其他二進位一律不收（說明原因）；文字檔要能用 UTF-8（含 BOM）／UTF-16／
  Big5（cp950）解得開，而且沒有 NUL。
- **解壓炸彈**：xlsx／docx 的 zip 先看每個成員宣告的大小（總和 ≤ 40 MB、壓縮比 ≤ 100），讀的時候也限量；不解開任何
  成員到硬碟。XML 用標準函式庫 ElementTree（expat 不抓外部實體；Python 3.13 內建的 expat 有擋實體展開炸彈）。
- 大小：每個檔 ≤ 10 MB（圖片照 llm.vision_limits 再擋一次）；每人同時最多 10 個沒送出的附件、30 分鐘沒送就丟。
- 給 AI 的文字有上限（每檔 12000 字、合計 24000 字），超過就截斷並註明；內容由 agent 包進這一輪的分隔符（資料不是指令）。
- 對話記憶只留「〔附件：檔名〕」替身，不留內容（跟圖片一樣）。
"""

from __future__ import annotations

import codecs
import csv
import io
import re
import secrets
import threading
import time
import unicodedata
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PENDING = 10
TTL_SECONDS = 30 * 60
MAX_NAME = 80
TEXT_CHARS_PER_FILE = 12000
TEXT_CHARS_TOTAL = 24000
ZIP_MAX_TOTAL = 40 * 1024 * 1024
ZIP_MAX_RATIO = 100
XLSX_MAX_ROWS = 2000
XLSX_MAX_SHEETS = 10

IMAGE, TABLE, DOCUMENT, TEXT = "image", "table", "document", "text"
KIND_LABELS = {IMAGE: "圖片", TABLE: "表格", DOCUMENT: "文件", TEXT: "文字檔"}
_BAD_NAME_CHARS = re.compile(r'[<>:"|?*]')
_SPACES = re.compile(r"\s+")
_NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_NS_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_NS_WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class Refused(Exception):
    """這個檔不收；訊息是給人看的一句話。"""


def clean_name(raw) -> str:
    """只給人看的檔名：去路徑、去控制字元與格式字元（RLO、零寬…）、去 Windows 保留字元、NFC、限長。永遠不當路徑用。"""
    name = unicodedata.normalize("NFC", str(raw or ""))
    name = re.split(r"[/\\]", name)[-1]
    name = "".join(ch for ch in name if unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"))
    name = _BAD_NAME_CHARS.sub("_", name)
    name = _SPACES.sub(" ", name).strip().strip(".").strip()
    if len(name) > MAX_NAME:
        stem, dot, ext = name.rpartition(".")
        ext = ext if dot and len(ext) <= 8 else ""
        name = (stem if ext else name)[: MAX_NAME - len(ext) - 2].rstrip() + "…" + ("." + ext if ext else "")
    return name or "附件"


# ── 判斷類型（看內容）────────────────────────────────────────────────

def _zip_kind(data: bytes) -> Optional[str]:
    if not data.startswith(b"PK\x03\x04"):
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
    except (zipfile.BadZipFile, ValueError, OSError):
        return None
    if "[Content_Types].xml" not in names:
        return None
    if "xl/workbook.xml" in names:
        return TABLE
    if "word/document.xml" in names:
        return DOCUMENT
    return None


def _decode_text(data: bytes) -> Optional[str]:
    if data.startswith(codecs.BOM_UTF8):
        try:
            return data[3:].decode("utf-8")
        except UnicodeDecodeError:
            return None
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            return None
    if b"\x00" in data:
        return None
    for enc in ("utf-8", "cp950"):
        try:
            text = data.decode(enc)
        except UnicodeDecodeError:
            continue
        bad = sum(1 for ch in text if unicodedata.category(ch) == "Cc" and ch not in "\t\r\n\f")
        if bad <= max(2, len(text) // 1000):
            return text
    return None


def sniff(data: bytes) -> Tuple[str, Optional[str]]:
    """(類型, 文字檔解碼後的字或 None)。不收丟 Refused。"""
    from synox.llm import vision
    if not data:
        raise Refused("是空的檔案。")
    if vision.sniff(data):
        return IMAGE, None
    if data.startswith(b"%PDF"):
        raise Refused("PDF 還不支援：請把內容複製成文字貼上，或另存成圖片／文字檔。")
    zk = _zip_kind(data)
    if zk:
        return zk, None
    if data.startswith(b"PK\x03\x04"):
        raise Refused("這是壓縮檔（zip），不收；表格請用 .xlsx 或 .csv。")
    if data.startswith(b"\xd0\xcf\x11\xe0"):
        raise Refused("這是舊版 Office 檔（.xls／.doc），不支援：請另存成 .xlsx／.docx 或 .csv。")
    text = _decode_text(data)
    if text is None:
        raise Refused("看不出是圖片、表格或文字檔（可能是程式或其他二進位檔），不收。")
    return TEXT, text


# ── 讀內容 ────────────────────────────────────────────────────────────

def _zip_read(z: zipfile.ZipFile, name: str, limit: int) -> bytes:
    with z.open(name) as f:
        data = f.read(limit + 1)
    if len(data) > limit:
        raise Refused("檔案裡的內容太大（解開後超過上限），不收。")
    return data


def _zip_guard(z: zipfile.ZipFile) -> None:
    total = 0
    for info in z.infolist():
        total += info.file_size
        if info.compress_size and info.file_size / max(info.compress_size, 1) > ZIP_MAX_RATIO and info.file_size > 1024 * 1024:
            raise Refused("檔案的壓縮比不正常（可能是解壓炸彈），不收。")
    if total > ZIP_MAX_TOTAL:
        raise Refused("檔案解開後太大，不收。")


def _col_index(ref: str) -> int:
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return max(n - 1, 0)


def xlsx_text(data: bytes) -> str:
    """xlsx → 每個工作表一段 CSV（只讀值；公式讀快取的結果）。最多 10 個工作表、每個 2000 列。"""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        _zip_guard(z)
        names = set(z.namelist())
        shared: List[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ElementTree.fromstring(_zip_read(z, "xl/sharedStrings.xml", ZIP_MAX_TOTAL))
            for si in root.iter(_NS_MAIN + "si"):
                shared.append("".join(t.text or "" for t in si.iter(_NS_MAIN + "t")))
        book = ElementTree.fromstring(_zip_read(z, "xl/workbook.xml", 4 * 1024 * 1024))
        rels = {}
        if "xl/_rels/workbook.xml.rels" in names:
            for rel in ElementTree.fromstring(_zip_read(z, "xl/_rels/workbook.xml.rels", 1024 * 1024)).iter(_NS_PKG_REL + "Relationship"):
                target = (rel.get("Target") or "").lstrip("/")
                rels[rel.get("Id")] = target if target.startswith("xl/") else "xl/" + target
        out: List[str] = []
        sheets = list(book.iter(_NS_MAIN + "sheet"))
        for i, sheet in enumerate(sheets[:XLSX_MAX_SHEETS]):
            path = rels.get(sheet.get(_NS_REL + "id")) or f"xl/worksheets/sheet{i + 1}.xml"
            if path not in names:
                continue
            root = ElementTree.fromstring(_zip_read(z, path, ZIP_MAX_TOTAL))
            buf = io.StringIO()
            writer = csv.writer(buf, lineterminator="\n")
            rows = 0
            cut = False
            for row in root.iter(_NS_MAIN + "row"):
                if rows >= XLSX_MAX_ROWS:
                    cut = True
                    break
                cells: Dict[int, str] = {}
                for c in row.iter(_NS_MAIN + "c"):
                    kind = c.get("t")
                    if kind == "inlineStr":
                        value = "".join(t.text or "" for t in c.iter(_NS_MAIN + "t"))
                    else:
                        v = c.find(_NS_MAIN + "v")
                        value = v.text if v is not None and v.text is not None else ""
                        if kind == "s" and value.isdigit() and int(value) < len(shared):
                            value = shared[int(value)]
                        elif kind == "b":
                            value = "TRUE" if value == "1" else "FALSE"
                    cells[_col_index(c.get("r") or "A")] = value
                if cells:
                    writer.writerow([cells.get(j, "") for j in range(max(cells) + 1)])
                    rows += 1
            title = sheet.get("name") or f"工作表 {i + 1}"
            out.append(f"## 工作表：{title}（{rows} 列{'，後面省略' if cut else ''}）\n{buf.getvalue().rstrip()}")
        if len(sheets) > XLSX_MAX_SHEETS:
            out.append(f"（還有 {len(sheets) - XLSX_MAX_SHEETS} 個工作表沒有讀）")
        return "\n\n".join(out) or "（這個表格是空的）"


def docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        _zip_guard(z)
        root = ElementTree.fromstring(_zip_read(z, "word/document.xml", ZIP_MAX_TOTAL))
    lines = []
    for p in root.iter(_NS_WORD + "p"):
        lines.append("".join(t.text or "" for t in p.iter(_NS_WORD + "t")))
    return "\n".join(lines).strip() or "（這份文件沒有文字）"


@dataclass
class Item:
    id: str
    name: str
    kind: str
    size: int
    data: bytes = field(repr=False)
    text: Optional[str] = field(default=None, repr=False)
    at: float = 0.0

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "kind": self.kind, "label": KIND_LABELS.get(self.kind, ""),
                "size": self.size}


def file_text(item: Item) -> str:
    """表格／文件／文字檔 → 給 AI 看的字（還沒截長度）。讀不出來丟 Refused。"""
    try:
        if item.kind == TABLE:
            return xlsx_text(item.data)
        if item.kind == DOCUMENT:
            return docx_text(item.data)
    except Refused:
        raise
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError, ValueError, OSError):
        raise Refused(f"「{item.name}」讀不出來（檔案可能壞了）。")
    return item.text or ""


def blocks_for_ai(items: List[Item]) -> Tuple[List[Tuple[str, str]], List[str]]:
    """非圖片的附件 → ([(標題, 內容)], 問題)。內容有上限，超過註明截斷。"""
    out: List[Tuple[str, str]] = []
    problems: List[str] = []
    left = TEXT_CHARS_TOTAL
    for item in items:
        try:
            text = file_text(item)
        except Refused as e:
            problems.append(str(e))
            continue
        if left <= 0:
            problems.append(f"「{item.name}」沒有給 AI：這則訊息的附件內容已經太長。")
            continue
        limit = min(TEXT_CHARS_PER_FILE, left)
        if len(text) > limit:
            text = text[:limit] + f"\n（以下省略：原本 {len(text)} 字，只給 AI 前 {limit} 字）"
        left -= len(text)
        out.append((f"{KIND_LABELS.get(item.kind, '檔案')}「{item.name}」", text))
    return out, problems


def placeholder(items: List[Item]) -> str:
    """對話記憶與畫面上的替身：不留內容。"""
    return "".join(f"〔附件：{i.name}〕" for i in items)


class UploadStore:
    """每個人、每段對話還沒送出的附件（只在記憶體）。"""

    def __init__(self, clock=time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self._items: Dict[Tuple[int, str], Dict[str, Item]] = {}

    def _sweep(self) -> None:
        now = self._clock()
        for key in list(self._items):
            box = self._items[key]
            for i in [i for i, it in box.items() if now - it.at > TTL_SECONDS]:
                del box[i]
            if not box:
                del self._items[key]

    def put(self, tg_id: int, chat: str, raw_name, data: bytes) -> Item:
        if len(data) > MAX_FILE_BYTES:
            raise Refused(f"檔案太大（每個最多 {MAX_FILE_BYTES // (1024 * 1024)} MB）。")
        name = clean_name(raw_name)
        kind, text = sniff(data)
        with self._lock:
            self._sweep()
            box = self._items.setdefault((int(tg_id), str(chat)), {})
            if len(box) >= MAX_PENDING:
                raise Refused(f"一次最多先放 {MAX_PENDING} 個附件；先送出再傳。")
            item = Item(secrets.token_urlsafe(12), name, kind, len(data), data, text, self._clock())
            box[item.id] = item
        return item

    def take(self, tg_id: int, chat: str, ids) -> List[Item]:
        """拿走（用一次就刪）；不是自己的、過期的、不存在的 id 一律略過。照傳進來的順序。"""
        with self._lock:
            self._sweep()
            box = self._items.get((int(tg_id), str(chat))) or {}
            out = []
            for i in ids or []:
                item = box.pop(str(i), None) if isinstance(i, str) else None
                if item is not None:
                    out.append(item)
            return out

    def drop(self, tg_id: int, chat: str, item_id: str) -> bool:
        with self._lock:
            box = self._items.get((int(tg_id), str(chat))) or {}
            return box.pop(str(item_id), None) is not None
