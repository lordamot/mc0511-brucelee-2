#!/usr/bin/env python3
"""Build a 48K .SNA snapshot from the unpacked Bruce Lee memory image.

The TAP's own restore stub defines the register file (see
snapshot_unpack.py); the .SNA format wants PC pushed on the stack, which
is exactly how the stub left it — so the image converts 1:1.

Usage:
  python3 tools/make_sna.py orig/game48k.bin orig/brucelee.sna
"""
import struct
import sys
from pathlib import Path

# register file recovered from the restore stub at 0x6247 (see
# snapshot_unpack.py output)
IY, IX = 0x5C3A, 0x0B6C
ALT_BC, ALT_DE, ALT_HL, ALT_AF = 0x1000, 0x5CF6, 0xFFFF, 0x2165
BC, DE, HL, AF = 0xFEFE, 0xFFFF, 0x6E27, 0xFFA8
I, R = 0x3F, 0x39
SP = 0x62E6          # (SP) holds the entry PC; RETN in the loader pops it
IFF2 = 0             # the stub took the DI path
IM = 1
BORDER = 0


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    ram = Path(sys.argv[1]).read_bytes()
    assert len(ram) == 49152, f"want 48K image, got {len(ram)}"
    hdr = struct.pack(
        "<BHHHHHHHHHBBHHBB",
        I, ALT_HL, ALT_DE, ALT_BC, ALT_AF,
        HL, DE, BC, IY, IX,
        (IFF2 & 1) << 2, R, AF, SP, IM, BORDER,
    )
    assert len(hdr) == 27
    Path(sys.argv[2]).write_bytes(hdr + ram)
    print(f"wrote {sys.argv[2]} ({27 + len(ram)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
