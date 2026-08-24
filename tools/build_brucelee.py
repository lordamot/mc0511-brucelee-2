#!/usr/bin/env python3
"""Build the game: src/ -> build/brucelee.dsk (bootable raw image).

Steps: run the resource generators (font, strings, tiles, chambers,
sprites, hud, music), concatenate the MACRO-11 modules listed in
src/brucelee.list, assemble with bin/macro11 (-yus -ysl 64), link
flat with tools/obj2bin.py, and lay out the raw disk (program at
LBA 0).

Usage: build_brucelee.py [OUT.dsk] [--force]
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
PROG_SIZE = 0o120000        # must match PROG_SIZE in src/defs.mac
DISK_SIZE = 819200


def run(*cmd):
    r = subprocess.run([str(c) for c in cmd], cwd=ROOT,
                       capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        sys.exit(f"error: {' '.join(str(c) for c in cmd)} failed")
    return r


def main():
    out = ROOT / (sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-")
                  else "build/brucelee.dsk")
    BUILD.mkdir(exist_ok=True)
    py = sys.executable

    run(py, "tools/font_gen.py", "src/res/font/font8.txt",
        "--out", "build/font8.mac", "--force")
    run(py, "tools/text_gen.py", "src/res/text/strings.txt",
        "--out", "build/strings.mac", "--force")
    run(py, "tools/tiles_gen.py", "src/res/tiles/tiles.txt",
        "--out", "build/data_tiles.mac", "--force")
    run(py, "tools/chambers_gen.py", "src/res/chambers",
        "--out", "build/data_chambers.mac", "--force")
    run(py, "tools/sprites_gen.py", "src/res/sprites",
        "--out", "build/data_sprites.mac", "--force")
    run(py, "tools/hud_gen.py", "src/res/hud",
        "--out", "build/data_hud.mac", "--force")
    run(py, "tools/music_gen.py", "orig/game48k.bin",
        "--out", "build/data_music.mac", "--force")
    run(py, "tools/pic_conv.py", "encode", "src/res/pics/title.bmp",
        "--p0", "build/title_p0.bin", "--p12", "build/title_p12.bin",
        "--pal", "build/data_title.mac", "--force")

    # concatenate modules
    modules = []
    for line in (ROOT / "src/brucelee.list").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            modules.append(ROOT / line)
    src = "\n".join(m.read_text() for m in modules)
    (BUILD / "brucelee.mac").write_text(src)

    # assemble + link flat
    r = run(ROOT / "bin/macro11/macro11", "-yus", "-ysl", "64",
            "-o", "build/brucelee.obj", "-l", "build/brucelee.lst",
            "build/brucelee.mac")
    if "***ERROR" in r.stdout or "***ERROR" in r.stderr:
        sys.exit("error: assembler reported errors (see build/brucelee.lst)")
    run(py, "tools/obj2bin.py", "build/brucelee.obj", "build/brucelee.raw",
        "--size", str(PROG_SIZE))

    # raw disk: program at LBA 0, then the title picture blobs
    # (LBAs must match TITLE0_LBA/TITLE0_SEC in src/title.mac)
    manifest = {"geometry": {"size": DISK_SIZE},
                "entries": [{"file": "brucelee.raw", "lba": 0,
                             "sectors": PROG_SIZE // 512},
                            {"file": "title_p0.bin", "lba": 80,
                             "sectors": 12},
                            {"file": "title_p12.bin", "lba": 92,
                             "sectors": 24}]}
    (BUILD / "manifest.json").write_text(json.dumps(manifest, indent=1))
    run(py, "tools/dsk_build.py", "build/manifest.json", out, "--force")
    print(f"{out}: OK ({PROG_SIZE} byte program)")


if __name__ == "__main__":
    main()
