# Bruce Lee UKNC port - design

Target: faithful port of the ZX Spectrum game logic (see re-notes.md)
to the UKNC MC-0511, structured like `../mc0511-openit` (boot sector +
flat program on a raw .dsk, MACRO-11 sources, PPU program for video
setup / keyboard / sound, resources generated from editable files).

## Memory map (CPU side, octal)

| Range | What |
|---|---|
| 0..777 | boot sector (src/boot.mac, from openit) |
| 1000..~120000 | program + data (code, chambers, tiles, sprites, strings) |
| ~120000..127777 | runtime: current map (704B) + pristine map + variables; stack below 130000 |
| 130000..157777 | back buffer: 24 cell rows x 32 cells x 16 bytes (8 words = 8 lines of 8 double px in planes 1+2) |

Planes are 64KB each; the CPU address space maps to plane bytes
0..24575.  The visible screen lives at plane bytes 0o100000/2+ and is
reachable only through `@#176640` (byte address reg) / `@#176642`
(planes 1+2 word data).  So the back buffer is plain CPU memory and
the blit is the only video-register work.

## Video

- Whole screen 320 mode (mode word 27), 40 visible bytes/line, line
  stride 80 bytes (firmware/openit convention), 288 lines.
- Game area = ZX layout 32x24 cells of 8x8 (double-wide) px: X offset
  4 bytes, Y offset 48 lines.  Rows 0-1 score HUD, rows 2-23 map.
- Colors: planes 1+2 only in the game area -> pixel values 0/2/4/6,
  remapped by palette to black / [three inks].  v1 global palette:
  black, red, green, white.  DONE: every 8-line cell row of the game
  area starts with a 4-word palette element in the PPU line table
  (ppu.mac NEW_TABLE; 4-word elements must be 8-byte aligned - the
  video controller masks next-links with ~7, hence the 4 pad bytes
  per row block).  PPU COMMAND_2 rewrites all 24 row palettes from
  the CPU ROWPALS array (24 x 2 words, nibble = Y*8+R*4+G*2+B).
  DONE: CH_LOAD calls CH_ROWPALS (title.mac), which scans the live
  map after the patch list and gives every cell row that holds a
  collectible lamp (tiles octal 20..26) a bright-yellow "warm" ink
  (value 4 nibble C -> E) - the lanterns are yellow as on the ZX,
  and the lamp tiles are combo=1 (warm) in tiles.txt.  Trade-off:
  a red/magenta tile sharing a cell row with a lamp shows yellow in
  that row (9 such rows: chambers 2, 11, 16, 17).
- Tiles are pre-colored at build time: 8 words (16 bytes) per tile,
  low byte plane 1, high byte plane 2 (tools/tiles_gen.py from
  tiles.txt: `#`-bitmap + ink class 1..3 per tile).
- Sprites stay 1bpp cell glyphs + masks like the ZX (two sets:
  normal + pre-shifted 4px); the cell-draw routine expands to the
  entity's plane combo (three specialized inner loops).
- Draw architecture is the ZX one: restore map cells under entity
  into the back buffer, draw masked sprite cells into the back
  buffer, blit the entity's 5x4-cell region to the screen after
  vsync.  Full-screen blit on chamber load (and FE0B-style flag).

## Processors

CPU: all game logic (the ported engine).  PPU (src/ppu.mac, loaded
via channel K2 like openit): video line table + palette, keyboard ->
key word in CPU RAM, vsync flag, FDD motor bookkeeping, and the
**beeper music/SFX engine** in its idle loop: tone tables copied from
the ZX data (music.json), speaker = bit 7 of PPU port 177716.
CPU->PPU mailbox in CPU RAM selects song/SFX; K1 commands as in
openit (screen setup, palette).

Keyboard mapping (PPU): arrows = move/jump/duck, FIKS (0107) = P1
fire, numpad ENTER (0166) = P2 fire (Yamo), AP2/STOP = pause menu,
ENTER = menu select.  Fire+direction = punch/kick as on ZX kempston.

## The game engine (ported 1:1 from the RE, see re-notes.md)

- 3 entity records (Bruce CCA5, Yamo CBBE, ninja CB1C): tick counter,
  state, facing, y-pixel offset(+4), x-halfcell(+3), col/row, damage,
  death counter, per-state table {info ptr, handler ptr}.
- Info blocks [w, h, cell codes...] = animation frames (extracted).
- State handlers (walk/jump arc table 7,5,3,2,1... /climb/fall/punch/
  kick/stagger) ported from the Z80 handlers (cd9b..d24d).
- AI (d24e..d7ab): input synthesis for Yamo/ninja, chase/climb logic,
  respawn spawn points from chamber header.
- Collision by tile class: >=40h solid, 18h-1Fh climbable(+floor),
  20h-3Fh scenery, 17h exit (per-chamber exit handler), 10h-16h
  pickup (pixel-overlap test, lantern removal marks the patch list so
  chambers stay looted per player).
- Chamber format: header 64B (attr page, patch list, border, spawn
  points, exit thresholds 600E-6011, exit table 6012+, anim specs
  6030/34/38) + RLE map + patch list; 20 chambers.
- Per-chamber tables: frame hazards (D7AC), pickup handlers (D7D4),
  exit handlers (D7FC); door-opening slots FE60; the wizard bolt
  (DE47) pushes entities, the collapsing floor, growing plants
  (DDA8), tile animations (DF7A).
- Score: ASCII 6-digit + bonus strings; lives 2-digit ASCII, extra
  life on thresholds; HUD rows 0-1 from a 64-char text buffer.
- Two players: alternating Bruces (FE07) with full state swap, or
  P2 controls Yamo (FE08).
- Menu: native UKNC screen (players 1/2, Yamo human/computer, start);
  attract mode = demo flag FE0B.

## Resources (all editable text/BMP under src/res/)

| Resource | Source form | Generator |
|---|---|---|
| tiles | res/tiles/tiles.txt (bitmap text + ink class) | tools/tiles_gen.py |
| chambers | res/chambers/chNN.txt (hex cell grid + header fields) | tools/chambers_gen.py |
| sprites | res/sprites/*.txt (cell bitmaps + frame info blocks) | tools/sprites_gen.py |
| entity tables | res/entities.txt (state->handler/frame map) | part of sprites_gen |
| music | res/music/*.txt (note tables) | tools/music_gen.py |
| font+strings | res/font/font8.txt, res/text/strings.txt | font_gen/text_gen (openit) |
| title | res/pics/title.bmp (256x192, ZX loading screen) | tools/pic_conv.py |

Extraction (one-time, from orig/game48k.bin): tools/extract_res.py
writes the res/ files; they are then the editable source of truth.

## Build

`make build`: generators -> build/*.mac, concatenate per
src/brucelee.list, macro11 -yus -ysl 64, obj2bin, dsk_build ->
build/brucelee.dsk.  `make run` (SDL window), `make shot`, `make
verify` (resource round-trip + boot smoke test in headless emulator).

## Title screen (milestone 7, done)

The Ocean loading screen is an editable 256x192 BMP
(src/res/pics/title.bmp, extracted once with `pic_conv.py decode`).
tools/pic_conv.py encodes it into three blobs at build time: plane 0
(6144 B), planes 1+2 (12288 B, back-buffer layout) and 24 row
palettes (build/data_title.mac, in the program image).  The pixel
blobs sit on the disk at LBA 80/92 (manifest in build_brucelee.py,
constants in src/title.mac - verify_build.py cross-checks them).

Runtime flow (src/title.mac): TITLE_LOAD runs FIRST thing in
MAIN_START, while the PPU still runs the firmware:

- **The firmware K2 FDD service dies as soon as MAIN touches the CPU
  vectors (100/4/10) and never works once our PPU program runs (its
  idle loop is the sound engine and never returns to the firmware
  main loop, unlike openit's).**  All disk data must therefore be
  loaded before that; there are no runtime disk reads later.
- The plane-0 blob is parked in a firmware-allocated PPU RAM block
  (K2 command 1 - which must be waited for via K2ERR, the result is
  written asynchronously; then command 20, no completion byte).
  Alloc must happen BEFORE any FDD op, or the firmware returns 0.
- After PP_MAIN_LOAD, TITLE_SHOW: COMMAND_3 copies the parked block
  into plane-0 VRAM (window bits 4-6 of PPU port 177054 must select
  RAM; done at priority 340), COMMAND_2 sets the row palettes,
  BLIT_FULL shows planes 1+2 from BUF; ~10 s or any key; then
  COMMAND_5 clears plane 0 and the standard palette returns.

VBLF note: the vsync ISR clamps the pending-frame bits to 3
(BIC #177770) - a long stall would otherwise shift bits into the
sign and ASR in VSYNC would never consume them again.

## Milestones

1. boot + PPU + chamber 0 rendered (tiles, colors) [DONE]
2. Bruce: walk/jump/duck/climb/fall vs collision [DONE]
3. enemies + AI + combat, death/lives [DONE]
4. pickups, doors, exits, chamber graph, all 20 chambers, hazards [DONE]
5. HUD/score/menu/2P [DONE]
6. music + SFX in PPU [DONE]
7. title screen, polish, docs, verify [DONE]
