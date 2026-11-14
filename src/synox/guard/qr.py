"""自己畫的 QR（ADR 0025 §5.2）：純 Python、不加相依。位元組模式、容錯等級 M、版本 1–10。

    matrix("otpauth://totp/…") -> ["1111111010…", …]     每列一串 0／1（1＝黑）；放不下丟 ValueError

畫面用 canvas 照格子畫（security.js）；終端機用方塊字（`python -m synox stepup setup`）。
QR 是加分項：掃不到時手動輸入那串金鑰一樣能設定。演算法照 ISO/IEC 18004（Reed–Solomon、八種遮罩取罰分最低）。
"""

from __future__ import annotations

from typing import List

# 容錯等級 M：版本 → (每塊的錯誤更正碼字數, [(塊數, 每塊資料碼字數), …])
_M = {
    1: (10, [(1, 16)]), 2: (16, [(1, 28)]), 3: (26, [(1, 44)]), 4: (18, [(2, 32)]), 5: (24, [(2, 43)]),
    6: (16, [(4, 27)]), 7: (18, [(4, 31)]), 8: (22, [(2, 38), (2, 39)]), 9: (22, [(3, 36), (2, 37)]),
    10: (26, [(4, 43), (1, 44)]),
}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
          9: [6, 26, 46], 10: [6, 28, 50]}
_REMAINDER = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7, 7: 0, 8: 0, 9: 0, 10: 0}
_EC_M = 0                               # 格式資訊裡 M 的兩個位元


def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree: int) -> List[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data: List[int], divisor: List[int]) -> List[int]:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


def _capacity(version: int) -> int:
    return sum(n * size for n, size in _M[version][1])


def _codewords(data: bytes, version: int) -> List[int]:
    bits: List[int] = []

    def put(value: int, n: int) -> None:
        bits.extend((value >> i) & 1 for i in reversed(range(n)))

    put(0b0100, 4)
    put(len(data), 8 if version < 10 else 16)
    for b in data:
        put(b, 8)
    cap_bits = _capacity(version) * 8
    put(0, min(4, cap_bits - len(bits)))
    put(0, (-len(bits)) % 8)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(words) < _capacity(version):
        words.append(pad)
        pad = 0x11 if pad == 0xEC else 0xEC
    ec_len, groups = _M[version]
    blocks, k = [], 0
    for n, size in groups:
        for _ in range(n):
            blocks.append(words[k:k + size])
            k += size
    divisor = _rs_divisor(ec_len)
    ecs = [_rs_remainder(b, divisor) for b in blocks]
    out: List[int] = []
    for i in range(max(len(b) for b in blocks)):
        out.extend(b[i] for b in blocks if i < len(b))
    for i in range(ec_len):
        out.extend(e[i] for e in ecs)
    return out


class _Grid:
    def __init__(self, version: int):
        self.version = version
        self.size = 17 + 4 * version
        self.dark = [[False] * self.size for _ in range(self.size)]
        self.func = [[False] * self.size for _ in range(self.size)]

    def set(self, x: int, y: int, dark: bool) -> None:
        self.dark[y][x] = dark
        self.func[y][x] = True

    def draw_function(self) -> None:
        n = self.size
        for i in range(n):
            self.set(6, i, i % 2 == 0)
            self.set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        self.set(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = _ALIGN[self.version]
        last = len(pos) - 1
        for i, a in enumerate(pos):
            for j, b in enumerate(pos):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set(a + dx, b + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format(0)
        if self.version >= 7:
            rem = self.version
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.version << 12 | rem
            for i in range(18):
                bit = (bits >> i) & 1 == 1
                a, b = n - 11 + i % 3, i // 3
                self.set(a, b, bit)
                self.set(b, a, bit)

    def draw_format(self, mask: int) -> None:
        data = _EC_M << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        n = self.size

        def bit(i: int) -> bool:
            return (bits >> i) & 1 == 1

        for i in range(6):
            self.set(8, i, bit(i))
        self.set(8, 7, bit(6))
        self.set(8, 8, bit(7))
        self.set(7, 8, bit(8))
        for i in range(9, 15):
            self.set(14 - i, 8, bit(i))
        for i in range(8):
            self.set(n - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set(8, n - 15 + i, bit(i))
        self.set(8, n - 8, True)

    def draw_codewords(self, words: List[int]) -> None:
        n = self.size
        total = len(words) * 8
        i = 0
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = n - 1 - vert if upward else vert
                    if not self.func[y][x] and i < total:
                        self.dark[y][x] = (words[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        for y in range(self.size):
            for x in range(self.size):
                if not self.func[y][x] and _MASKS[mask](x, y):
                    self.dark[y][x] = not self.dark[y][x]

    def penalty(self) -> int:
        n, grid = self.size, self.dark
        score = 0
        lines = [grid[y] for y in range(n)] + [[grid[y][x] for y in range(n)] for x in range(n)]
        finder_a = [True, False, True, True, True, False, True, False, False, False, False]
        finder_b = finder_a[::-1]
        for line in lines:
            run, prev = 0, None
            for v in line:
                if v == prev:
                    run += 1
                else:
                    if run >= 5:
                        score += 3 + run - 5
                    run, prev = 1, v
            if run >= 5:
                score += 3 + run - 5
            for k in range(n - 10):
                window = list(line[k:k + 11])
                if window == finder_a or window == finder_b:
                    score += 40
        for y in range(n - 1):
            for x in range(n - 1):
                c = grid[y][x]
                if c == grid[y][x + 1] == grid[y + 1][x] == grid[y + 1][x + 1]:
                    score += 3
        dark = sum(sum(1 for v in row if v) for row in grid)
        total = n * n
        k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
        return score + max(0, k) * 10


_MASKS = [
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
]


def matrix(text: str) -> List[str]:
    """text（UTF-8 位元組）→ QR 的格子，每列一串 0／1。版本 1–10 放不下丟 ValueError。"""
    data = str(text).encode("utf-8")
    version = None
    for v in range(1, 11):
        need_bits = 4 + (8 if v < 10 else 16) + 8 * len(data)
        if need_bits <= _capacity(v) * 8:
            version = v
            break
    if version is None:
        raise ValueError("text too long for a version 1-10 QR code")
    words = _codewords(data, version)
    best, best_score = None, None
    for mask in range(8):
        g = _Grid(version)
        g.draw_function()
        g.draw_codewords(words)
        g.apply_mask(mask)
        g.draw_format(mask)
        score = g.penalty()
        if best_score is None or score < best_score:
            best, best_score = g, score
    return ["".join("1" if v else "0" for v in row) for row in best.dark]


def terminal(rows: List[str]) -> str:
    """終端機畫法：上下兩格合成一個字元（▀ ▄ █），四周留 2 格白邊。畫的是「白」的格子（Windows 終端機多半是
    黑底淺色字，這樣看起來才是白底黑格）。"""
    pad = 2
    n = len(rows)
    grid = [[True] * (n + 2 * pad) for _ in range(pad)] + \
           [[True] * pad + [c == "0" for c in r] + [True] * pad for r in rows] + \
           [[True] * (n + 2 * pad) for _ in range(pad)] + [[False] * (n + 2 * pad)]
    out = []
    for y in range(0, len(grid) - 1, 2):
        line = []
        for x in range(len(grid[0])):
            top, bottom = grid[y][x], grid[y + 1][x]
            line.append("█" if top and bottom else "▀" if top else "▄" if bottom else " ")
        out.append("".join(line))
    return "\n".join(out)
