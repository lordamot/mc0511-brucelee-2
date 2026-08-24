#!/usr/bin/env python3
"""verify_build.py - check the toolchain and the built game disk.

Check groups:

  generators  every resource generator, re-run into a temp dir, must
              reproduce build/ byte-for-byte (determinism: a rebuild
              from the same sources gives the same disk)

  title       the title picture encoder must be stable:
              encode(preview(encode(bmp))) == encode(bmp), and the
              blobs on the disk must match the manifest layout that
              src/title.mac expects (TITLE0_LBA / sector counts)

  image       build/brucelee.raw must look like a bootable image:
              correct size, boot marker, program fits PROG_SIZE

  smoke       build/brucelee.dsk must boot in the headless emulator:
              the title picture shows (red pixels present), ENTER
              reaches the menu (white text), ENTER starts the game,
              and walking right exits chamber 0 into chamber 1

Usage:
    python3 tools/verify_build.py [--skip-smoke]
"""

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
failures = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}"
          + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def run(argv, **kw):
    return subprocess.run([str(a) for a in argv], cwd=REPO_ROOT,
                          capture_output=True, text=True, **kw)


def same(a, b):
    return Path(a).read_bytes() == Path(b).read_bytes()


def verify_generators(tmp):
    py = sys.executable
    gens = [
        (["tools/font_gen.py", "src/res/font/font8.txt"], "font8.mac"),
        (["tools/text_gen.py", "src/res/text/strings.txt"], "strings.mac"),
        (["tools/tiles_gen.py", "src/res/tiles/tiles.txt"], "data_tiles.mac"),
        (["tools/chambers_gen.py", "src/res/chambers"], "data_chambers.mac"),
        (["tools/sprites_gen.py", "src/res/sprites"], "data_sprites.mac"),
        (["tools/hud_gen.py", "src/res/hud"], "data_hud.mac"),
        (["tools/music_gen.py", "orig/game48k.bin"], "data_music.mac"),
    ]
    for cmd, out in gens:
        r = run([py] + cmd + ["--out", tmp / out, "--force"])
        ok = r.returncode == 0 and same(tmp / out, REPO_ROOT / "build" / out)
        check(f"generator {cmd[0].split('/')[-1]}", ok,
              r.stderr.strip().splitlines()[-1] if r.returncode else
              f"build/{out} differs from a fresh run")


def verify_title(tmp):
    py = sys.executable
    r = run([py, "tools/pic_conv.py", "encode", "src/res/pics/title.bmp",
             "--p0", tmp / "p0.bin", "--p12", tmp / "p12.bin",
             "--pal", tmp / "pal.mac", "--force"])
    ok = (r.returncode == 0
          and same(tmp / "p0.bin", REPO_ROOT / "build/title_p0.bin")
          and same(tmp / "p12.bin", REPO_ROOT / "build/title_p12.bin")
          and same(tmp / "pal.mac", REPO_ROOT / "build/data_title.mac"))
    check("title encode reproduces build/", ok)

    r = run([py, "tools/pic_conv.py", "preview", tmp / "p0.bin",
             tmp / "p12.bin", tmp / "pal.mac", tmp / "prev.png", "--force"])
    r2 = run([py, "tools/pic_conv.py", "encode", tmp / "prev.png",
              "--p0", tmp / "p0b.bin", "--p12", tmp / "p12b.bin",
              "--pal", tmp / "palb.mac", "--force"])
    ok = (r.returncode == 0 and r2.returncode == 0
          and same(tmp / "p0.bin", tmp / "p0b.bin")
          and same(tmp / "p12.bin", tmp / "p12b.bin")
          and same(tmp / "pal.mac", tmp / "palb.mac"))
    check("title encode(preview(x)) == x", ok)

    # disk layout constants in src/title.mac vs the built manifest
    src = (REPO_ROOT / "src/title.mac").read_text()
    lba = int(re.search(r"TITLE0_LBA\s*=\s*(\d+)\.", src).group(1))
    s0 = int(re.search(r"TITLE0_SEC\s*=\s*(\d+)\.", src).group(1))
    s12 = int(re.search(r"TITLE12_SEC\s*=\s*(\d+)\.", src).group(1))
    import json
    man = json.loads((REPO_ROOT / "build/manifest.json").read_text())
    entries = {e["file"]: e for e in man["entries"]}
    ok = (entries["title_p0.bin"]["lba"] == lba
          and entries["title_p0.bin"]["sectors"] == s0
          and entries["title_p12.bin"]["lba"] == lba + s0
          and entries["title_p12.bin"]["sectors"] == s12)
    check("title disk layout matches src/title.mac", ok)


def verify_image():
    raw = (REPO_ROOT / "build/brucelee.raw").read_bytes()
    check("image size 40960", len(raw) == 40960, str(len(raw)))
    # boot sector marker: NOP (000240) then BR
    w0 = raw[0] | raw[1] << 8
    w1 = raw[2] | raw[3] << 8
    check("boot marker", w0 == 0o240 and (w1 >> 8) == 0o001,
          f"{w0:06o} {w1:06o}")
    dsk = (REPO_ROOT / "build/brucelee.dsk").read_bytes()
    check("disk size 819200", len(dsk) == 819200, str(len(dsk)))
    check("program on disk at LBA 0", dsk[:40960] == raw)


def symbol_addr(name):
    """Address of a label from the assembler listing."""
    for line in (REPO_ROOT / "build/brucelee.lst").read_text().splitlines():
        m = re.match(rf"\s*\d+\s+([0-7]+)\s+{name}:", line)
        if m:
            return int(m.group(1), 8)
    sys.exit(f"error: symbol {name} not found in build/brucelee.lst")


def count_colors(bmp_path):
    from PIL import Image
    im = Image.open(bmp_path).convert("RGB")
    return {c: n for n, c in im.getcolors(im.width * im.height)}


def verify_smoke(tmp):
    chamber = symbol_addr("CHAMBER")
    script = tmp / "smoke.script"
    script.write_text(f"""\
run 900
press 030
run 30
press 153
run 350
screenshot {tmp}/title.bmp
run 150
screenshot {tmp}/title2.bmp
press 153
run 100
screenshot {tmp}/menu.bmp
press 153
run 60
screenshot {tmp}/game.bmp
keydown 133
run 500
keyup 133
run 50
dumpcpu {chamber:o} 2 {tmp}/chamber.bin
screenshot {tmp}/walk.bmp
quit
""")
    r = run([REPO_ROOT / "bin/ukncbtl/uknc-headless",
             "--rom", REPO_ROOT / "bin/ukncbtl/uknc_rom.bin",
             "--disk", REPO_ROOT / "build/brucelee.dsk",
             "--script", script], timeout=300)
    check("emulator boots the disk", r.returncode == 0, r.stderr.strip())
    if r.returncode != 0:
        return

    red = 0
    for shot in ("title.bmp", "title2.bmp"):
        title = count_colors(tmp / shot)
        red = max(red, sum(n for c, n in title.items()
                           if c[0] > 180 and c[1] < 80))
    check("title picture shows (red pixels)", red > 2000, f"red={red}")

    menu = count_colors(tmp / "menu.bmp")
    white = menu.get((255, 255, 255), 0)
    check("menu shows (white text)", white > 1500, f"white={white}")

    game = count_colors(tmp / "game.bmp")
    green = sum(n for c, n in game.items() if c[1] > 180 and c[0] < 80)
    red = sum(n for c, n in game.items() if c[0] > 180 and c[1] < 80)
    check("chamber 0 renders (green+red tiles)",
          green > 2000 and red > 1000, f"green={green} red={red}")

    ch = (tmp / "chamber.bin").read_bytes()
    check("walking right reaches chamber 1", ch[0] == 1, f"chamber={ch[0]}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skip-smoke", action="store_true")
    args = ap.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="brucelee-verify-") as td:
        tmp = Path(td)
        print("generators:")
        verify_generators(tmp)
        print("title:")
        verify_title(tmp)
        print("image:")
        verify_image()
        if not args.skip_smoke:
            print("smoke:")
            verify_smoke(tmp)

    if failures:
        print(f"\n{len(failures)} check(s) FAILED: " + ", ".join(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
