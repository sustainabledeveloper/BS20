#!/usr/bin/env python3
"""Discover a charger's Bluetooth LE interface.

Scans, reads the GATT table and listens on any notifying characteristic.
Nothing is ever written to the charger::

    pip install bleak
    python3 tools/besen_ble_probe.py                 # scan only
    python3 tools/besen_ble_probe.py --connect       # scan, then enumerate
    python3 tools/besen_ble_probe.py --why           # is it connectable?

macOS asks for Bluetooth permission on first use, so run it from a terminal
where the prompt can be answered. Linux needs no special permission.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    print("This needs bleak:  pip install bleak", file=sys.stderr)
    raise SystemExit(1)

#: Advertising name prefix used by these chargers.
NAME_PREFIXES = ("ACP#", "EVSE", "BS20")

#: Service UUIDs used by the modules in this family.
INTERESTING = ("0000fff0", "0000fff1", "0000ffe0", "0000ffe5", "0003cdd0")


async def explain_advertisement(seconds: float, prefix: str) -> int:
    """Report whether the charger advertises as connectable (macOS only).

    A non-connectable peripheral times out every connection attempt regardless
    of signal. bleak does not surface the flag, so the raw CoreBluetooth
    advertisement dictionary is read directly.
    """
    if sys.platform != "darwin":
        print("This check is macOS specific; on Linux use `btmon` while scanning.")
        return 2
    try:
        import objc
        from CoreBluetooth import CBCentralManager
        from Foundation import NSDate, NSObject, NSRunLoop
    except ImportError:
        print("Needs pyobjc:  pip install pyobjc-framework-CoreBluetooth", file=sys.stderr)
        return 2

    seen: dict[str, dict] = {}

    class Delegate(NSObject):
        def centralManagerDidUpdateState_(self, central):
            if central.state() == 5:  # CBManagerStatePoweredOn
                central.scanForPeripheralsWithServices_options_(None, None)
            else:
                print(f"Bluetooth is not powered on (state {central.state()}).")

        def centralManager_didDiscoverPeripheral_advertisementData_RSSI_(
            self, central, peripheral, data, rssi
        ):
            name = data.get("kCBAdvDataLocalName") or peripheral.name()
            if not name or not str(name).startswith(prefix):
                return
            seen[str(name)] = {str(k): data[k] for k in data}
            seen[str(name)]["_rssi"] = int(rssi)

    delegate = Delegate.alloc().init()
    manager = CBCentralManager.alloc().initWithDelegate_queue_(delegate, None)
    print(f"Reading raw advertisements for {seconds:g}s, looking for {prefix!r}...\n")
    NSRunLoop.currentRunLoop().runUntilDate_(
        NSDate.dateWithTimeIntervalSinceNow_(seconds)
    )
    manager.stopScan()

    if not seen:
        print(f"No advertisement from a device named {prefix}*.")
        return 1
    for name, data in seen.items():
        connectable = data.get("kCBAdvDataIsConnectable")
        print(f"{name}  rssi={data.get('_rssi')}")
        for key in sorted(data):
            if key == "_rssi":
                continue
            print(f"    {key} = {data[key]}")
        print()
        if connectable is None:
            print("  The connectable flag is absent, which macOS reports for")
            print("  non-connectable advertisements.")
        elif int(connectable) == 0:
            print("  NOT CONNECTABLE: the charger is broadcasting only. Every")
            print("  connection attempt will time out until it starts accepting")
            print("  connections -- on these units, typically when it is off Wi-Fi.")
        else:
            print("  Connectable. A timeout then points at pairing or at the")
            print("  phone app holding the link; close the app and retry.")
    return 0


def looks_like_charger(name: str | None, uuids: list[str]) -> bool:
    if name and name.upper().startswith(NAME_PREFIXES):
        return True
    return any(u.lower().startswith(INTERESTING) for u in uuids)


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seconds", type=float, default=15.0)
    ap.add_argument("--connect", action="store_true",
                    help="connect to the best candidate and list its GATT table")
    ap.add_argument("--address", help="connect to this address instead of guessing")
    ap.add_argument("--listen", type=float, default=30.0,
                    help="seconds to listen for notifications after connecting")
    ap.add_argument("--connect-timeout", type=float, default=30.0)
    ap.add_argument("--attempts", type=int, default=4)
    ap.add_argument("--why", action="store_true",
                    help="explain why connecting fails: read the raw advertisement "
                         "and report whether the charger accepts connections at all")
    ap.add_argument("--prefix", default="ACP#",
                    help="advertised name prefix to look for (default ACP#)")
    args = ap.parse_args()

    if args.why:
        return await explain_advertisement(args.seconds, args.prefix)

    print(f"Scanning for {args.seconds:g}s...\n")
    devices = await BleakScanner.discover(timeout=args.seconds, return_adv=True)

    candidates = []
    for address, (device, adv) in sorted(
        devices.items(), key=lambda kv: -(kv[1][1].rssi or -999)
    ):
        name = adv.local_name or device.name
        uuids = list(adv.service_uuids or [])
        hit = looks_like_charger(name, uuids)
        if hit:
            candidates.append((address, name, device, adv.rssi))
        print(f"  {address}  rssi={adv.rssi:>4}  name={name!r}")
        if uuids:
            print(f"       services: {', '.join(uuids)}")
        if adv.manufacturer_data:
            for company, payload in adv.manufacturer_data.items():
                print(f"       manufacturer 0x{company:04X}: {payload.hex()}")
        if hit:
            print("       ^^^ looks like the charger")
            if (adv.rssi or -999) < -80:
                print("       !!! signal is very weak; move closer before connecting")

    print(f"\n{len(devices)} device(s), {len(candidates)} candidate(s)")
    if not args.connect and not args.address:
        print("\nRe-run with --connect to read the GATT table.")
        return 0

    target = None
    if args.address:
        target = args.address
    elif candidates:
        address, name, device, rssi = candidates[0]
        target = device            # connecting from the scan result is more reliable
        print(f"\nTarget: {name} at {address}, rssi {rssi}")
        if (rssi or -999) < -80:
            print("Signal is weak. If the connection times out, move the computer")
            print("closer to the charger and run this again.")
    if target is None:
        print("\nNo candidate found. If you know the charger's address, pass --address.")
        return 1

    client = None
    for attempt in range(1, args.attempts + 1):
        print(f"\nConnecting (attempt {attempt}/{args.attempts}, "
              f"{args.connect_timeout:g}s timeout)...")
        try:
            client = BleakClient(target, timeout=args.connect_timeout)
            await client.connect()
            break
        except Exception as err:  # noqa: BLE001 - report and retry
            print(f"  failed: {type(err).__name__}: {err}")
            client = None
            await asyncio.sleep(2)
    if client is None:
        print("\nCould not connect. Most likely causes, in order:")
        print("  1. too far away -- BLE needs a few metres, walls cost a lot")
        print("  2. the EVSEMaster app is connected and holding the link")
        print("  3. the charger only accepts Bluetooth while it is not on Wi-Fi")
        return 1

    try:
        print(f"connected: {client.is_connected}\n")
        notifiable = []
        for service in client.services:
            print(f"service {service.uuid}  ({service.description})")
            for char in service.characteristics:
                props = ",".join(char.properties)
                print(f"    char {char.uuid}  [{props}]")
                if "notify" in char.properties or "indicate" in char.properties:
                    notifiable.append(char.uuid)
                if "read" in char.properties:
                    try:
                        value = await client.read_gatt_char(char)
                        print(f"         value: {value.hex()}  {value[:24]!r}")
                    except Exception as err:  # noqa: BLE001 - informational only
                        print(f"         read failed: {err}")
                for descriptor in char.descriptors:
                    print(f"         descriptor {descriptor.uuid}")

        if not notifiable:
            print("\nNo notifying characteristic; the charger may only answer after a write.")
            return 0

        print(f"\nListening {args.listen:g}s on {len(notifiable)} characteristic(s).")
        print("Frames should start 06 01 and end 0f 02, like the UDP ones.\n")
        seen = 0

        def on_notify(sender, data: bytearray) -> None:
            nonlocal seen
            seen += 1
            marker = "  <== Besen frame" if data[:2] == b"\x06\x01" else ""
            print(f"  {sender.uuid} [{len(data):3d}] {data.hex()}{marker}")

        for uuid in notifiable:
            try:
                await client.start_notify(uuid, on_notify)
            except Exception as err:  # noqa: BLE001
                print(f"  could not subscribe to {uuid}: {err}")
        await asyncio.sleep(args.listen)
        print(f"\n{seen} notification(s) received.")
    finally:
        await client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
