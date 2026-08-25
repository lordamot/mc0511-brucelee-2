# Bruce Lee for the UKNC (Elektronika MS-0511)

A faithful port of *Bruce Lee* (Datasoft, 1984; ZX Spectrum version
by Ocean) to the Soviet UKNC MS-0511 school computer.  The game logic
was reverse-engineered from the ZX Spectrum tape (`BRUCELEE.TAP`) and
re-implemented in MACRO-11 for the UKNC's twin PDP-11 processors:
all 20 chambers, both enemies with their AI, pickups, doors, hazards,
the wizard, two-player modes, beeper music/SFX and the Ocean loading
picture as the title screen.

Everything builds from editable text/BMP sources into a bootable
`.dsk` image with modern PC-based tools - no vintage software needed.

## Requirements

- Linux, Python 3 with Pillow (`python3 -m pip install pillow`)
- prebuilt tools in `bin/` (MACRO-11 assembler, UKNCBTL-based
  emulators); rebuild them from source with `make toolchain`
  (needs `gcc`/`make`, clones/uses sources under `tmp/`)

## Build and run

```
make build     # sources -> build/brucelee.dsk (bootable image)
make run       # build + play in an SDL window
make shot      # headless: boot to the game menu, screenshot to tmp/
make demo      # headless: start a game, walk into chamber 1
make verify    # generators, title round-trip, image checks, plus a
               # boot-to-gameplay smoke test and engine behavior
               # checks (lamp pickup, fall landing) in the headless
               # emulator
```

In `make run` the firmware boot menu loads the disk automatically;
the title picture shows for ~10 s (any key skips it).  Controls:
arrows = move/jump/duck/climb, ФИКС (mapped to LCtrl) = player 1
fire (fire+direction = punch/kick), numpad Enter (RCtrl) = player 2
fire, Enter = menu select, АП2/СТОП = pause.

## Project layout

| Path | Contents |
|---|---|
| `src/*.mac` | MACRO-11 sources (CPU game engine + PPU program) |
| `src/brucelee.list` | module order = memory order of the image |
| `src/res/` | editable resources: chambers, tiles, sprites, font, strings, HUD, title BMP |
| `tools/` | build pipeline + resource generators + emulator drivers (Python) |
| `bin/` | prebuilt assembler and emulators |
| `orig/` | unpacked ZX Spectrum originals (reference for extraction) |
| `build/` | build products (not committed) |
| `.claude/docs/` | reverse-engineering notes and port design |

Resources are the source of truth: edit `src/res/chambers/chNN.txt`
(hex cell grids + header fields), `src/res/tiles/tiles.txt`
(`#`-bitmaps + ink class), `src/res/sprites/*.txt`,
`src/res/text/strings.txt` or `src/res/pics/title.bmp` and rebuild.
They were extracted once from the ZX memory image by
`tools/extract_res.py`.

## The machine

The UKNC has two PDP-11 processors: the CPU runs the game engine, a
PPU program (loaded over channel K2 at startup) owns the video line
table with a palette element per 8-line cell row, the keyboard, the
vsync exchange and the beeper sound engine in its idle loop.  The
game renders into a back buffer in CPU RAM and blits through the
plane 1+2 video registers; the title picture additionally uses video
plane 0, which only the PPU can reach.  See
`.claude/docs/port-plan.md` for the memory map and the details, and
`.claude/docs/re-notes.md` for the ZX reverse-engineering notes.

## Credits

- Original game: Datasoft, Inc. (1984); ZX Spectrum conversion:
  Ocean Software.  This is a non-commercial preservation/porting
  project; the original game content belongs to its rights holders.
- Emulator core: [UKNCBTL](https://github.com/nzeemin/ukncbtl-qt)
  (LGPL), used for the bundled headless test runner and player.
- MACRO-11 assembler: Richard Krehbiel's `macro11` (see
  `bin/macro11/LICENSE`).
