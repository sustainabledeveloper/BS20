#!/usr/bin/env python3
"""Listen to a Besen charger, and optionally answer it.

Passive mode needs only a network path to the charger::

    python3 tools/besen_probe.py

Active mode answers the charger with acknowledgements and read-only queries.
It never sends start, stop, or any setting write::

    BESEN_PASSWORD=123456 python3 tools/besen_probe.py --active --serial <16 hex>

The password is read from the environment or prompted for, and is masked in the
frame dump.
"""

from __future__ import annotations

import argparse
import getpass
import os
import socket
import sys
import time
from collections import Counter

# Commands this tool may transmit. Nothing that changes charger behaviour.
SAFE_COMMANDS = {
    0x8003: ("heartbeat ack", b""),
    0x8004: ("AC status ack", b"\x01"),
    0x800D: ("AC status ack (alt)", b"\x01"),
    0x8005: ("session status ack", b"\x01"),
    0x8006: ("session status ack (alt)", b"\x01"),
    0x810D: ("button setting query", b"\x02\x00"),
    0x8002: ("login / device info request", b""),
    0x8001: ("login ack", b"\x01"),
}

MAGIC = b"\x06\x01"
TAIL = b"\x0f\x02"


def checksum(chunk: bytes) -> int:
    return sum(chunk) & 0xFFFF


def build(serial: str, password: str, command: int, payload: bytes = b"") -> bytes:
    serial_bytes = bytes.fromhex(serial)
    assert len(serial_bytes) == 8, "serial must be 16 hex digits"
    password_bytes = password.encode("ascii")
    assert len(password_bytes) == 6, "password must be exactly 6 characters"

    length = 25 + len(payload)
    frame = bytearray(length)
    frame[0:2] = MAGIC
    frame[2] = (length >> 8) & 0xFF
    frame[3] = length & 0xFF
    frame[5:13] = serial_bytes
    frame[13:19] = password_bytes
    frame[19] = (command >> 8) & 0xFF
    frame[20] = command & 0xFF
    frame[21 : 21 + len(payload)] = payload
    crc = checksum(frame[: length - 4])
    frame[length - 4] = (crc >> 8) & 0xFF
    frame[length - 3] = crc & 0xFF
    frame[length - 2 :] = TAIL
    return bytes(frame)


def parse(data: bytes) -> tuple[str, int, bytes] | None:
    if len(data) < 25 or data[0:2] != MAGIC or data[-2:] != TAIL:
        return None
    if ((data[2] << 8) | data[3]) != len(data):
        return None
    if checksum(data[:-4]) != ((data[-4] << 8) | data[-3]):
        return None
    return data[5:13].hex(), (data[19] << 8) | data[20], data[21:-4]


def masked(frame: bytes) -> str:
    """Hex dump with the password field masked."""
    return frame[:13].hex() + "·" * 12 + frame[19:].hex()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="print the payload of every received frame")
    ap.add_argument("--port", type=int, default=28376)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--serial", help="only act on this charger (16 hex digits)")
    ap.add_argument(
        "--active",
        action="store_true",
        help="answer the charger with acknowledgements and one read-only query",
    )
    ap.add_argument(
        "--ack-records",
        action="store_true",
        help="also acknowledge charging record uploads (0x800A). The charger "
        "may drop the record afterwards.",
    )
    args = ap.parse_args()

    password = ""
    if args.active:
        if not args.serial:
            print("--active requires --serial", file=sys.stderr)
            return 2
        password = os.environ.get("BESEN_PASSWORD") or getpass.getpass(
            "Charger password (6 characters, not echoed): "
        )
        if len(password) != 6:
            print("Password must be exactly 6 characters.", file=sys.stderr)
            return 2

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except OSError:
        pass
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("0.0.0.0", args.port))
    sock.settimeout(2.0)

    print(f"Listening on UDP {args.port} for {args.seconds:.0f}s"
          f"{' (active)' if args.active else ' (passive)'}\n")

    counts: Counter[int] = Counter()
    sent: Counter[int] = Counter()
    queried = False
    started = time.time()

    while time.time() - started < args.seconds:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            continue

        parsed = parse(data)
        if parsed is None:
            continue
        serial, command, payload = parsed
        if args.serial and serial.lower() != args.serial.lower():
            continue

        counts[command] += 1
        print(f"{time.time()-started:7.2f} <- {addr[0]}:{addr[1]} "
              f"cmd=0x{command:04X} len={len(data)} n={counts[command]}")
        if args.verbose:
            print(f"        payload({len(payload)}B) {payload.hex(' ')}")

        if not args.active:
            continue

        replies: list[int] = []
        if command == 0x0003:
            replies.append(0x8003)
        elif command in (0x0004, 0x000D):
            replies.append(0x8000 | command)
            if not queried:
                replies.append(0x8002)
                replies.append(0x810D)
                queried = True
        elif command in (0x0005, 0x0006):
            replies.append(0x8000 | command)
        elif command in (0x0001, 0x0002):
            # Acknowledge both halves; query only after the confirm.
            replies.append(0x8001)
            if command == 0x0002:
                replies.append(0x810D)
        elif command == 0x000A and args.ack_records:
            label, payload_out = "record ack", b"\x01"
            frame = build(serial, password, 0x800A, payload_out)
            sock.sendto(frame, addr)
            sent[0x800A] += 1
            print(f"        -> cmd=0x800A {label}: {masked(frame)}")

        for reply in replies:
            label, payload_out = SAFE_COMMANDS[reply]
            frame = build(serial, password, reply, payload_out)
            sock.sendto(frame, addr)
            sent[reply] += 1
            print(f"        -> cmd=0x{reply:04X} {label}: {masked(frame)}")

    print("\nReceived:")
    for command, n in sorted(counts.items()):
        print(f"  0x{command:04X}  {n:4d}")
    if args.active:
        print("Sent:")
        for command, n in sorted(sent.items()):
            print(f"  0x{command:04X}  {n:4d}")
        if 0x010D in counts:
            print("\nThe charger answered the 0x810D query -> the password and "
                  "the outbound path are correct.")
        else:
            print("\nNo 0x010D answer. Either the password is wrong, or this "
                  "firmware does not answer that query.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
