"""Candle chart as a PNG, standard library only (no matplotlib on this Mac).

  chart_png.render(bars, path, support=..., resistance=..., ma=...)

Dark background, green/red candles for the last N daily bars, the 50-day average in gold,
support as a green dashed line and resistance as a red dashed line. No text: the Telegram
caption carries the numbers.
"""
import struct
import zlib

W, H, PAD = 900, 480, 24
BG = (17, 20, 28)
GRID = (34, 39, 52)
UP = (38, 194, 129)
DOWN = (239, 83, 80)
MA = (241, 196, 15)
SUP = (38, 194, 129)
RES = (239, 83, 80)
LAST = (120, 160, 255)


class Canvas:
    def __init__(self, w, h, bg):
        self.w, self.h = w, h
        self.px = bytearray(bytes(bg) * (w * h))

    def dot(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = 3 * (y * self.w + x)
            self.px[i:i + 3] = bytes(c)

    def rect(self, x0, y0, x1, y1, c):
        for y in range(max(0, min(y0, y1)), min(self.h, max(y0, y1) + 1)):
            for x in range(max(0, min(x0, x1)), min(self.w, max(x0, x1) + 1)):
                self.dot(x, y, c)

    def line(self, x0, y0, x1, y1, c, width=1, dash=0):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err, n = dx + dy, 0
        while True:
            if not dash or (n // dash) % 2 == 0:
                for k in range(width):
                    self.dot(x0, y0 + k, c)
            if x0 == x1 and y0 == y1:
                break
            e2, n = 2 * err, n + 1
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def png(self):
        raw = b"".join(b"\x00" + bytes(self.px[3 * y * self.w:3 * (y + 1) * self.w]) for y in range(self.h))

        def chunk(tag, data):
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def render(bars, path, support=None, resistance=None, ma=None, n=60):
    """bars: [{o,h,l,c}] oldest first; ma: list aligned with bars (or None)."""
    b = bars[-n:]
    m = (ma or [None] * len(bars))[-n:]
    lv = [x for x in (support, resistance) if x]
    lo = min([x["l"] for x in b] + lv + [v for v in m if v])
    hi = max([x["h"] for x in b] + lv + [v for v in m if v])
    span = (hi - lo) or 1
    lo, hi = lo - 0.04 * span, hi + 0.04 * span

    def y(p):
        return int(PAD + (hi - p) / (hi - lo) * (H - 2 * PAD))

    cv = Canvas(W, H, BG)
    for k in range(1, 5):
        gy = PAD + k * (H - 2 * PAD) // 5
        cv.line(PAD, gy, W - PAD, gy, GRID)
    step = (W - 2 * PAD) / len(b)
    half = max(1, int(step * 0.32))
    if support:
        cv.line(PAD, y(support), W - PAD, y(support), SUP, width=2, dash=10)
    if resistance:
        cv.line(PAD, y(resistance), W - PAD, y(resistance), RES, width=2, dash=10)
    prev = None
    for i, v in enumerate(m):
        if v:
            pt = (int(PAD + (i + 0.5) * step), y(v))
            if prev:
                cv.line(prev[0], prev[1], pt[0], pt[1], MA, width=2)
            prev = pt
    for i, x in enumerate(b):
        cx = int(PAD + (i + 0.5) * step)
        col = UP if x["c"] >= x["o"] else DOWN
        cv.line(cx, y(x["h"]), cx, y(x["l"]), col)
        top, bot = y(max(x["o"], x["c"])), y(min(x["o"], x["c"]))
        cv.rect(cx - half, top, cx + half, max(bot, top + 1), col)
    ly = y(b[-1]["c"])
    cv.line(PAD, ly, W - PAD, ly, LAST, dash=4)
    with open(path, "wb") as f:
        f.write(cv.png())
    return path
