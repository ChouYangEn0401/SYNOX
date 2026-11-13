"""
Draw the .synoxpack file icon (src/synox/assets/synoxpack.ico): a teal rounded tile with a white
"download into a tray" arrow, so Explorer shows an installer-looking file instead of a blank page.

Standard library only (struct, zlib); deterministic output, so re-running gives the same bytes.
Sizes 16, 24, 32, 48 are 32-bit BMP entries (oldest Explorer code paths read these), 256 is PNG.

    .venv\\Scripts\\python.exe scripts\\make_pack_icon.py                    -> src\\synox\\assets\\synoxpack.ico
    .venv\\Scripts\\python.exe scripts\\make_pack_icon.py --preview <dir>    also writes PNGs to look at
"""

from __future__ import annotations

import argparse
import os
import struct
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "src", "synox", "assets", "synoxpack.ico")
SIZES = (16, 24, 32, 48, 256)
SS = 4                                    # supersampling per axis (anti-aliasing)

TOP = (0x1A, 0xB0, 0x9C)                  # tile gradient (brand teal, see web/static/app.html --accent)
BOTTOM = (0x0A, 0x7C, 0x70)
EDGE = (0x06, 0x5A, 0x51)
WHITE = (0xFF, 0xFF, 0xFF)


def _in_round_rect(x, y, x0, y0, x1, y1, r):
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _in_triangle(x, y, a, b, c):
    def side(p, q):
        return (x - q[0]) * (p[1] - q[1]) - (p[0] - q[0]) * (y - q[1])
    d1, d2, d3 = side(a, b), side(b, c), side(c, a)
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


def _glyph(x, y, small):
    """White parts in unit coordinates (0..1, y down): arrow shaft + head, and a tray under it."""
    shaft = 0.085 if not small else 0.10
    if 0.5 - shaft <= x <= 0.5 + shaft and 0.17 <= y <= 0.50:
        return True
    if _in_triangle(x, y, (0.25, 0.46), (0.75, 0.46), (0.5, 0.71)):
        return True
    t = 0.075 if not small else 0.09        # tray thickness
    if 0.20 <= x <= 0.80 and 0.80 - t <= y <= 0.80:
        return True
    if 0.58 <= y <= 0.80 and (0.20 <= x <= 0.20 + t or 0.80 - t <= x <= 0.80):
        return True
    return False


def render(n: int):
    """n x n RGBA rows (top to bottom), each a list of (r, g, b, a)."""
    small = n <= 24
    pad = 0.04 if small else 0.06
    radius = 0.18
    border = 1.0 / n if small else 0.012
    rows = []
    for py in range(n):
        row = []
        for px in range(n):
            tile = edge = glyph = 0
            for sy in range(SS):
                for sx in range(SS):
                    x = (px + (sx + 0.5) / SS) / n
                    y = (py + (sy + 0.5) / SS) / n
                    if not _in_round_rect(x, y, pad, pad, 1 - pad, 1 - pad, radius):
                        continue
                    tile += 1
                    if not _in_round_rect(x, y, pad + border, pad + border, 1 - pad - border, 1 - pad - border,
                                          radius - border):
                        edge += 1
                    elif _glyph(x, y, small):
                        glyph += 1
            total = SS * SS
            if not tile:
                row.append((0, 0, 0, 0))
                continue
            t = py / max(n - 1, 1)
            fill = tuple(round(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3))
            body = tile - edge - glyph
            rgb = tuple(round((fill[i] * body + EDGE[i] * edge + WHITE[i] * glyph) / tile) for i in range(3))
            row.append(rgb + (round(255 * tile / total),))
        rows.append(row)
    return rows


def png_bytes(rows) -> bytes:
    n = len(rows)
    raw = b"".join(b"\x00" + bytes(c for px in row for c in px) for row in rows)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def bmp_bytes(rows) -> bytes:
    """ICO-style DIB: BITMAPINFOHEADER (height doubled), bottom-up BGRA, then an all-zero AND mask."""
    n = len(rows)
    header = struct.pack("<IiiHHIIiiII", 40, n, n * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    pixels = b"".join(bytes((b, g, r, a)) for row in reversed(rows) for (r, g, b, a) in row)
    mask_row = ((n + 31) // 32) * 4
    return header + pixels + b"\x00" * (mask_row * n)


def ico_bytes(images) -> bytes:
    """images: [(size, data)]."""
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    body = b""
    for size, data in images:
        dim = 0 if size >= 256 else size
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset + len(body))
        body += data
    return out + body


def build():
    images, previews = [], {}
    for n in SIZES:
        rows = render(n)
        previews[n] = png_bytes(rows)
        images.append((n, previews[n] if n >= 256 else bmp_bytes(rows)))
    return ico_bytes(images), previews


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="draw src/synox/assets/synoxpack.ico")
    parser.add_argument("--out", default=OUT)
    parser.add_argument("--preview", default="", help="folder for synoxpack-<size>.png previews")
    args = parser.parse_args(argv)
    ico, previews = build()
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(ico)
    print(f"wrote {args.out} ({len(ico)} bytes; sizes {', '.join(map(str, SIZES))})")
    if args.preview:
        os.makedirs(args.preview, exist_ok=True)
        for n, data in previews.items():
            with open(os.path.join(args.preview, f"synoxpack-{n}.png"), "wb") as f:
                f.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
