#!/usr/bin/env python3
"""Extract the beeper music/jingles from the Bruce Lee memory image.

Engine (player at 0x95E2, all data static):
  song:   list of phrase pointers, word 0 ends
  phrase: list of 6-byte note records {tone_ptr, cycles, rest}, word 0 ends
  tone:   list of half-period words (usually two, an octave apart),
          word 0 ends; one 'cycle' plays the whole list once through
          the speaker-toggle + 26T/iter delay loop.

Entry points: 0x9300 -> song 0x935C (tune), 0x9306 -> 0x933A (death),
0x930C -> 0x9346 (pickup/lantern).

Usage:
  python3 tools/music_extract.py IMAGE.bin json OUT.json
  python3 tools/music_extract.py IMAGE.bin wav SONG OUT.wav   (SONG: tune|death|pickup)
"""
import json
import struct
import sys
import wave
from pathlib import Path

BASE = 0x4000
SONGS = {"tune": 0x935C, "death": 0x933A, "pickup": 0x9346}
TSTATES = 3500000
# delay loop: dec de(6) + ld a,d(4) + or e(4) + jr nz(12) = 26 T per count;
# per toggle overhead: ld a,(nn)13 + xor 7 + ld (nn),a 13 + out 11 +
# fetch pair ~40 = roughly 84 T
LOOP_T = 26
TOGGLE_T = 84


def word(mem, a):
    return mem[a - BASE] | (mem[a - BASE + 1] << 8)


def parse_song(mem, addr):
    phrases = []
    a = addr
    while True:
        p = word(mem, a)
        a += 2
        if p == 0:
            break
        phrases.append(p)
    out = []
    for ph in phrases:
        notes = []
        a = ph
        while True:
            tone = word(mem, a)
            if tone == 0:
                break
            cycles = word(mem, a + 2)
            rest = word(mem, a + 4)
            a += 6
            periods = []
            t = tone
            while True:
                hp = word(mem, t)
                if hp == 0:
                    break
                periods.append(hp)
                t += 2
            notes.append({"tone": tone, "periods": periods,
                          "cycles": cycles, "rest": rest})
        out.append({"phrase": ph, "notes": notes})
    return out


def synth(song, rate=44100):
    samples = bytearray()
    level = 40
    for phrase in song:
        for note in phrase["notes"]:
            for _ in range(note["cycles"]):
                for hp in note["periods"]:
                    t = hp * LOOP_T + TOGGLE_T
                    n = max(1, round(t / TSTATES * rate))
                    level = 215 - level  # toggle around midpoint
                    samples += bytes([level]) * n
            # rest: busy loop, speaker still
            t = note["rest"] * LOOP_T
            n = round(t / TSTATES * rate)
            samples += bytes([samples[-1] if samples else 128]) * n
    return samples


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 1
    mem = Path(sys.argv[1]).read_bytes()
    cmd = sys.argv[2]
    if cmd == "json":
        data = {name: parse_song(mem, addr) for name, addr in SONGS.items()}
        Path(sys.argv[3]).write_text(json.dumps(data, indent=1))
        for name, song in data.items():
            n = sum(len(p["notes"]) for p in song)
            print(f"{name}: {len(song)} phrases, {n} notes")
        print(f"wrote {sys.argv[3]}")
    elif cmd == "wav":
        song = parse_song(mem, SONGS[sys.argv[3]])
        pcm = synth(song)
        with wave.open(sys.argv[4], "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(1)
            w.setframerate(44100)
            w.writeframes(bytes(pcm))
        print(f"wrote {sys.argv[4]} ({len(pcm)/44100:.1f}s)")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
