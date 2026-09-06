#!/usr/bin/env python3
"""Watch a charging session and report what the protocol did.

Run with a vehicle connected to observe what an idle charger cannot show: fault
codes, start and stop reasons, session limit units and state transitions::

    python3 tools/besen_session_watch.py --serial <16 hex> --minutes 30

Entirely passive, so it is safe alongside Home Assistant. Decoding goes through
the integration's own parser.
"""

from __future__ import annotations

import argparse
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components"))

from besen import protocol as proto  # noqa: E402
from besen.const import (  # noqa: E402
    CMD_AC_STATUS,
    CMD_AC_STATUS_ALT,
    CMD_CHARGE_RECORD,
    CMD_CHARGE_STATUS,
    CMD_CHARGE_STATUS_ALT,
)

#: Fields printed whenever they change.
WATCH = (
    "state", "state_code", "state_code_primary", "state_code_secondary",
    "plug_state", "output_state_raw", "emergency_stop_raw",
    "session_id", "session_user", "start_type_raw", "charge_type_raw",
    "session_max_current", "limit_duration", "limit_energy", "limit_cost",
    "phase_count_raw", "unknown_21_24", "unknown_tail_ac", "unknown_tail_session",
)
#: Fields summarised at the end rather than printed on every change.
NUMERIC = ("power", "current_l1", "current_l2", "current_l3",
           "session_energy", "session_duration", "energy_total")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--serial", required=True, help="16 hex digits")
    ap.add_argument("--port", type=int, default=28376)
    ap.add_argument("--minutes", type=float, default=30.0)
    args = ap.parse_args()

    serial = proto.normalise_serial(args.serial)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except OSError:
        pass
    sock.bind(("0.0.0.0", args.port))
    sock.settimeout(2.0)

    print(f"Watching {serial} for {args.minutes:g} minutes. Passive; nothing is sent.")
    print("Plug in, start a charge, let it run, then stop it.\n")
    print(f"{'time':>8}  field                     value")
    print("-" * 72)

    state: dict[str, object] = {}
    ranges: dict[str, tuple[float, float]] = {}
    records: list[dict] = []
    started = time.time()

    while time.time() - started < args.minutes * 60:
        try:
            data, _addr = sock.recvfrom(8192)
        except socket.timeout:
            continue
        frame = proto.parse_frame(data)
        if frame is None or frame.serial != serial:
            continue

        if frame.command in (CMD_AC_STATUS, CMD_AC_STATUS_ALT):
            new = proto.parse_ac_status(frame.payload)
        elif frame.command in (CMD_CHARGE_STATUS, CMD_CHARGE_STATUS_ALT):
            new = proto.parse_charge_status(frame.payload)
        elif frame.command == CMD_CHARGE_RECORD:
            record = proto.parse_charge_record(frame.payload)
            if record not in records:
                records.append(record)
                print(f"{time.time()-started:8.1f}  RECORD                    "
                      f"{record['energy']} kWh in {record['duration']}s, "
                      f"started by {record['start_reason']!r}, "
                      f"stopped by {record['stop_reason']!r}")
            continue
        else:
            print(f"{time.time()-started:8.1f}  UNKNOWN COMMAND           "
                  f"0x{frame.command:04X} {frame.payload.hex()}")
            continue

        for key, value in new.items():
            if key in NUMERIC and isinstance(value, (int, float)):
                lo, hi = ranges.get(key, (value, value))
                ranges[key] = (min(lo, value), max(hi, value))
            if key in WATCH and state.get(key) != value:
                if key in state:
                    print(f"{time.time()-started:8.1f}  {key:<24}  "
                          f"{state[key]!r} -> {value!r}")
                else:
                    print(f"{time.time()-started:8.1f}  {key:<24}  {value!r}")
            state[key] = value

    print("\n" + "-" * 72)
    print("ranges observed:")
    for key in NUMERIC:
        if key in ranges:
            lo, hi = ranges[key]
            print(f"  {key:<22} {lo} .. {hi}")
    print(f"\n{len(records)} charging record(s) uploaded during the window.")
    print("\nSend this whole output along when reporting how the session went.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
