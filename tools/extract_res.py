#!/usr/bin/env python3
"""One-time extractor: orig/game48k.bin -> editable resources in src/res/.

Produces (all plain text, the editable source of truth for the port):
  src/res/tiles/tiles.txt      256 background tiles: bitmap + colour class
  src/res/chambers/chNN.txt    20 chambers: header fields, map grid, patches
  src/res/sprites/cells.txt    256 sprite cells (glyph+mask combined)
  src/res/sprites/entities.txt frames (info blocks) + state tables
  src/res/hud/logo.txt         big logo cell sheet (ZX 5B00 region)
  src/res/hud/fist.txt         24-cell graphic (ZX 9200 region)
  src/res/text/strings.txt     game strings (label|text)

Formats are documented in .claude/docs/resources.md.

Usage: python3 tools/extract_res.py [orig/game48k.bin]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = 0x4000

ZX_COLORS = ["BLACK", "BLUE", "RED", "MAGENTA", "GREEN", "CYAN", "YELLOW", "WHITE"]
# ZX ink -> UKNC plane combo class: 1 = "warm" (plane1), 2 = "cool" (plane2),
# 3 = white (planes 1+2).  Black ink handled per-tile (invert vs paper).
# Note: src/res/tiles/tiles.txt was hand-retouched after extraction -
# the collectible lamps (tiles 0x10-0x16, yellow ink) are combo=1 so
# CH_ROWPALS can show them yellow; a re-extraction would lose that.
INK_COMBO = {0: 0, 1: 2, 2: 1, 3: 1, 4: 2, 5: 2, 6: 3, 7: 3}


def rb(mem, a):
    return mem[a - BASE]


def rw(mem, a):
    return mem[a - BASE] | (mem[a - BASE + 1] << 8)


# ---------------------------------------------------------------- tiles

def extract_tiles(mem, out):
    """Tiles 0x9800 + attr table 0x6300 -> tiles.txt."""
    lines = [
        "# Background tiles (8x8).  '#' = ink pixel, '.' = background.",
        "# combo: UKNC plane combo the ink maps to (1 warm/red, 2 cool/green,",
        "# 3 white); attr is the original ZX attribute for reference.",
        "# Tile classes by code (collision): >=40 solid, 18-1F climbable,",
        "# 20-3F scenery, 17 exit, 10-16 collectible, <10 background.",
        "",
    ]
    for code in range(256):
        attr = rb(mem, 0x6300 + code)
        ink, paper, bright = attr & 7, (attr >> 3) & 7, (attr >> 6) & 1
        glyph = [rb(mem, 0x9800 + code * 8 + i) for i in range(8)]
        inverted = False
        if ink == 0 and paper != 0:
            # black-on-colour tile: store inverted, ink = paper colour
            glyph = [g ^ 0xFF for g in glyph]
            ink = paper
            inverted = True
        combo = INK_COMBO[ink]
        if all(g == 0 for g in glyph):
            combo = combo or 1
        flags = f" attr={attr:02x}" + (" inverted" if inverted else "")
        lines.append(
            f"tile {code:02x} combo={combo} ink={ZX_COLORS[ink]}"
            f"{' bright' if bright else ''}{flags}"
        )
        for g in glyph:
            lines.append("".join("#" if (g >> (7 - b)) & 1 else "." for b in range(8)))
        lines.append("")
    out.write_text("\n".join(lines))
    print(f"tiles.txt: 256 tiles -> {out}")


# ---------------------------------------------------------------- chambers

def decode_patch_list(mem, ptr):
    """Patch list: guard bytes (bit7, & player mask) + 3-byte entries
    {col, row, value}; 0xFF ends."""
    entries = []
    a = ptr
    while True:
        b = rb(mem, a)
        if b == 0xFF:
            break
        if b & 0x80:
            entries.append(("guard", b))
            a += 1
        else:
            col, row, val = rb(mem, a), rb(mem, a + 1), rb(mem, a + 2)
            entries.append(("set", col, row, val))
            a += 3
    return entries, a + 1


def extract_chambers(mem, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    for n in range(20):
        ptr = rw(mem, 0x6400 + n * 2)
        h = [rb(mem, ptr + i) for i in range(0x40)]
        # RLE map
        a = ptr + 0x40
        cells = bytearray()
        while True:
            c = rb(mem, a)
            a += 1
            if c == 0:
                break
            if c & 0x80:
                for _ in range(c & 0x7F):
                    cells.append(rb(mem, a))
                    a += 1
            else:
                cells += bytes([rb(mem, a)]) * c
                a += 1
        assert len(cells) == 32 * 22, (n, len(cells))
        patch_ptr = h[6] | (h[7] << 8)
        patches, _ = decode_patch_list(mem, patch_ptr)

        L = [f"# Chamber {n}", ""]
        L.append(f"spawn_a   {h[8]} {h[9]} {h[0x0A]:02x}   # col row flags(bit0 facing, bit7 enemies blocked)")
        L.append(f"spawn_b   {h[0x2D]} {h[0x2E]} {h[0x2F]:02x}")
        L.append(f"border    {h[0x0B]}")
        L.append(f"col_thr   {h[0x0E]} {h[0x0F]}")
        L.append(f"row_thr   {h[0x10]} {h[0x11]}")
        for e in range(9):
            ch2, col, row = h[0x12 + e * 3 : 0x15 + e * 3]
            if ch2 == 255:
                L.append(f"exit {e}    death")
            else:
                L.append(f"exit {e}    {ch2} {col} {row}")
        for i, off in enumerate((0x30, 0x34, 0x38)):
            if any(h[off : off + 4]):
                L.append(
                    f"anim {i}    {h[off]} {h[off+1]} {h[off+2]} {h[off+3]}"
                    "   # row col_start col_end delay"
                )
        # header bytes 0x3C..0x3F sometimes hold a 4th anim (chamber 17)
        if any(h[0x3C:0x40]):
            L.append(f"anim 3    {h[0x3C]} {h[0x3D]} {h[0x3E]} {h[0x3F]}")
        L.append("")
        L.append("map")
        for row in range(22):
            L.append(" ".join(f"{cells[row*32+c]:02x}" for c in range(32)))
        L.append("")
        L.append("patches")
        for p in patches:
            if p[0] == "guard":
                L.append(f" guard {p[1]:02x}")
            else:
                L.append(f" set {p[1]} {p[2]} {p[3]:02x}")
        L.append("")
        (outdir / f"ch{n:02d}.txt").write_text("\n".join(L))
    print(f"chambers -> {outdir}/ch00..19.txt")


# ---------------------------------------------------------------- sprites

def extract_cells(mem, out, gbase=0xA000, mbase=0xB000, which="right-facing"):
    """Sprite cells (glyphs + masks) -> cells text file.
    '.' transparent (mask 1), '#' ink (glyph 1), 'o' opaque black."""
    lines = [
        f"# Sprite cells (8x8), {which} sheet: '.' transparent, '#' ink,",
        "# 'o' opaque black.  Both sheets share cell codes; the facing",
        "# bit of an entity selects the sheet.",
        "",
    ]
    for code in range(256):
        g = [rb(mem, gbase + code * 8 + i) for i in range(8)]
        m = [rb(mem, mbase + code * 8 + i) for i in range(8)]
        lines.append(f"cell {code:02x}")
        for gi, mi in zip(g, m):
            row = ""
            for b in range(8):
                bit = 7 - b
                gb, mb = (gi >> bit) & 1, (mi >> bit) & 1
                row += "#" if gb else ("." if mb else "o")
            lines.append(row)
        lines.append("")
    out.write_text("\n".join(lines))
    print(f"cells.txt -> {out}")


HANDLER_NAMES = {
    0xCD9B: "H_STAND", 0xCE48: "H_WALK", 0xCF04: "H_STEP", 0xCF18: "H_PUNCH",
    0xCF2D: "H_PUNCH2", 0xCF59: "H_DUCK", 0xCFB3: "H_DUCKWALK", 0xCFBD: "H_LIEDOWN",
    0xCFCE: "H_JUMPUP", 0xCFF8: "H_JUMPFWD", 0xD023: "H_JUMPFWD2", 0xD032: "H_HANG",
    0xD03F: "H_FALL", 0xD063: "H_CLIMB", 0xD10D: "H_CLIMB2", 0xCB8A: "H_NOP",
    0xD112: "H_FALLING", 0xD15D: "H_KNOCKDOWN", 0xD16F: "H_STAGGER",
    0xD198: "H_STAGGER2", 0xD1A2: "H_THROWN", 0xD1D2: "H_KICK",
}

ENTITIES = {"ninja": 0xCB1C, "yamo": 0xCBBE, "bruce": 0xCCA5}
MAXSTATE = {"ninja": 0x15, "yamo": 0x16, "bruce": 0x16}


def extract_entities(mem, out):
    lines = [
        "# Entity animation frames (info blocks) and state tables.",
        "# frame NAME w= h= : cell codes (see cells.txt), row-major.",
        "# state NN frame=NAME handler=H_XXX",
        "",
    ]
    frames = {}  # addr -> name
    order = []
    for name, e in ENTITIES.items():
        for s in range(1, MAXSTATE[name] + 1):
            info = rw(mem, e + 0x16 + (s - 1) * 4)
            if info not in frames:
                fname = f"f_{info:04x}"
                frames[info] = fname
                order.append(info)
    for info in sorted(order):
        w, h = rb(mem, info), rb(mem, info + 1)
        assert 1 <= w <= 5 and 1 <= h <= 5, (hex(info), w, h)
        lines.append(f"frame {frames[info]} w={w} h={h}")
        for r in range(h):
            lines.append(
                " " + " ".join(f"{rb(mem, info+2+r*w+c):02x}" for c in range(w))
            )
        lines.append("")
    for name, e in ENTITIES.items():
        lines.append(f"entity {name} tick={rb(mem, e+1)} color={rb(mem, e+5)}")
        for s in range(1, MAXSTATE[name] + 1):
            info = rw(mem, e + 0x16 + (s - 1) * 4)
            hdl = rw(mem, e + 0x18 + (s - 1) * 4)
            hname = HANDLER_NAMES.get(hdl, f"H_{hdl:04X}")
            lines.append(f" state {s:02x} frame={frames[info]} handler={hname}")
        lines.append("")
    out.write_text("\n".join(lines))
    print(f"entities.txt -> {out}")


# ---------------------------------------------------------------- hud art

def extract_sheet(mem, addr, count, out, note):
    lines = [f"# {note}", f"# {count} cells of 8x8 from ZX {addr:#06x}", ""]
    for i in range(count):
        g = [rb(mem, addr + i * 8 + r) for r in range(8)]
        lines.append(f"cell {i:02x}")
        for gi in g:
            lines.append("".join("#" if (gi >> (7 - b)) & 1 else "." for b in range(8)))
        lines.append("")
    out.write_text("\n".join(lines))
    print(f"{out.name}: {count} cells -> {out}")


# ---------------------------------------------------------------- strings

STRINGS = [
    # label, addr, length  (from the menu / game-over / pause code)
    ("gameover1", 0xFC17, 0x12),
    ("gameover2", 0xFC29, 0x36),
    ("gameover3", 0xFC5F, 0x10),
    ("gameover4", 0xFC6F, 0x1E),
    ("gameover5", 0xFC8D, 0x1E),
    ("gameover6", 0xFCAB, 0x32),
    ("timesup", 0xFCDD, 0x20),
    ("menu1", 0xFB12, 0x1A),
    ("menu2", 0xFB2C, 0x19),
    ("menu3", 0xFB45, 0x3C),
    ("menu4", 0xFB81, 0x13),
    ("menu5", 0xFB94, 0x80),
    ("menu6", 0xFC14, 0x03),
    ("pause", 0x92C0, 0x20),
    ("hudtext", 0xFEB2, 0x40),
    ("b50", 0xC96B, 6),
    ("b75", 0xC971, 6),
    ("b100", 0xC977, 6),
    ("b125", 0xC97D, 6),
    ("b200", 0xC983, 6),
    ("b450", 0xC989, 6),
    ("b2000", 0xC98F, 6),
    ("b3000", 0xC995, 6),
]


def extract_strings(mem, out):
    # menu / status strings are built at run time; take them from the
    # live-game dump when available
    live_path = ROOT / "tmp/re/live48k.bin"
    live = live_path.read_bytes() if live_path.exists() else mem
    lines = [
        "# Game strings.  label|text ; ZX charset was ASCII 20..5F.",
        "",
    ]
    for label, addr, ln in STRINGS:
        src = live if rb(mem, addr) == 0 else mem
        txt = "".join(chr(src[addr - BASE + i]) for i in range(ln))
        txt = "".join(c if 0x20 <= ord(c) < 0x80 else "?" for c in txt)
        lines.append(f"{label}|{txt}")
    out.write_text("\n".join(lines) + "\n")
    print(f"strings.txt -> {out}")


def main():
    img = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "orig/game48k.bin")
    mem = Path(img).read_bytes()
    res = ROOT / "src/res"
    (res / "tiles").mkdir(parents=True, exist_ok=True)
    (res / "sprites").mkdir(parents=True, exist_ok=True)
    (res / "hud").mkdir(parents=True, exist_ok=True)
    (res / "text").mkdir(parents=True, exist_ok=True)
    extract_tiles(mem, res / "tiles/tiles.txt")
    extract_chambers(mem, res / "chambers")
    extract_cells(mem, res / "sprites/cells.txt")
    extract_cells(mem, res / "sprites/cells_l.txt", 0xA800, 0xB800, "left-facing")
    extract_entities(mem, res / "sprites/entities.txt")
    extract_sheet(mem, 0x5B00, 64, res / "hud/logo.txt", "logo / HUD cell sheet")
    extract_sheet(mem, 0x9200, 24, res / "hud/fist.txt", "fist (lives) graphic")
    extract_strings(mem, res / "text/strings.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
