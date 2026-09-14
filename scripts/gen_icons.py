"""One-off: generate simple flat-color PWA icons (no external deps).

Produces a green square with a white ring + green dot (a plain
"stopwatch/target" mark) at the given sizes, written as real PNG files
using only the stdlib (struct + zlib).
"""
import struct
import zlib
import sys
import os

BG = (0x1a, 0xb2, 0x59)  # brand green, a shade deeper than the widget's #25d366
RING = (255, 255, 255)
DOT = (0x17, 0x20, 0x33)  # matches the widget's dark badge colour


def make_png(size, path):
    cx = cy = size / 2.0
    outer_r = size * 0.34
    ring_w = size * 0.075
    dot_r = size * 0.10
    stem_w = size * 0.06

    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            px, py = x + 0.5, y + 0.5
            d = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
            # little stopwatch "button" nub at the top
            nub = (abs(px - cx) < stem_w / 2) and (cy - outer_r - size * 0.09 < py < cy - outer_r + size * 0.02)
            if nub:
                r, g, b = RING
            elif outer_r - ring_w <= d <= outer_r:
                r, g, b = RING
            elif d <= dot_r:
                r, g, b = DOT
            else:
                r, g, b = BG
            row += bytes((r, g, b))
        rows.append(bytes(row))

    raw = bytearray()
    for row in rows:
        raw += b"\x00" + row  # filter type 0 per scanline

    def chunk(tag, data):
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    idat = zlib.compress(bytes(raw), 9)
    png = sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(png)
    print("wrote", path, size, "x", size, len(png), "bytes")


if __name__ == "__main__":
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    make_png(192, os.path.join(out_dir, "mm-icon-192.png"))
    make_png(512, os.path.join(out_dir, "mm-icon-512.png"))
