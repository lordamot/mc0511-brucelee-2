#!/usr/bin/env python3
"""Rebuild the running Bruce Lee memory image from the TAP blocks.

The tape is a compressed memory snapshot: "bruce lee3" holds an RLE
stream (escape = bytes `C B value 37 ED CB`, meaning `value` x BC,
consumed backwards) that unpacks downwards from 0xFFFF until the source
pointer reaches 0x62B0; "bruce lee2" (12 bytes) unpacks the same way
downwards from 0x5AFF; "bruce lee1" is copied plainly to 0x5B00.  The
restore stub then pops the register file and RETs to the game PC.

Usage:
  python3 tools/snapshot_unpack.py TAPDIR OUT.bin   (48K image, org 0x4000)

Prints the restored registers, SP and entry PC.
"""
import sys
from pathlib import Path


def unrle(src: bytes, src_end: int, src_start: int, dst_end: int, mem: bytearray):
    """Backwards RLE unpack; src indices relative to array `src`.

    Reads src[src_end-1] down to src[src_start]; writes mem[dst_end-1]
    downwards.  Returns final dst pointer (address of last byte written).
    """
    hl = src_end
    de = dst_end
    ix = src_start
    while True:
        if hl == ix:
            return de
        hl -= 1
        a = src[hl]
        if a == 0xCB and hl >= 2 and src[hl - 1] == 0xED and src[hl - 2] == 0x37:
            hl -= 2
            hl -= 1
            val = src[hl]
            hl -= 1
            b = src[hl]
            hl -= 1
            c = src[hl]
            count = (b << 8) | c
            # the stub writes once, then loops while BC != 0
            n = count if count else 0x10000
            for _ in range(n):
                de -= 1
                mem[de] = val
        else:
            de -= 1
            mem[de] = a


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    tapdir = Path(sys.argv[1])
    out = Path(sys.argv[2])
    lee3 = (tapdir / "05_bruce_lee3_24792.bin").read_bytes()  # org 0x60D8
    lee2 = (tapdir / "07_bruce_lee2_16384.bin").read_bytes()  # 12 bytes
    lee1 = (tapdir / "09_bruce_lee1_25264.bin").read_bytes()  # -> 0x5B00

    mem = bytearray(0x10000)

    def w3(addr):
        off = addr - 0x60D8
        return lee3[off] | (lee3[off + 1] << 8)

    src_hi = w3(0x60F7)   # 0xDCDD: end of the compressed stream
    src_lo = w3(0x60EF)   # 0x62B0: start of the compressed stream
    print(f"stream: {src_lo:#06x}..{src_hi:#06x}")

    # main stream -> memory downwards from 0x10000
    final = unrle(lee3, src_hi - 0x60D8, src_lo - 0x60D8, 0x10000, mem)
    print(f"main unpack wrote {0x10000-final} bytes: {final:#06x}..0xffff")

    # bruce lee2 (12 bytes at 0x4000) -> downwards from 0x5B00
    final2 = unrle(lee2, len(lee2), 0, 0x5B00, mem)
    print(f"aux unpack wrote {0x5B00-final2} bytes: {final2:#06x}..0x5aff")

    # bruce lee1 -> 0x5B00 linear
    mem[0x5B00 : 0x5B00 + len(lee1)] = lee1
    print(f"lee1 copied to 0x5b00..{0x5B00+len(lee1)-1:#06x}")

    # register restore: stack image copied from 0x6247+2.. to 0x4002
    stub = lee3[0x6247 - 0x60D8 : 0x6247 - 0x60D8 + 0x4F]
    sp = stub[0x1A] | (stub[0x1B] << 8)

    def word(k):
        return stub[k] | (stub[k + 1] << 8)

    regs = {}
    k = 2
    for name in ("iy", "ix", "bc'", "de'", "hl'", "af'", "bc", "de",
                 "af_r", "af_i", "hl", "af"):
        regs[name] = word(k)
        k += 2
    print("registers:", {n: f"{v:#06x}" for n, v in regs.items()})
    print(f"sp = {sp:#06x}")
    pc = mem[sp] | (mem[sp + 1] << 8)
    print(f"entry pc = (sp) = {pc:#06x} ({pc})")

    out.write_bytes(mem[0x4000:])
    print(f"wrote {out} (48K, org 0x4000)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
