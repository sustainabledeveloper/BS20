"""Bluetooth LE transport for Besen chargers.

The framing is identical to UDP; only the plumbing differs, since a frame runs
to 180 bytes and a Bluetooth write may carry as few as 20.

Used when Wi-Fi is unavailable, which after a power cut some units cannot
rejoin on their own.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .const import (
    BLE_CHARACTERISTIC_PAIRS,
    BLE_CONNECT_TIMEOUT,
    BLE_NAME_PREFIX,
)
from .protocol import FrameReassembler

_LOGGER = logging.getLogger(__name__)

def ble_name_for(serial: str) -> str:
    """Return the name a charger with this serial advertises.

    The fixed prefix plus the last two bytes of the serial, so serial
    ``1122334455667788`` advertises as ``ACP#EVSE7788``.
    """
    return f"ACP#EVSE{serial[-4:].upper()}"


def _short_uuid(uuid: str) -> str:
    """Return the 16 bit form of a Bluetooth base UUID, or the whole thing."""
    lowered = uuid.lower()
    if lowered.endswith("-0000-1000-8000-00805f9b34fb"):
        return lowered[4:8]
    return lowered


class BesenBleTransport:
    """Talks to one charger over Bluetooth LE."""

    def __init__(
        self,
        hass: HomeAssistant,
        serial: str,
        on_frame: Callable[[bytes], None],
        address: str | None = None,
    ) -> None:
        self.hass = hass
        self.serial = serial
        self.address = address
        self._on_frame = on_frame
        self._client: BleakClient | None = None
        self._write: BleakGATTCharacteristic | None = None
        self._frames = FrameReassembler()
        self._lock = asyncio.Lock()
        # Kept for diagnostics: without it a failing connection is invisible
        # unless someone is watching the log at the right moment.
        self.attempts = 0
        self.last_error: str | None = None
        self.last_rssi: int | None = None
        # Counted separately from decoded frames, so a notification that
        # arrives but does not parse is distinguishable from none arriving.
        self.notifications = 0
        self.bytes_received = 0
        self.frames_sent = 0
        self.last_write_error: str | None = None
        self.split_writes = 0
        self.write_uuid: str | None = None
        self.notify_uuid: str | None = None
        self.mtu: int | None = None

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    @property
    def name(self) -> str:
        return ble_name_for(self.serial)

    # --- discovery ----------------------------------------------------------

    def available(self) -> bool:
        """Whether Home Assistant has any usable Bluetooth."""
        try:
            scanners = bluetooth.async_scanner_count(self.hass, connectable=True)
        except RuntimeError:
            _LOGGER.error(
                "The Bluetooth fallback is switched on for %s, but Home Assistant "
                "has no Bluetooth set up. Add the Bluetooth integration (a local "
                "adapter, or an ESPHome Bluetooth proxy near the charger) or turn "
                "the option off again.",
                self.serial,
            )
            return False
        if not scanners:
            _LOGGER.error(
                "The Bluetooth fallback is switched on for %s, but no adapter or "
                "proxy is currently usable.",
                self.serial,
            )
            return False
        return True

    def find_device(self) -> bluetooth.BluetoothServiceInfoBleak | None:
        """Return this charger among the devices Home Assistant can see.

        A configured address wins; otherwise the advertised name is matched,
        which carries only the last two bytes of the serial. The first frame
        then confirms identity from the full serial.
        """
        wanted = self.name
        seen: list[str] = []
        by_name: bluetooth.BluetoothServiceInfoBleak | None = None
        try:
            discovered = list(bluetooth.async_discovered_service_info(self.hass, True))
        except RuntimeError:
            return None
        for info in discovered:
            name = (info.name or "").upper()
            if self.address and info.address.upper() == self.address.upper():
                return info
            if name.startswith(BLE_NAME_PREFIX):
                seen.append(f"{info.name} ({info.address})")
                if name == wanted and by_name is None:
                    by_name = info

        if by_name is not None:
            # A configured address that nothing answers to is worse than no
            # address at all: the charger is right there under its own name.
            if self.address:
                _LOGGER.info(
                    "Nothing at the configured address %s; using %s at %s, which "
                    "advertises this charger's name",
                    self.address,
                    by_name.name,
                    by_name.address,
                )
            return by_name

        _LOGGER.debug(
            "%d Bluetooth device(s) in range; none of them is %s",
            len(discovered),
            self.address or wanted,
        )
        self.last_error = "the charger is not visible to any Bluetooth adapter"
        if seen:
            _LOGGER.warning(
                "Did not find %s over Bluetooth. Chargers in range: %s. "
                "If one of these is it, set its address in the integration options.",
                self.address or wanted,
                ", ".join(seen),
            )
        else:
            _LOGGER.debug("No charger is visible to any Bluetooth adapter or proxy")
        return None

    # --- connection ---------------------------------------------------------

    async def async_connect(self) -> bool:
        """Connect and subscribe, returning whether the charger is reachable."""
        async with self._lock:
            if self.connected:
                return True
            if not self.available():
                return False
            info = self.find_device()
            if info is None:
                _LOGGER.debug(
                    "%s is not visible to any Bluetooth adapter or proxy", self.name
                )
                return False

            self.attempts += 1
            self.last_rssi = info.rssi
            _LOGGER.debug("Connecting to %s (%s), rssi %s", self.name, info.address, info.rssi)
            try:
                client = await establish_connection(
                    BleakClientWithServiceCache,
                    info.device,
                    self.name,
                    self._handle_disconnect,
                    timeout=BLE_CONNECT_TIMEOUT,
                )
            except Exception as err:  # noqa: BLE001 - bleak raises broadly
                self.last_error = f"{type(err).__name__}: {err}" if str(err) else type(err).__name__
                _LOGGER.warning(
                    "Could not connect to %s at rssi %s: %s",
                    self.name,
                    info.rssi,
                    self.last_error,
                )
                return False

            self.last_error = None
            write, notify = self._pick_characteristics(client)
            if write is None or notify is None:
                _LOGGER.error(
                    "%s exposes no usable write/notify pair; found services %s",
                    self.name,
                    [_short_uuid(s.uuid) for s in client.services],
                )
                await client.disconnect()
                return False

            try:
                await client.start_notify(notify, self._handle_notify)
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Could not subscribe to %s: %s", _short_uuid(notify.uuid), err)
                await client.disconnect()
                return False

            self._client = client
            self._write = write
            self._frames.reset()
            self.write_uuid = _short_uuid(write.uuid)
            self.notify_uuid = _short_uuid(notify.uuid)
            self.mtu = getattr(client, "mtu_size", None)
            # These modules can drop a write issued before their serial
            # bridge is ready.
            await asyncio.sleep(1.0)
            _LOGGER.info(
                "Connected to %s over Bluetooth; writing to %s, listening on %s",
                self.name,
                _short_uuid(write.uuid),
                _short_uuid(notify.uuid),
            )
            return True

    @staticmethod
    def _pick_characteristics(
        client: BleakClient,
    ) -> tuple[BleakGATTCharacteristic | None, BleakGATTCharacteristic | None]:
        """Choose the pair that carries the protocol.

        Tried in preference order and only as complete pairs: the stock GATT
        table holds several plausible write/notify pairs, one of which speaks
        the protocol.
        """
        writable: dict[str, BleakGATTCharacteristic] = {}
        notifiable: dict[str, BleakGATTCharacteristic] = {}
        for service in client.services:
            for char in service.characteristics:
                short = _short_uuid(char.uuid)
                if {"write", "write-without-response"} & set(char.properties):
                    writable.setdefault(short, char)
                if {"notify", "indicate"} & set(char.properties):
                    notifiable.setdefault(short, char)

        for write_uuid, notify_uuid in BLE_CHARACTERISTIC_PAIRS:
            if write_uuid in writable and notify_uuid in notifiable:
                return writable[write_uuid], notifiable[notify_uuid]

        _LOGGER.warning(
            "No known write/notify pair on this charger; falling back to the "
            "first usable one. Writable: %s. Notifying: %s.",
            sorted(writable),
            sorted(notifiable),
        )
        return (
            next(iter(writable.values()), None),
            next(iter(notifiable.values()), None),
        )

    def _handle_disconnect(self, _client: BleakClient) -> None:
        _LOGGER.info("Bluetooth link to %s dropped", self.name)
        self._client = None
        self._write = None
        self._frames.reset()

    async def async_disconnect(self) -> None:
        async with self._lock:
            client, self._client, self._write = self._client, None, None
            self._frames.reset()
        if client is not None:
            try:
                await client.disconnect()
            except Exception as err:  # noqa: BLE001 - nothing useful to do
                _LOGGER.debug("Error while disconnecting from %s: %s", self.name, err)

    # --- framing ------------------------------------------------------------

    def _handle_notify(self, _sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Hand every complete frame to the coordinator."""
        self.notifications += 1
        self.bytes_received += len(data)
        _LOGGER.debug("<- bluetooth %d bytes: %s", len(data), data.hex())
        for frame in self._frames.feed(bytes(data)):
            self._on_frame(frame)

    async def async_send(self, frame: bytes) -> bool:
        """Write one frame, whole if the link will take it.

        ``mtu_size`` is unreliable here and can report the 23 byte default on a
        link carrying far more, so the frame is written in one go first and
        split only if that fails.
        """
        client, write = self._client, self._write
        if client is None or write is None or not client.is_connected:
            return False

        self.mtu = getattr(client, "mtu_size", None)
        # write-with-response gives flow control; use it when offered.
        response = "write" in write.properties
        _LOGGER.debug(
            "-> bluetooth %d bytes on %s (reported mtu %s): %s",
            len(frame),
            self.write_uuid,
            self.mtu,
            frame.hex(),
        )
        try:
            await client.write_gatt_char(write, frame, response=response)
        except Exception as whole_err:  # noqa: BLE001 - bleak raises broadly
            _LOGGER.debug(
                "Whole-frame write to %s failed (%s); splitting it",
                self.name,
                whole_err,
            )
            if not await self._send_split(client, write, frame, response):
                return False
            self.split_writes += 1

        self.last_write_error = None
        self.frames_sent += 1
        return True

    async def _send_split(
        self,
        client: BleakClient,
        write: BleakGATTCharacteristic,
        frame: bytes,
        response: bool,
    ) -> bool:
        """Write a frame in MTU sized pieces, paced so none are dropped."""
        chunk = max(20, (self.mtu or 23) - 3)
        try:
            for offset in range(0, len(frame), chunk):
                await client.write_gatt_char(
                    write, frame[offset : offset + chunk], response=response
                )
                if not response:
                    # Unacknowledged writes; pace them.
                    await asyncio.sleep(0.02)
        except Exception as err:  # noqa: BLE001
            self.last_write_error = f"{type(err).__name__}: {err}"
            _LOGGER.warning("Bluetooth write to %s failed: %s", self.name, err)
            await self.async_disconnect()
            return False
        return True
