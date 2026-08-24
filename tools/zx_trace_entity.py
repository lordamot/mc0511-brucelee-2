#!/usr/bin/env python3
"""Frame-accurate entity tracer for the running Bruce Lee original.

Uses a PC breakpoint on the main-loop top (0xC7AB) to stop once per
game frame, reads the entity records and input state, applies the
scripted joystick value, and continues.  The result is a CSV of
per-frame entity state - the ground truth for porting the physics.

Requires a running instance (tools/zx_control.py launch ...), with the
game IN PLAY and P1 input forced to kempston (write-memory 65033 02).

Usage:
  python3 tools/zx_trace_entity.py OUT.csv "20:NONE 30:RIGHT 40:RIGHT+FIRE 20:NONE"
  python3 tools/zx_trace_entity.py OUT.csv "60:UP" --entity 0xcbbe --comp

Script: space-separated FRAMES:JOYSPEC ('+'-joined RIGHT/LEFT/UP/DOWN/
FIRE or NONE).  --comp additionally captures the current composition
list bytes each frame.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from zx_control import ZRCP, IDLE_PORTS, JOYBITS, rows_for_joy

MAIN_LOOP_PC = 0xC7AB


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("script")
    ap.add_argument("--entity", default="0xcb1c")
    ap.add_argument("--comp", action="store_true")
    ap.add_argument("--port", type=int, default=10000)
    args = ap.parse_args()

    ent = int(args.entity, 0)
    steps = []
    for part in args.script.split():
        n, spec = part.split(":")
        val = 0
        for name in spec.split("+"):
            if name.upper() != "NONE":
                val |= JOYBITS[name.upper()]
        steps += [val] * int(n)

    z = ZRCP(port=args.port)

    # Real-time sampling: the emulator keeps running; we poll the entity
    # record as fast as ZRCP allows and use the game's own frame counter
    # (0xFE05, 16-bit, zeroed on chamber load) to timestamp/dedupe rows.
    rows = []
    seen_frame = -1
    try:
        idx = 0
        joy = steps[0] if steps else 0
        z.cmd(f"set-ui-io-ports {z.ports_hex(rows_for_joy(joy), joystick=joy)}")
        start = None
        while idx < len(steps):
            rec = bytes.fromhex(z.cmd(f"read-memory {ent} 24").strip())
            fe0x = bytes.fromhex(z.cmd("read-memory 65026 32").strip())
            fc = fe0x[3] | (fe0x[4] << 8)
            if start is None:
                start = fc
            frame = fc - start
            if frame < 0:  # counter reset (chamber change)
                start = fc
                frame = 0
            if frame >= len(steps):
                break
            if steps[frame] != joy:
                joy = steps[frame]
                z.cmd(f"set-ui-io-ports {z.ports_hex(rows_for_joy(joy), joystick=joy)}")
            if frame == seen_frame:
                continue
            seen_frame = frame
            idx = frame
            row = {
                "frame": frame, "joy": joy,
                "tick": rec[0], "rate": rec[1], "state": rec[2],
                "shift": rec[3], "sub": rec[4], "colour": rec[5],
                "col": rec[6], "row": rec[7], "ccol": rec[8], "crow": rec[9],
                "dying": rec[10], "f11": rec[11], "f12": rec[12],
                "f13": rec[13], "f14": rec[14], "f15": rec[15],
                "f16": rec[16], "f17": rec[17],
                "fe03": fe0x[1], "fe10": fe0x[14], "fe1a": fe0x[24],
            }
            if args.comp:
                st = row["state"]
                if st:
                    taddr = ent + 0x16 + 4 * (st - 1)
                    tw = bytes.fromhex(z.cmd(f"read-memory {taddr} 4").strip())
                    cptr = tw[0] | (tw[1] << 8)
                    hptr = tw[2] | (tw[3] << 8)
                    comp = bytes.fromhex(z.cmd(f"read-memory {cptr} 14").strip())
                    row["comp_ptr"] = f"{cptr:04x}"
                    row["handler"] = f"{hptr:04x}"
                    row["comp"] = comp.hex()
                else:
                    row["comp_ptr"] = row["handler"] = row["comp"] = ""
            rows.append(row)
            idx += 1
    finally:
        z.cmd(f"set-ui-io-ports {z.ports_hex(IDLE_PORTS)}")

    keys = list(rows[0].keys())
    with open(args.out, "w") as f:
        f.write(",".join(keys) + "\n")
        for r in rows:
            f.write(",".join(str(r[k]) for k in keys) + "\n")
    print(f"wrote {args.out} ({len(rows)} frames)")


if __name__ == "__main__":
    main()
