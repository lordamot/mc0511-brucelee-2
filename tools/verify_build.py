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

  gameplay    engine behavior in the headless emulator (Bruce is
              teleported with pokecpu): the collectible lamps render
              yellow, a fall lands back into the standing state in
              place (ZX D112), and picking a lamp up scores 125 and
              removes it from the map

  moves       Bruce's moves: fire standing = the fist strike, fire
              mid-walk = the flying kick, up mid-walk = the side
              jump, down over a ladder = climb down centred on it,
              and a misaligned climb from the bottom still passes
              the one-hole floor at the top (CLIMB_SNAP)

  enemies     the ninja: activates promptly at his own rate (the
              score fill must not spill into his record), walks at
              the ZX pace and actually strikes an adjacent Bruce
              (state 0x16 exists in his state table)

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


def verify_gameplay(tmp):
    bruce = symbol_addr("BRUCE")
    score1 = symbol_addr("SCORE1")
    hdr = symbol_addr("HDR")            # MAPB = HDR: map cell base
    e_state, e_yoff, e_col = bruce + 2, bruce + 4, bruce + 6
    lamp_top = hdr + 18 * 32 + 17       # chamber 0 lamp at (17, 18)
    script = tmp / "gameplay.script"
    script.write_text(f"""\
run 900
press 030
run 30
press 153
run 350
press 153
run 100
press 153
run 100
screenshot {tmp}/g-start.bmp
pokecpu {e_yoff:o} 0
pokecpu {e_col:o} 4 3
run 150
dumpcpu {bruce:o} 20 {tmp}/g-fall.bin
pokecpu {e_col:o} 21 22
run 60
dumpcpu {score1:o} 6 {tmp}/g-score.bin
dumpcpu {lamp_top:o} 1 {tmp}/g-lamp.bin
quit
""")
    r = run([REPO_ROOT / "bin/ukncbtl/uknc-headless",
             "--rom", REPO_ROOT / "bin/ukncbtl/uknc_rom.bin",
             "--disk", REPO_ROOT / "build/brucelee.dsk",
             "--script", script], timeout=300)
    check("gameplay script runs", r.returncode == 0, r.stderr.strip())
    if r.returncode != 0:
        return

    start = count_colors(tmp / "g-start.bmp")
    yellow = sum(n for c, n in start.items()
                 if c[0] > 180 and c[1] > 180 and c[2] < 80)
    check("lamps render yellow", yellow > 100, f"yellow={yellow}")

    rec = (tmp / "g-fall.bin").read_bytes()
    state, col, row = rec[2], rec[6], rec[7]
    check("fall lands standing in place (ZX D112)",
          state == 1 and col == 4 and row == 6,
          f"state={state} col={col} row={row}")

    score = (tmp / "g-score.bin").read_bytes()
    check("lamp pickup scores 125", score == b"000125", score.decode())
    lamp = (tmp / "g-lamp.bin").read_bytes()[0]
    check("collected lamp leaves the map", lamp != 0x10, f"tile={lamp:02x}")


GAME_START_SCRIPT = """\
run 900
press 030
run 30
press 153
run 350
press 153
run 100
press 153
run 60
"""


def ent_rec(path):
    """Entity record dump -> dict of the interesting fields."""
    b = Path(path).read_bytes()
    return {"tick": b[0], "reload": b[1], "state": b[2], "yoff": b[4],
            "col": b[6], "row": b[7], "death": b[10], "dmg": b[14]}


def verify_moves(tmp):
    bruce = symbol_addr("BRUCE")
    ninja = symbol_addr("NINJA")
    yamo = symbol_addr("YAMO")
    lines = [GAME_START_SCRIPT,
             # keep the enemies hidden while testing Bruce's moves
             f"pokecpu {ninja + 16:o} 377",
             f"pokecpu {yamo + 16:o} 377"]
    # fire standing: the fist strike (0x16), then its recovery (0x0b)
    lines += ["keydown 107"]
    for i in range(6):
        lines += ["run 2", f"dumpcpu {bruce:o} 20 {tmp}/m-fist{i}.bin"]
    lines += ["keyup 107", "run 20"]
    # fire mid-walk: the flying kick (states 4/5, ZX 0x11 command)
    lines += ["keydown 133", "run 12", "keydown 107"]
    for i in range(8):
        lines += ["run 2", f"dumpcpu {bruce:o} 20 {tmp}/m-kick{i}.bin"]
    # separate key releases with a run: the ROM keyboard scan delivers
    # one release event per pass, simultaneous ones lose a key
    lines += ["keyup 107", "run 3", "keyup 133", "run 30"]
    # up mid-walk: the side jump (states 9/0xA, row-1; ZX 0x09 command)
    lines += [f"pokecpu {bruce + 2:o} 1", f"pokecpu {bruce + 4:o} 0",
              f"pokecpu {bruce + 6:o} 4 6", "run 5",
              "keydown 133", "run 15", "keydown 154"]
    for i in range(8):
        lines += ["run 2", f"dumpcpu {bruce:o} 20 {tmp}/m-jump{i}.bin"]
    lines += ["keyup 154", "run 3", "keyup 133", "run 30"]
    # down over the chamber-0 ladder, one column off: descend centred
    lines += [f"pokecpu {bruce + 2:o} 1", f"pokecpu {bruce + 4:o} 0",
              f"pokecpu {bruce + 6:o} 13 6", "run 5",
              "keydown 134", "run 40",
              f"dumpcpu {bruce:o} 20 {tmp}/m-down.bin",
              "keyup 134", "run 10"]
    # climb from the bottom, one column off: snap must centre Bruce so
    # the one-hole floor at the ladder top lets him through
    lines += [f"pokecpu {bruce + 2:o} 1", f"pokecpu {bruce + 4:o} 0",
              f"pokecpu {bruce + 6:o} 15 24", "run 5",
              "keydown 154", "run 300", "keyup 154", "run 25",
              f"dumpcpu {bruce:o} 20 {tmp}/m-top.bin", "quit"]
    script = tmp / "moves.script"
    script.write_text("\n".join(lines) + "\n")
    r = run([REPO_ROOT / "bin/ukncbtl/uknc-headless",
             "--rom", REPO_ROOT / "bin/ukncbtl/uknc_rom.bin",
             "--disk", REPO_ROOT / "build/brucelee.dsk",
             "--script", script], timeout=300)
    check("moves script runs", r.returncode == 0, r.stderr.strip())
    if r.returncode != 0:
        return

    seen = {ent_rec(tmp / f"m-fist{i}.bin")["state"] for i in range(6)}
    check("fire standing does the fist strike (0x16)",
          seen & {0x16, 0x0B} != set(), f"states={sorted(map(hex, seen))}")

    seen = {ent_rec(tmp / f"m-kick{i}.bin")["state"] for i in range(8)}
    check("fire mid-walk does the flying kick (04/05)",
          seen & {0x04, 0x05} != set(), f"states={sorted(map(hex, seen))}")

    jumps = [ent_rec(tmp / f"m-jump{i}.bin") for i in range(8)]
    ok = any(j["state"] in (0x09, 0x0A) and j["row"] == 5 for j in jumps)
    check("up mid-walk does the side jump (09/0A, row-1)", ok,
          " ".join(f"{j['state']:02x}@{j['row']}" for j in jumps))

    d = ent_rec(tmp / "m-down.bin")
    check("down over the ladder descends centred",
          d["state"] in (0x0E, 0x0F) and d["col"] == 12 and d["row"] >= 9,
          f"state={d['state']:02x} col={d['col']} row={d['row']}")

    t = ent_rec(tmp / "m-top.bin")
    check("misaligned climb passes the floor hole to the top",
          t["state"] == 1 and t["col"] == 12 and t["row"] == 6,
          f"state={t['state']:02x} col={t['col']} row={t['row']}")


def verify_enemies(tmp):
    bruce = symbol_addr("BRUCE")
    ninja = symbol_addr("NINJA")
    lines = [GAME_START_SCRIPT,
             f"pokecpu {bruce + 6:o} 10 24",     # Bruce to the bottom floor
             "run 20", f"dumpcpu {ninja:o} 20 {tmp}/n-act.bin",
             "run 50"]
    for i in range(16):
        lines += ["run 10", f"dumpcpu {ninja:o} 20 {tmp}/n{i}.bin",
                  f"dumpcpu {bruce:o} 20 {tmp}/nb{i}.bin"]
    lines += ["quit"]
    script = tmp / "enemies.script"
    script.write_text("\n".join(lines) + "\n")
    r = run([REPO_ROOT / "bin/ukncbtl/uknc-headless",
             "--rom", REPO_ROOT / "bin/ukncbtl/uknc_rom.bin",
             "--disk", REPO_ROOT / "build/brucelee.dsk",
             "--script", script], timeout=300)
    check("enemies script runs", r.returncode == 0, r.stderr.strip())
    if r.returncode != 0:
        return

    act = ent_rec(tmp / "n-act.bin")
    check("ninja record keeps its rate (score fill overflow)",
          act["reload"] == 4 and act["tick"] <= 4,
          f"reload={act['reload']} tick={act['tick']}")

    recs = [ent_rec(tmp / f"n{i}.bin") for i in range(16)]
    check("ninja activates promptly", recs[0]["state"] != 0,
          "still hidden after ~5 s")
    walked = [r_["col"] for r_ in recs if r_["row"] == 20]
    check("ninja walks the bottom floor towards Bruce",
          len(walked) >= 2 and walked[0] - walked[-1] >= 3,
          f"cols={walked}")
    dmg = max(ent_rec(tmp / f"nb{i}.bin")["dmg"] for i in range(16))
    check("ninja strikes an adjacent Bruce (state 0x16)", dmg > 0,
          "Bruce took no damage")


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
            print("gameplay:")
            verify_gameplay(tmp)
            print("moves:")
            verify_moves(tmp)
            print("enemies:")
            verify_enemies(tmp)

    if failures:
        print(f"\n{len(failures)} check(s) FAILED: " + ", ".join(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
