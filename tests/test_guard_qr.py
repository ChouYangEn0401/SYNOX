"""自己畫的 QR（guard/qr.py）：用測試裡獨立寫的小解碼器讀回來（格式資訊 → 去遮罩 → 讀碼字 → 錯誤更正碼的餘數是 0 → 位元組）。"""

import pytest

from synox.guard import qr

pytestmark = pytest.mark.usefixtures("no_sockets")

BLOCKS_M = {1: (10, [16]), 2: (16, [28]), 3: (26, [44]), 4: (18, [32] * 2), 5: (24, [43] * 2), 6: (16, [27] * 4),
            7: (18, [31] * 4), 8: (22, [38, 38, 39, 39]), 9: (22, [36, 36, 36, 37, 37]),
            10: (26, [43, 43, 43, 43, 44])}
ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
         9: [6, 26, 46], 10: [6, 28, 50]}
MASKS = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
         lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
         lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
         lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0]
FINDER = ["1111111", "1000001", "1011101", "1011101", "1011101", "1000001", "1111111"]


def gf_mul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a <<= 1
        if a & 0x100:
            a ^= 0x11D
        b >>= 1
    return r


def gf_pow(a, n):
    r = 1
    for _ in range(n):
        r = gf_mul(r, a)
    return r


def function_map(n, v):
    f = [[False] * n for _ in range(n)]

    def mark(x0, y0, w, h):
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                f[y][x] = True
    mark(0, 0, 9, 9)
    mark(n - 8, 0, 8, 9)
    mark(0, n - 8, 9, 8)
    mark(6, 0, 1, n)
    mark(0, 6, n, 1)
    pos = ALIGN[v]
    for a in pos:
        for b in pos:
            if (a, b) in ((6, 6), (6, pos[-1]), (pos[-1], 6)):
                continue
            mark(a - 2, b - 2, 5, 5)
    if v >= 7:
        mark(n - 11, 0, 3, 6)
        mark(0, n - 11, 6, 3)
    return f


def decode(rows):
    n = len(rows)
    v = (n - 17) // 4
    g = [[c == "1" for c in r] for r in rows]
    spots = [(8, i) for i in range(6)] + [(8, 7), (8, 8), (7, 8)] + [(14 - i, 8) for i in range(9, 15)]
    raw = sum(int(g[y][x]) << i for i, (x, y) in enumerate(spots))
    fmt = raw ^ 0x5412
    data = fmt >> 10
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    assert (data << 10 | rem) == fmt, "format BCH"
    assert data >> 3 == 0, "level M"
    mask = MASKS[data & 7]
    f = function_map(n, v)
    bits = []
    right = n - 1
    while right >= 1:
        if right == 6:
            right = 5
        upward = ((right + 1) & 2) == 0
        for vert in range(n):
            y = n - 1 - vert if upward else vert
            for x in (right, right - 1):
                if not f[y][x]:
                    bits.append(int(g[y][x] ^ mask(x, y)))
        right -= 2
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits) - 7, 8)]
    ec, sizes = BLOCKS_M[v]
    blocks = [[] for _ in sizes]
    k = 0
    for i in range(max(sizes)):
        for b, size in enumerate(sizes):
            if i < size:
                blocks[b].append(words[k])
                k += 1
    for i in range(ec):
        for b in range(len(sizes)):
            blocks[b].append(words[k])
            k += 1
    for block in blocks:
        for i in range(ec):
            s = 0
            a = gf_pow(2, i)
            for c in block:
                s = gf_mul(s, a) ^ c
            assert s == 0, "Reed-Solomon syndrome"
    stream = "".join(format(w, "08b") for b, size in zip(blocks, sizes) for w in b[:size])
    assert stream[:4] == "0100"
    count_bits = 8 if v < 10 else 16
    count = int(stream[4:4 + count_bits], 2)
    body = stream[4 + count_bits:4 + count_bits + 8 * count]
    return bytes(int(body[i:i + 8], 2) for i in range(0, len(body), 8)).decode("utf-8")


@pytest.mark.parametrize("length", [20, 60, 120])
def test_round_trip(length):
    text = ("otpauth://totp/SYNOX:owner?secret=JBSWY3DPEHPK3PXP&issuer=SYNOX" * 3)[:length]
    rows = qr.matrix(text)
    assert decode(rows) == text


def test_real_uri_and_unicode():
    from isdtelekit.security import totp
    uri = totp.provisioning_uri(totp.new_secret(), "user-123456789", issuer="SYNOX")
    assert decode(qr.matrix(uri)) == uri
    assert decode(qr.matrix("中文 ok")) == "中文 ok"


def test_finders_in_three_corners():
    rows = qr.matrix("x" * 60)
    n = len(rows)
    for x0, y0 in ((0, 0), (n - 7, 0), (0, n - 7)):
        assert [rows[y0 + i][x0:x0 + 7] for i in range(7)] == FINDER
    assert rows[n - 8][8] == "1"                                   # 固定的黑點


def test_too_long():
    with pytest.raises(ValueError):
        qr.matrix("x" * 300)


def test_terminal_render():
    out = qr.terminal(qr.matrix("abc"))
    assert set(out) <= set("█▀▄ \n")
