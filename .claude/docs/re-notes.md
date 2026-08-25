# Reverse-engineering notes: BRUCELEE.TAP (ZX Spectrum, Ocean/Datasoft)

Everything below was recovered from the tape in this repo with the
tools in `tools/` and verified against the running game in ZEsarUX
(`tools/zx_control.py`).  Addresses are the ZX memory map.

## Tape structure (tools/tap_extract.py, tools/snapshot_unpack.py)

The tape is a *memory snapshot*, not a normal program:

| Block | Loads at | Content |
|---|---|---|
| Program "Bruce Lee" | BASIC | loader: CLEAR 24791, USR 24830, USR 24833 |
| "Bruce Leeª" 6912 | screen | loading screen (Ocean) |
| "bruce lee3" 31749 @24792 | 0x60D8 | stub + RLE-packed RAM 0x62B0..0xFFFF |
| "bruce lee2" 12 @16384 | 0x4000 | RLE-packed screen+attr fill (0x4000..0x5AFF) |
| "bruce lee1" 1968 @16464 | 0x4050 | plain copy -> 0x5B00..0x62AF |

RLE stream is consumed backwards; escape = bytes `C B val 37 ED CB`
meaning "val repeated BC times".  The restore stub at 0x6247 pops the
register file from its own image and RETs to the saved PC.
`tools/snapshot_unpack.py` rebuilds the 48K image (orig/game48k.bin);
`tools/make_sna.py` converts it to orig/brucelee.sna which boots in
ZEsarUX (48k machine + /usr/share/spectrum-roms/48.rom).

Snapshot state: SP=0x62E6, PC=(SP)=0x02B1 (inside ROM key scan), IM1,
DI, I=0x3F.  The game then rebuilds its own IM2 world: vector table
0xFD00..0xFE00 = 0xFE, handler 0xFEFE `jp 0xC003`, I=0xFD.

## Memory map (running game)

| Range | What |
|---|---|
| 0x4000-0x5AFF | screen + attrs |
| 0x5B00-0x5CFF | ? (loaded from tape block 1) |
| 0x5D00-0x5FFF | pristine copy of header+map (restore source) |
| 0x6000-0x603F | current chamber header (copied from chamber blob) |
| 0x6040-0x62FF | current chamber map: 32x22 tile codes (screen rows 2-23) |
| 0x6300-0x63FF | tile attribute table: attr = [0x6300 + tilecode] |
| 0x6400-0x6428 | chamber pointer table, word per chamber, 20 chambers |
| 0x6429-0x91FF | chamber blobs (header 64B + RLE map + patch lists) |
| 0x92C0- | pause text?, sound routine at 0x932F, 0x962A |
| 0x9800-0x9FFF | tile glyphs (code*8, 8 bytes per 8x8 cell) |
| 0xA000-0xA7FF | sprite glyph cells, unshifted (8 bytes per 8x8 cell) |
| 0xA800-0xAFFF | sprite glyph cells, pre-shifted 4px |
| 0xB000-0xBFFF | masks for the above (+0x1000 from data) |
| 0xC003-0xDE47 | game code (ISR, main loop, entities, draw) |
| 0xCB1C/0xCBBE/0xCCA5 | entity records: Ninja, Yamo, Bruce (D675 feeds FE11 to 0xCCA5 = Bruce; 0xCB1C is skipped in CD9B's up-diagonal jump = the ninja) |
| 0xE000-0xF7FF | off-screen pixel back buffer (linear cell layout) |
| 0xF800-0xFAFF | off-screen attr back buffer |
| 0xFD00-0xFE01 | IM2 vector table (0xFE) |
| 0xFE02-0xFEFF | game variables (see below) |

## Variables (0xFExx)

| Addr | Meaning |
|---|---|
| FE02 | vsync flag bits (ISR shifts 1 in, main loop consumes) |
| FE03 | chamber number 0..19 |
| FE04 | player count? (1/2; checked ==2 for player-2 input swap) |
| FE05/06 | 16-bit frame counter (zeroed on chamber load) |
| FE07 | ? (two-player related) |
| FE08 | player-2 active flag |
| FE09/FE0A | input device P1/P2: 0 keyboard, 1 IF2, 2 kempston, 3 protek |
| FE0B | attract/demo flag (0 = normal play) |
| FE0D | ? (affects enemy activation delay 0x0A vs 0x28) |
| FE10 | raw input byte this frame (kempston bit order: R,L,D,U,F) |
| | command values (hex!): 1 R, 2 L, 4 D, 8 U, 9/0xA = up+dir (stand: start run CDAB; walk: vault jump CE89/CED3), 0x10 = fire (stand: fist strike 0x16 at CDE9), 0x11/0x12 = fire+dir (walk: flying kick, state 4, run-up >= 2 at CE73/CEBD) |
| FE11/12 | processed input word |
| FE13/14 | previous input P1/P2 |
| FE15 | bit0: current player flag |
| FE1B/1C | latched direction P1/P2 |
| FE60-FE71 | timers/state cleared on chamber load (18 bytes) |
| FE72-FE80 | frame-tick counters (FE73/78/7D inc every ISR) |
| FE99 | ISR tick counter |
| FE9A | sound on/off (SYMBOL SHIFT toggles) |
| FEA0-FEA9 | draw scratch (sprite base, attr ptr, map ptr) |
| FED0/D1 | score digits (partly ASCII math) |

## Key routines

| Addr | What |
|---|---|
| C003 | IM2 ISR: input scan -> FE10/11, counters |
| C085 | input dispatch by device type; key tables at C0E5/C10D/C112/C117 |
| C121 | per-frame system keys: SHIFT+SPACE restart, ENTER pause, SS sound toggle |
| C16E | chamber loader (DI!): copy header, RLE map -> 0x6040, pristine copy -> 0x5D00, patch list, draw all cells, reset entities, blit 0xE000->screen |
| C1F8 | draw whole map loop |
| C2B8 | write attr to back buffer |
| C2C0 | draw tile: glyph from (0x6000)+code*8 -> 0xE000 buf, attr from (0x6003) page -> 0xF800 buf |
| C2EC | entity update (movement state machine), IX=entity |
| C366 | restore background under entity (5-wide cell strip from map) |
| C3CB | draw entity sprite: composition list, glyphs 0xA000/0xA800(+4px), masks +0x1000, AND/OR into back buffer |
| C7AB | main loop: vsync wait, C121, entity updates C2EC x3, draws C366/C3CB x3 |
| C99B | add score: HL = 6-ASCII-digit amount; updates score, top score, extra-life check (port: score.mac SCORE_ADD) |
| CA37 | dispatch on (FE03) via jump table after call site |
| DE41 | called on chamber load |

## Entity record (0xA2 bytes Bruce; layout partial)

| Off | Meaning |
|---|---|
| +2 | draw state / composition index (0 = hidden) |
| +3 | 4px-shift flag (selects 0xA800 sprite set) |
| +4 | x byte offset within row |
| +5 | colour |
| +6 | map column (0..28) |
| +7 | map row (2..19) |
| +8/+9 | clamped copies of +6/+7 |
| +0x11 | table: composition-list pointers (4 bytes/entry: dims ptr, data ptr) |
| +0x16 | table: background-restore pointers |
| +0x2C | enemy activation delay counter (0xCB2C for entity2...) |

## Chamber blob format (tools/chamber_extract.py)

Header 64 bytes: +0 tile glyph base (all use 0x9800), +3 attr page
(all 0x63), +6 patch list ptr, +0x0B border colour, +0x0C/0D lantern
counters?, +0x0E.. object/lantern position list (format TBD).
Then RLE map: ctrl 0=end, bit7 set = copy n&0x7F literals, else
repeat next byte n times.  704 cells = 32 x 22.

Patch list (at header+6): guarded 3-byte entries, applied to the map
copy at 0x6000 by the loader; guard bytes have bit7 (0xFF ends the
list); guard & player-number selects per-player variants (doors).

## Emulator driving (tools/zx_control.py)

- launch --sna orig/brucelee.sna --machine 48k --romfile /usr/share/spectrum-roms/48.rom
  (Kempston joystick emulation enabled by default)
- game start: press SPACE (menu appears), C cycles input device,
  ENTER begins; then `write-memory 65033 02` forces P1=kempston and
  `joy RIGHT 50` etc. drives Bruce.
- menu keys in original: A players, B opponent, C input; QAOP move,
  Z-M punch/kick, ENTER pause, SHIFT+SPACE restart, SS sound toggle.
- `dump ADDR LEN FILE` saves live memory (used for runtime-built
  structures: IM2 table, back buffers).

## Still to decode

- lantern/object list in header (+0x0E..) and exit/door mechanics
- sprite composition tables (entity +0x11/+0x16) and all frames
- movement physics (walk/jump/duck/climb/fall) in C2EC..
- Yamo/Ninja AI
- collision (tile classes: solid/ladder/vine/hazard/exit)
- score/lives/HUD drawing
- beeper SFX (0x932F, 0x962A, 0xC29F?, 0xC4C2, 0xCF00) and the
  title/background music player
- what 0x5B00-0x5CFF holds
