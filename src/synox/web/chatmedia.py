"""
工具回覆帶的圖（和弦圖、圖表…）：檢查、存檔、讀回來給網頁的 <img>（docs/sdk.md「回覆帶圖」）。

    images = prepare([{"svg": b"<svg…>", "png": b"\\x89PNG…", "alt": "D/F# 和弦圖"}, b"\\x89PNG…"])
        -> [Prepared(mime, data, w, h, alt)]                不收的丟 Refused（一句話說原因）
    media = ChatMedia(folder, vault)
    media.put(tg_id, prepared) -> 隨機 id                    存檔（有保管箱＝那個人的金鑰加密）
    media.get(tg_id, id) -> (mime, bytes) 或 None
    media.drop(tg_id, ids)                                   訊息被擠掉、清空、刪掉時一起刪

安全（擁有者 2026-11-18：工具要能送圖給使用者，但不能變成注入的管道）：
- **類型看內容**：點陣圖看檔頭（llm.vision.sniff：PNG／JPEG／WebP／GIF），寬高看檔頭、每邊 ≤ MAX_SIDE、像素 ≤ MAX_PIXELS；
  不信副檔名、不信工具說的類型。
- **SVG 嚴格白名單、重新產生**：有 DOCTYPE／ENTITY 直接不收；用 ElementTree 解析，只准白名單裡的元素與屬性
  （沒有 script、foreignObject、use、image、a、style、動畫；沒有 on* 屬性、沒有 href／xlink:href、沒有帶命名空間的屬性；
  屬性值不准有 url(、javascript:、<、&），有任何一樣不在白名單＝整張不收（不是刪掉那一段再收）。
  存的是**照白名單重新寫出來的** SVG（不是工具給的原始位元組），所以註解、處理指令、CDATA 之類一律不會留下來。
- 給瀏覽器時一律用 <img src="同源網址">（不 inline 插進 DOM）：<img> 裡的 SVG 本來就不跑程式、不抓外部資源；
  網址本身回 `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; sandbox`＋nosniff，直接開那個網址也不會跑程式。
- 大小：每張 ≤ MAX_BYTES；一則訊息 ≤ MAX_IMAGES 張；alt ≤ 200 字。
- 檔名是隨機 id（secrets.token_urlsafe），從來不用工具給的名字當路徑。
"""

from __future__ import annotations

import os
import re
import secrets
import threading
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple
from xml.etree import ElementTree

MAX_IMAGES = 8
MAX_BYTES = 2 * 1024 * 1024
MAX_SVG_BYTES = 512 * 1024
MAX_SVG_NODES = 5000
MAX_SIDE = 4096
MAX_PIXELS = 16_000_000
MAX_ALT = 200
SVG = "image/svg+xml"
ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,40}$")
_NS = "{http://www.w3.org/2000/svg}"

SVG_ELEMENTS = frozenset(("svg", "g", "line", "rect", "circle", "ellipse", "path", "polyline", "polygon", "text",
                          "tspan", "title", "desc"))
SVG_ATTRS = frozenset((
    "viewBox", "width", "height", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "d", "points",
    "dx", "dy", "transform", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-dasharray",
    "opacity", "fill-opacity", "stroke-opacity", "font-size", "font-family", "font-weight", "font-style",
    "text-anchor", "dominant-baseline", "letter-spacing", "preserveAspectRatio", "version", "role", "aria-label",
    "class", "id", "fill-rule", "shape-rendering", "text-rendering"))
_BAD_VALUE = re.compile(r"url\s*\(|javascript:|data:|expression\s*\(|[<>&\\]|@import", re.IGNORECASE)
_VALUE_RE = re.compile(r"^[\x20-\x7e -￿]*$")


class Refused(Exception):
    """這張圖不收；訊息是給人看的一句話。"""


@dataclass
class Prepared:
    mime: str
    data: bytes
    w: int
    h: int
    alt: str = ""

    def meta(self, image_id: str) -> dict:
        return {"id": image_id, "type": self.mime, "w": int(self.w), "h": int(self.h), "alt": self.alt}


def _num(value: str) -> Optional[float]:
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(?:px)?\s*$", value or "")
    return float(m.group(1)) if m else None


def _esc(text: str, attr: bool = False) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.replace('"', "&quot;") if attr else text


def sanitize_svg(data: bytes) -> Tuple[bytes, int, int]:
    """白名單檢查＋照白名單重新寫出來。(新的 SVG 位元組, 寬, 高)；有任何不准的東西丟 Refused。"""
    if len(data) > MAX_SVG_BYTES:
        raise Refused("SVG 太大。")
    low = data.lower()
    if b"<!doctype" in low or b"<!entity" in low:
        raise Refused("SVG 不能有 DOCTYPE／ENTITY。")
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        raise Refused("SVG 格式不對。")
    if root.tag != _NS + "svg":
        raise Refused("不是 SVG（最外層要是 <svg>）。")
    count = 0

    def walk(el) -> str:
        nonlocal count
        count += 1
        if count > MAX_SVG_NODES:
            raise Refused("SVG 的元素太多。")
        if not isinstance(el.tag, str) or not el.tag.startswith(_NS):
            raise Refused("SVG 裡有不認得的元素。")
        name = el.tag[len(_NS):]
        if name not in SVG_ELEMENTS:
            raise Refused(f"SVG 裡有不准的元素 <{name}>。")
        attrs = []
        for key, value in el.attrib.items():
            if key.startswith("{") or key not in SVG_ATTRS or key.lower().startswith("on"):
                raise Refused(f"SVG 裡有不准的屬性 {key}。")
            if len(value) > 20000 or _BAD_VALUE.search(value) or not _VALUE_RE.match(value):
                raise Refused(f"SVG 的屬性 {key} 的值不准。")
            attrs.append(f' {key}="{_esc(value, True)}"')
        inner = _esc(el.text or "") + "".join(walk(child) + _esc(child.tail or "") for child in el)
        return f"<{name}{''.join(attrs)}>{inner}</{name}>"

    body = walk(root)
    clean = body.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1).encode("utf-8")
    w, h = _num(root.get("width", "")), _num(root.get("height", ""))
    if (w is None or h is None) and root.get("viewBox"):
        parts = re.split(r"[\s,]+", root.get("viewBox").strip())
        if len(parts) == 4:
            w = w if w is not None else _num(parts[2])
            h = h if h is not None else _num(parts[3])
    if not w or not h:
        raise Refused("SVG 要有 width／height 或 viewBox。")
    if w > MAX_SIDE or h > MAX_SIDE:
        raise Refused("SVG 太大（邊長）。")
    return clean, int(round(w)), int(round(h))


def check_raster(data: bytes) -> Tuple[str, int, int]:
    from synox.llm import vision
    mime = vision.sniff(data)
    if not mime:
        raise Refused("看不出是 PNG／JPEG／WebP／GIF。")
    dims = vision.dimensions(data, mime)
    if not dims or dims[0] <= 0 or dims[1] <= 0:
        raise Refused("讀不出圖的寬高。")
    w, h = dims
    if w > MAX_SIDE or h > MAX_SIDE or w * h > MAX_PIXELS:
        raise Refused("圖太大（寬高）。")
    return mime, int(w), int(h)


def _clean_alt(text) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(text or "")).strip()
    return text[:MAX_ALT]


def prepare_one(item, prefer_svg: bool = True) -> Prepared:
    """一張圖：bytes（點陣圖）或 {"svg": …, "png": …／"data": …, "alt": …}。有 SVG 又 prefer_svg＝用 SVG，
    SVG 不收就退回點陣圖；都沒有／都不收丟 Refused。"""
    if isinstance(item, (bytes, bytearray)):
        item = {"data": bytes(item)}
    if not isinstance(item, dict):
        raise Refused("圖要是 bytes 或 {svg, png, alt}。")
    alt = _clean_alt(item.get("alt"))
    raster = item.get("png") or item.get("data")
    problem = None
    svg = item.get("svg")
    if svg and prefer_svg:
        try:
            data, w, h = sanitize_svg(bytes(svg if isinstance(svg, (bytes, bytearray)) else str(svg).encode("utf-8")))
            return Prepared(SVG, data, w, h, alt)
        except Refused as e:
            problem = e
    if raster:
        raster = bytes(raster)
        if len(raster) > MAX_BYTES:
            raise Refused("圖太大（檔案大小）。")
        mime, w, h = check_raster(raster)
        return Prepared(mime, raster, w, h, alt)
    raise problem or Refused("沒有圖。")


def prepare(items: Iterable, prefer_svg: bool = True) -> Tuple[List[Prepared], List[str]]:
    """好幾張：(收下的, 不收的原因)。超過 MAX_IMAGES 張的後面不收。"""
    out, problems = [], []
    for item in list(items or []):
        if len(out) >= MAX_IMAGES:
            problems.append(f"一則最多 {MAX_IMAGES} 張圖，後面的不收。")
            break
        try:
            out.append(prepare_one(item, prefer_svg))
        except Refused as e:
            problems.append(str(e))
    return out, problems


class ChatMedia:
    """網頁對話的圖：data/web_chats/media/<tg_id>/<id>.img（有保管箱＝.img.enc，那個人的金鑰）。"""

    def __init__(self, folder: str, vault=None):
        self.folder = folder
        self._vault = vault
        self._lock = threading.Lock()

    def _dir(self, tg_id: int) -> str:
        return os.path.join(self.folder, str(int(tg_id)))

    def _path(self, tg_id: int, image_id: str) -> str:
        if not ID_RE.match(image_id or ""):
            raise ValueError("bad image id")
        return os.path.join(self._dir(tg_id), image_id + (".img.enc" if self._vault is not None else ".img"))

    def _box(self, tg_id: int):
        return self._vault.for_user(int(tg_id)).at(self._dir(tg_id)) if self._vault is not None else None

    def put(self, tg_id: int, image: Prepared) -> str:
        image_id = secrets.token_urlsafe(12)
        path = self._path(tg_id, image_id)
        head = image.mime.encode("ascii") + b"\n"
        box = self._box(tg_id)
        blob = box.encrypt_bytes(head + image.data) if box is not None else head + image.data
        with self._lock:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(blob)
        return image_id

    def get(self, tg_id: int, image_id: str) -> Optional[Tuple[str, bytes]]:
        try:
            path = self._path(tg_id, image_id)
        except ValueError:
            return None
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            blob = f.read()
        box = self._box(tg_id)
        try:
            raw = box.decrypt_bytes(blob, where="對話的圖") if box is not None else blob
        except Exception:
            return None
        mime, _, data = raw.partition(b"\n")
        mime = mime.decode("ascii", "replace")
        if mime not in (SVG, "image/png", "image/jpeg", "image/webp", "image/gif"):
            return None
        return mime, data

    def drop(self, tg_id: int, ids: Iterable[str]) -> None:
        for image_id in ids or []:
            try:
                path = self._path(tg_id, str(image_id))
            except ValueError:
                continue
            try:
                os.remove(path)
            except OSError:
                pass


def image_ids(messages: Iterable[dict]) -> List[str]:
    return [str(i.get("id")) for m in messages or [] for i in (m.get("images") or []) if isinstance(i, dict)]
