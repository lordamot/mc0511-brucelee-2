#!/usr/bin/env python3
"""Extract the 20 chamber definitions from the unpacked Bruce Lee image.

Chamber pointer table: 0x6400, one word per chamber (20 entries).
Each chamber blob:
  +0x00  64-byte header:
         +0  word  tile glyph base (code*8 indexes 8-byte glyphs)
         +3  byte  attribute table page (attr = mem[page*256 + code])
         +6  word  patch/object list pointer
         +8  ...   per-chamber parameters (decoded incrementally)
         +0x0B     border colour
  +0x40  RLE map -> 704 cells (32 cols x 22 rows, screen rows 2..23):
         n=0 end; n bit7 clear: repeat next byte n times;
         n bit7 set: copy n&0x7f literal bytes.
  patch list (from header +6): 3-byte entries VALUE, POSLO, POSHI-ish
         guarded by player masks; terminated by 0xFF (see loader 0xC1BD).

Usage:
  python3 tools/chamber_extract.py IMAGE.bin png OUTDIR      all chambers -> PNG
  python3 tools/chamber_extract.py IMAGE.bin json OUT.json   maps+headers -> JSON
  python3 tools/chamber_extract.py IMAGE.bin tiles N OUT.png tile set of chamber N
"""
import json
import sys
from pathlib import Path
from PIL import Image

BASE = 0x4000
TABLE = 0x6400
NCHAMBERS = 20
COLS, ROWS = 32, 22

PALETTE = [
    (0, 0, 0), (0, 0, 215), (215, 0, 0), (215, 0, 215),
    (0, 215, 0), (0, 215, 215), (215, 215, 0), (215, 215, 215),
]
BRIGHT = [
    (0, 0, 0), (0, 0, 255), (255, 0, 0), (255, 0, 255),
    (0, 255, 0), (0, 255, 255), (255, 255, 0), (255, 255, 255),
]


class Chamber:
    def __init__(self, mem, n):
        self.n = n
        ptr = mem[TABLE - BASE + n * 2] | (mem[TABLE - BASE + n * 2 + 1] << 8)
        self.ptr = ptr
        off = ptr - BASE
        self.header = bytes(mem[off : off + 0x40])
        self.tile_base = self.header[0] | (self.header[1] << 8)
        self.attr_page = self.header[3]
        self.patch_ptr = self.header[6] | (self.header[7] << 8)
        self.border = self.header[0x0B]
        # RLE map
        p = off + 0x40
        cells = bytearray()
        while True:
            c = mem[p]
            p += 1
            if c == 0:
                break
            if c & 0x80:
                n_lit = c & 0x7F
                cells += mem[p : p + n_lit]
                p += n_lit
            else:
                cells += bytes([mem[p]]) * c
                p += 1
        self.map = bytes(cells)
        self.end = p + BASE
        # patch list (player-1 view): entries until 0xFF; player-mask
        # guard entries have bit7 set (see 0xC1BD)
        self.patches = []
        q = self.patch_ptr - BASE
        while True:
            b = mem[q]
            if not (b & 0x80):
                # plain entry: pos-lo, pos-hi(with row bits), value
                lo, hi, val = mem[q], mem[q + 1], mem[q + 2]
                # decode like the loader: c = swap-nibble-ish rrc hi x3
                rhi = ((hi >> 3) | (hi << 5)) & 0xFF
                col = ((lo ^ rhi) & 0x1F ^ rhi) & 0xFF
                self.patches.append({"raw": [lo, hi, val]})
                q += 3
                continue
            if b == 0xFF:
                break
            self.patches.append({"guard": b})
            q += 1

    def cell(self, x, y):
        return self.map[y * COLS + x] if y * COLS + x < len(self.map) else 0

    def render(self, mem, zoom=2):
        img = Image.new("RGB", (COLS * 8, ROWS * 8))
        px = img.load()
        for cy in range(ROWS):
            for cx in range(COLS):
                code = self.cell(cx, cy)
                glyph_off = self.tile_base + code * 8 - BASE
                attr = mem[(self.attr_page << 8) + code - BASE]
                ink = attr & 7
                paper = (attr >> 3) & 7
                pal = BRIGHT if attr & 0x40 else PALETTE
                for ry in range(8):
                    row = mem[glyph_off + ry]
                    for rx in range(8):
                        on = (row >> (7 - rx)) & 1
                        px[cx * 8 + rx, cy * 8 + ry] = pal[ink] if on else pal[paper]
        return img.resize((img.width * zoom, img.height * zoom), Image.NEAREST)


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 1
    mem = Path(sys.argv[1]).read_bytes()
    cmd = sys.argv[2]
    if cmd == "png":
        outdir = Path(sys.argv[3])
        outdir.mkdir(parents=True, exist_ok=True)
        for n in range(NCHAMBERS):
            ch = Chamber(mem, n)
            ch.render(mem).save(outdir / f"chamber{n:02d}.png")
            print(
                f"ch{n:02d} @{ch.ptr:#06x} tiles={ch.tile_base:#06x}"
                f" attrs={ch.attr_page:#04x}00 border={ch.border}"
                f" map={len(ch.map)} cells end={ch.end:#06x}"
            )
    elif cmd == "json":
        data = []
        for n in range(NCHAMBERS):
            ch = Chamber(mem, n)
            data.append({
                "n": n, "ptr": ch.ptr, "tile_base": ch.tile_base,
                "attr_page": ch.attr_page, "border": ch.border,
                "header": list(ch.header), "map": list(ch.map),
                "patch_ptr": ch.patch_ptr,
            })
        Path(sys.argv[3]).write_text(json.dumps(data))
        print(f"wrote {sys.argv[3]}")
    elif cmd == "tiles":
        n = int(sys.argv[3])
        out = sys.argv[4]
        ch = Chamber(mem, n)
        used = sorted(set(ch.map))
        img = Image.new("RGB", (16 * 10, ((len(used) + 15) // 16) * 10), (40, 40, 60))
        for i, code in enumerate(used):
            cell = Image.new("RGB", (8, 8))
            px = cell.load()
            glyph_off = ch.tile_base + code * 8 - BASE
            attr = mem[(ch.attr_page << 8) + code - BASE]
            ink, paper = attr & 7, (attr >> 3) & 7
            pal = BRIGHT if attr & 0x40 else PALETTE
            for ry in range(8):
                row = mem[glyph_off + ry]
                for rx in range(8):
                    px[rx, ry] = pal[ink] if (row >> (7 - rx)) & 1 else pal[paper]
            img.paste(cell, ((i % 16) * 10 + 1, (i // 16) * 10 + 1))
        img = img.resize((img.width * 4, img.height * 4), Image.NEAREST)
        img.save(out)
        print(f"chamber {n}: {len(used)} distinct tiles -> {out}")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
