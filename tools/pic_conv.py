#!/usr/bin/env python3
"""pic_conv.py - convert the title picture between ZX/BMP and UKNC form.

The title screen is an editable 256x192 24-bit BMP (src/res/pics/
title.bmp).  At build time it is encoded into the three UKNC video
planes with a separate 8-colour palette for every 8-line cell row
(24 rows), which the PPU programs into the video line table
(per-row palette tags, see ppu.mac NEW_TABLE / COMMAND_2):

  plane 0    192 lines x 32 bytes, bit 0 = leftmost pixel
             (blitted into PPU plane-0 VRAM by PPU COMMAND_3)
  planes 1+2 192 lines x 32 words, low byte = plane 1, high = plane 2
             (back-buffer layout, blitted by the CPU BLIT_FULL)
  palettes   24 rows x 2 words: nibble c of the pair = colour of
             pixel value c, nibble = Y*8 + R*4 + G*2 + B
             (Y: 0 = dim 0x80, 1 = bright 0xFF component levels)

Pixel value = plane2*4 + plane1*2 + plane0; value 0 is always black
(the border around the picture shows palette colour 0).  Rows with
more than 8 distinct colours lose the rarest ones to their nearest
kept neighbour.

Usage:
    pic_conv.py decode INPUT.scr OUTPUT.bmp [--force]
        one-time extraction: 6912-byte ZX SCREEN$ -> editable BMP
    pic_conv.py encode INPUT.bmp --p0 P0.bin --p12 P12.bin --pal PAL.mac [--force]
        BMP -> plane blobs + MACRO-11 palette table (label TITLE_PALS)
    pic_conv.py preview P0.bin P12.bin PAL.mac OUTPUT.png [--force]
        render the encoded data back to an image (visual check)
"""
import argparse
import sys
from pathlib import Path

from PIL import Image

W, H = 256, 192
ROWS = H // 8

# ZX attribute palette (dim 215 / bright 255)
ZX_DIM = [(0, 0, 0), (0, 0, 215), (215, 0, 0), (215, 0, 215),
          (0, 215, 0), (0, 215, 215), (215, 215, 0), (215, 215, 215)]
ZX_BRIGHT = [(0, 0, 0), (0, 0, 255), (255, 0, 0), (255, 0, 255),
             (0, 255, 0), (0, 255, 255), (255, 255, 0), (255, 255, 255)]


def nibble_rgb(n):
    """UKNC YRGB nibble -> RGB (standard palette, full brightness group)."""
    lvl = 255 if n & 8 else 128
    return (lvl if n & 4 else 0, lvl if n & 2 else 0, lvl if n & 1 else 0)


def rgb_nibble(rgb):
    """RGB -> UKNC YRGB nibble.  Exact ZX colours map dim->dim,
    bright->bright; anything else goes to the nearest of the 16."""
    r, g, b = rgb
    if rgb in ZX_DIM:
        return zx_to_nibble(ZX_DIM.index(rgb), 0)
    if rgb in ZX_BRIGHT:
        return zx_to_nibble(ZX_BRIGHT.index(rgb), 8)
    best, bd = 0, 1 << 30
    for n in range(16):
        nr, ng, nb = nibble_rgb(n)
        d = (r - nr) ** 2 + (g - ng) ** 2 + (b - nb) ** 2
        if d < bd:
            best, bd = n, d
    return best


def zx_to_nibble(i, y):
    """ZX colour index (GRB bit order: 1=B,2=R,4=G) -> YRGB nibble."""
    b, r, g = i & 1, (i >> 1) & 1, (i >> 2) & 1
    n = y + r * 4 + g * 2 + b
    return n if n else 0            # black stays black regardless of Y


def decode_scr(data):
    if len(data) < 6912:
        sys.exit(f"error: SCREEN$ too short ({len(data)} bytes)")
    im = Image.new("RGB", (W, H))
    px = im.load()
    for y in range(H):
        third, line = y >> 6, y & 63
        base = third * 2048 + (line & 7) * 256 + (line >> 3) * 32
        for xc in range(32):
            bits = data[base + xc]
            attr = data[6144 + (y >> 3) * 32 + xc]
            pal = ZX_BRIGHT if attr & 0x40 else ZX_DIM
            ink, paper = pal[attr & 7], pal[(attr >> 3) & 7]
            for i in range(8):
                px[xc * 8 + i, y] = ink if bits & (0x80 >> i) else paper
    return im


def encode(im):
    if im.size != (W, H):
        sys.exit(f"error: picture must be {W}x{H}, got {im.size[0]}x{im.size[1]}")
    im = im.convert("RGB")
    px = im.load()
    p0 = bytearray(H * 32)
    p12 = bytearray(H * 64)
    palettes = []
    for row in range(ROWS):
        # choose up to 8 colours for this row, black fixed at value 0
        hist = {}
        for y in range(row * 8, row * 8 + 8):
            for x in range(W):
                n = rgb_nibble(px[x, y])
                hist[n] = hist.get(n, 0) + 1
        cols = sorted((c for c in hist if c), key=lambda c: -hist[c])
        kept = [0] + cols[:7]
        remap = {}
        for c in cols[7:]:
            cr = nibble_rgb(c)
            remap[c] = min(kept, key=lambda k: sum(
                (a - b) ** 2 for a, b in zip(cr, nibble_rgb(k))))
        value = {c: i for i, c in enumerate(kept)}
        for c, k in remap.items():
            value[c] = value[k]
        pal = kept + [0] * (8 - len(kept))
        palettes.append(pal)
        for y in range(row * 8, row * 8 + 8):
            for x in range(W):
                v = value[rgb_nibble(px[x, y])]
                bit = 1 << (x & 7)
                if v & 1:
                    p0[y * 32 + (x >> 3)] |= bit
                if v & 2:
                    p12[y * 64 + (x >> 3) * 2] |= bit
                if v & 4:
                    p12[y * 64 + (x >> 3) * 2 + 1] |= bit
    return bytes(p0), bytes(p12), palettes


def pal_words(pal):
    w1 = sum(pal[i] << (i * 4) for i in range(4))
    w2 = sum(pal[i + 4] << (i * 4) for i in range(4))
    return w1, w2


def pal_mac(palettes):
    out = ["; generated by tools/pic_conv.py - do not edit",
           "; per-cell-row title palettes: 24 x 2 words (colours 0-3, 4-7)",
           "TITLE_PALS:"]
    for row, pal in enumerate(palettes):
        w1, w2 = pal_words(pal)
        out.append(f"\t.WORD\t{w1:06o},{w2:06o}\t; row {row}")
    out.append("")
    return "\n".join(out)


def preview(p0, p12, palettes):
    im = Image.new("RGB", (W, H))
    px = im.load()
    for y in range(H):
        pal = palettes[y >> 3]
        for x in range(W):
            bit = 1 << (x & 7)
            v = ((1 if p0[y * 32 + (x >> 3)] & bit else 0)
                 + (2 if p12[y * 64 + (x >> 3) * 2] & bit else 0)
                 + (4 if p12[y * 64 + (x >> 3) * 2 + 1] & bit else 0))
            px[x, y] = nibble_rgb(pal[v])
    return im


def parse_pal_mac(text):
    palettes = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith(".WORD"):
            continue
        w1, w2 = (int(v, 8) for v in line.split()[1].split(";")[0].split(","))
        palettes.append([(w1 >> (i * 4)) & 15 for i in range(4)]
                        + [(w2 >> (i * 4)) & 15 for i in range(4)])
    return palettes


def out_path(p, force):
    if p.exists() and not force:
        sys.exit(f"error: {p} exists (use --force)")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decode")
    d.add_argument("input", type=Path)
    d.add_argument("output", type=Path)
    d.add_argument("--force", action="store_true")
    e = sub.add_parser("encode")
    e.add_argument("input", type=Path)
    e.add_argument("--p0", type=Path, required=True)
    e.add_argument("--p12", type=Path, required=True)
    e.add_argument("--pal", type=Path, required=True)
    e.add_argument("--force", action="store_true")
    p = sub.add_parser("preview")
    p.add_argument("p0", type=Path)
    p.add_argument("p12", type=Path)
    p.add_argument("pal", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "decode":
        im = decode_scr(args.input.read_bytes())
        im.save(out_path(args.output, args.force))
        print(f"{args.output}: {W}x{H}")
    elif args.cmd == "encode":
        p0, p12, palettes = encode(Image.open(args.input))
        out_path(args.p0, args.force).write_bytes(p0)
        out_path(args.p12, args.force).write_bytes(p12)
        out_path(args.pal, args.force).write_text(pal_mac(palettes))
        print(f"{args.p0}: {len(p0)} bytes, {args.p12}: {len(p12)} bytes, "
              f"{ROWS} row palettes")
    elif args.cmd == "preview":
        palettes = parse_pal_mac(args.pal.read_text())
        im = preview(args.p0.read_bytes(), args.p12.read_bytes(), palettes)
        im.save(out_path(args.output, args.force))
        print(f"{args.output}: {W}x{H}")


if __name__ == "__main__":
    main()
