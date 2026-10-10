"""Minimal PNG decoder for tests: non-interlaced 1-bit or 8-bit gray, RGB and RGBA."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

_CHANNELS = {0: 1, 2: 3, 6: 4}


@dataclass
class Png:
    width: int
    height: int
    bit_depth: int
    color_type: int
    ppm: tuple[int, int] | None
    rows: list[bytes]

    @property
    def channels(self) -> int:
        return _CHANNELS[self.color_type]

    def pixel(self, x: int, y: int) -> tuple[int, ...]:
        row = self.rows[y]
        if self.bit_depth == 1:
            return ((row[x >> 3] >> (7 - (x & 7))) & 1,)
        c = self.channels
        return tuple(row[x * c : x * c + c])

    def gray_bytes(self) -> bytes:
        """1-bit pixels expanded to 0/255, for comparison with Pillow's "1" mode."""
        return bytes(255 * self.pixel(x, y)[0] for y in range(self.height) for x in range(self.width))


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def read_png(path: Path) -> Png:
    data = Path(path).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, ppm = 8, bytearray(), None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind, body = data[pos + 4 : pos + 8], data[pos + 8 : pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, color = struct.unpack(">IIBB", body[:10])
        elif kind == b"pHYs":
            ppm = struct.unpack(">II", body[:8])
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    channels = _CHANNELS[color]
    row_len = (width + 7) // 8 if depth == 1 else width * channels
    bpp = 1 if depth == 1 else channels
    raw, rows, prev = zlib.decompress(bytes(idat)), [], bytes(row_len)
    for y in range(height):
        start = y * (row_len + 1)
        kind, line = raw[start], bytearray(raw[start + 1 : start + 1 + row_len])
        for i in range(row_len):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            predictor = (0, a, b, (a + b) // 2, _paeth(a, b, c))[kind]
            line[i] = (line[i] + predictor) & 0xFF
        rows.append(bytes(line))
        prev = line
    return Png(width, height, depth, color, ppm, rows)
