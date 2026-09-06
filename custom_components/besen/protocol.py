"""Wire protocol for Besen / EVSEMaster wall chargers.

The charger broadcasts UDP datagrams to port 28376.  Every frame looks like::

    0      1      2 3      4      5..12     13..18     19 20     21..n-5   n-4 n-3  n-2 n-1
    0x06   0x01   length   0x00   serial    password   command   payload   checksum  0x0F 0x02

``length`` is the total frame length, big endian.  ``checksum`` is the plain
sum of every byte before it, modulo 65536, big endian.  In device -> app frames
the password field is filled with ``0xFF``; only app -> device frames carry the
real password.

Every function here is pure so it can be exercised without Home Assistant.
"""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass, field
from typing import Any

from .const import (
    CHARGER_STATES,
    DEFAULT_LISTEN_PORT,
    SUBOP_SET,
    WIFI_PASSWORD_SLICE,
    WIFI_PAYLOAD_LEN,
    WIFI_SERVER_IP_SLICE,
    WIFI_SERVER_PORT_SLICE,
    WIFI_SSID_SLICE,
    FRAME_HEADER_LEN,
    FRAME_MAGIC,
    FRAME_MIN_LEN,
    FRAME_TAIL,
    FRAME_TRAILER_LEN,
    LIMIT_UNLIMITED,
    PASSWORD_LEN,
    PLUG_STATES,
    SENTINEL_16,
    SENTINEL_8,
    SERIAL_LEN,
    STATE_CODE_CHARGING,
    STATE_UNKNOWN,
    STATE_WAITING_FOR_EV,
    TEMPERATURE_OFFSET,
    TEMPERATURE_SCALE,
)

_LOGGER = logging.getLogger(__name__)


class ProtocolError(ValueError):
    """Raised when a serial number or password cannot be put on the wire."""


# --- helpers ----------------------------------------------------------------


def normalise_serial(serial: str) -> str:
    """Return *serial* as a lower-case 16 character hex string.

    Raises:
        ProtocolError: if it is not 16 hex digits.
    """
    cleaned = serial.strip().replace(" ", "").replace("-", "").lower()
    if len(cleaned) != SERIAL_LEN * 2:
        raise ProtocolError(
            f"serial must be {SERIAL_LEN * 2} hex digits, got {len(cleaned)}"
        )
    try:
        bytes.fromhex(cleaned)
    except ValueError as err:
        raise ProtocolError("serial must contain hex digits only") from err
    return cleaned


def encode_password(password: str) -> bytes:
    """Return *password* as exactly six ASCII bytes.

    The field is fixed width; a longer value is refused rather than truncated.
    """
    try:
        raw = password.encode("ascii")
    except UnicodeEncodeError as err:
        raise ProtocolError("password must be ASCII") from err
    if len(raw) != PASSWORD_LEN:
        raise ProtocolError(
            f"password must be exactly {PASSWORD_LEN} characters, got {len(raw)}"
        )
    return raw


def checksum(frame_without_trailer: bytes) -> int:
    """Return the 16 bit additive checksum used by the protocol."""
    return sum(frame_without_trailer) & 0xFFFF


def build_frame(serial: str, password: str, command: int, payload: bytes = b"") -> bytes:
    """Assemble one frame ready to be sent to the charger."""
    serial_bytes = bytes.fromhex(normalise_serial(serial))
    password_bytes = encode_password(password)

    length = FRAME_MIN_LEN + len(payload)
    frame = bytearray(length)
    frame[0:2] = FRAME_MAGIC
    frame[2] = (length >> 8) & 0xFF
    frame[3] = length & 0xFF
    frame[4] = 0x00
    frame[5:13] = serial_bytes
    frame[13:19] = password_bytes
    frame[19] = (command >> 8) & 0xFF
    frame[20] = command & 0xFF
    frame[FRAME_HEADER_LEN : FRAME_HEADER_LEN + len(payload)] = payload

    crc = checksum(frame[: length - FRAME_TRAILER_LEN])
    frame[length - 4] = (crc >> 8) & 0xFF
    frame[length - 3] = crc & 0xFF
    frame[length - 2 : length] = FRAME_TAIL
    return bytes(frame)


@dataclass(slots=True)
class Frame:
    """A validated inbound frame."""

    serial: str
    command: int
    payload: bytes
    raw: bytes = field(repr=False)


def parse_frame(data: bytes) -> Frame | None:
    """Validate and split *data*, or return ``None`` if it is not ours.

    The socket listens on a broadcast port, so unrelated traffic is expected
    and is dropped rather than raised on.
    """
    if len(data) < FRAME_MIN_LEN:
        return None
    if data[0:2] != FRAME_MAGIC:
        return None
    if data[-2:] != FRAME_TAIL:
        return None

    declared = (data[2] << 8) | data[3]
    if declared != len(data):
        _LOGGER.debug(
            "Frame length mismatch: header says %d, datagram is %d bytes",
            declared,
            len(data),
        )
        return None

    expected = checksum(data[: len(data) - FRAME_TRAILER_LEN])
    received = (data[len(data) - 4] << 8) | data[len(data) - 3]
    if expected != received:
        _LOGGER.debug(
            "Frame checksum mismatch: computed 0x%04X, received 0x%04X",
            expected,
            received,
        )
        return None

    return Frame(
        serial=data[5:13].hex(),
        command=(data[19] << 8) | data[20],
        payload=data[FRAME_HEADER_LEN : len(data) - FRAME_TRAILER_LEN],
        raw=data,
    )


# --- field decoders ---------------------------------------------------------


def _u16(payload: bytes, offset: int) -> int | None:
    if len(payload) < offset + 2:
        return None
    return int.from_bytes(payload[offset : offset + 2], "big")


def _u32(payload: bytes, offset: int) -> int | None:
    if len(payload) < offset + 4:
        return None
    return int.from_bytes(payload[offset : offset + 4], "big")


def _u8(payload: bytes, offset: int) -> int | None:
    if len(payload) <= offset:
        return None
    return payload[offset]


def _text(payload: bytes, start: int, end: int) -> str | None:
    if len(payload) < end:
        return None
    return payload[start:end].decode("ascii", errors="replace").strip("\x00 ") or None


def _scaled(raw: int | None, factor: float, digits: int = 2) -> float | None:
    if raw is None:
        return None
    return round(raw * factor, digits)


def _temperature(raw: int | None) -> float | None:
    """Convert a raw temperature field. ``0xFFFF`` means no sensor."""
    if raw is None or raw in (SENTINEL_16, SENTINEL_8):
        return None
    return round((raw - TEMPERATURE_OFFSET) * TEMPERATURE_SCALE, 2)


def _limit(raw: int | None) -> int | None:
    """Return a session limit, or ``None`` when it means "unlimited"."""
    if raw is None or raw == LIMIT_UNLIMITED:
        return None
    return raw


def _epoch(raw: int | None) -> int | None:
    """Return a raw device timestamp, or ``None`` when unset.

    Not a UTC epoch; see ``DEVICE_TZ_OFFSET``. Conversion needs Home
    Assistant's timezone and lives in the coordinator.
    """
    if not raw:
        return None
    return raw


# --- payload parsers --------------------------------------------------------


def parse_ac_status(payload: bytes) -> dict[str, Any]:
    """Decode the AC measurement payload (commands 0x0004 / 0x000D).

    The frame is 40 bytes on current firmware; every read is length guarded so
    other payload sizes degrade to ``None``.
    """
    data: dict[str, Any] = {}

    data["line_id"] = _u8(payload, 0)
    data["voltage_l1"] = _scaled(_u16(payload, 1), 0.1, 1)
    data["current_l1"] = _scaled(_u16(payload, 3), 0.01)
    data["power_reported"] = _u32(payload, 5)
    data["energy_total"] = _scaled(_u32(payload, 9), 0.01)
    data["temperature_inner"] = _temperature(_u16(payload, 13))
    data["temperature_outer"] = _temperature(_u16(payload, 15))

    emergency = _u8(payload, 17)
    data["emergency_stop_raw"] = emergency
    data["emergency_stop"] = None if emergency is None else emergency != 1

    plug_raw = _u8(payload, 18)
    data["plug_state_raw"] = plug_raw
    data["plug_state"] = PLUG_STATES.get(plug_raw, STATE_UNKNOWN) if plug_raw is not None else None

    output_raw = _u8(payload, 19)
    data["output_state_raw"] = output_raw
    data["output_active"] = None if output_raw is None else output_raw != 1

    data["voltage_l2"] = _scaled(_u16(payload, 25), 0.1, 1)
    data["current_l2"] = _scaled(_u16(payload, 27), 0.01)
    data["voltage_l3"] = _scaled(_u16(payload, 29), 0.1, 1)
    data["current_l3"] = _scaled(_u16(payload, 31), 0.01)

    data["phase_count_raw"] = _u8(payload, 33)

    # The reported power field covers one phase, so it reads a third of the
    # truth on a three phase charger. Summing the phases is right on both.
    phases = [
        (data.get(f"voltage_l{n}"), data.get(f"current_l{n}")) for n in (1, 2, 3)
    ]
    measured = [v * i for v, i in phases if v and i]
    if measured:
        data["power"] = round(sum(measured))
    elif any(v for v, _ in phases):
        data["power"] = 0
    else:
        data["power"] = data["power_reported"]

    # Byte 20 holds the state code. Byte 34 is a secondary code some firmwares
    # populate and others leave at 0xFF.
    primary = _u8(payload, 20)
    secondary = _u8(payload, 34)
    data["state_code_primary"] = primary
    data["state_code_secondary"] = secondary
    state_raw = secondary if secondary not in (None, SENTINEL_8) else primary
    data["state_code"] = state_raw

    state = CHARGER_STATES.get(state_raw, STATE_UNKNOWN) if state_raw is not None else None
    if state_raw == STATE_CODE_CHARGING and plug_raw != 4:
        state = STATE_WAITING_FOR_EV
    data["state"] = state

    if len(payload) > 21:
        data["unknown_21_24"] = payload[21:25].hex()
    if len(payload) > 35:
        data["unknown_tail_ac"] = payload[35:].hex()
    return data


def parse_charge_status(payload: bytes) -> dict[str, Any]:
    """Decode the session payload (commands 0x0005 / 0x0006)."""
    data: dict[str, Any] = {}

    data["port"] = _u8(payload, 0)
    data["session_state_code"] = _u8(payload, 1)
    data["session_id"] = _text(payload, 2, 18)
    data["start_type_raw"] = _u8(payload, 18)
    data["charge_type_raw"] = _u8(payload, 19)

    data["limit_duration"] = _limit(_u16(payload, 20))
    data["limit_energy"] = _limit(_u16(payload, 22))
    data["limit_cost"] = _limit(_u16(payload, 24))

    data["reservation_time"] = _epoch(_u32(payload, 26))
    data["session_user"] = _text(payload, 30, 46)
    data["session_max_current"] = _u8(payload, 46)
    data["session_start"] = _epoch(_u32(payload, 47))
    data["session_duration"] = _u32(payload, 51)
    data["energy_at_session_start"] = _scaled(_u32(payload, 55), 0.01)
    data["energy_total_at_session"] = _scaled(_u32(payload, 59), 0.01)
    data["session_energy"] = _scaled(_u32(payload, 63), 0.01)

    # The price and fee fields are little endian in this payload.
    if len(payload) >= 71:
        data["price"] = round(
            int.from_bytes(payload[67:71], "little") * 0.01, 2
        )
    data["fee_type_raw"] = _u8(payload, 71)
    if len(payload) >= 74:
        data["session_cost"] = round(
            int.from_bytes(payload[72:74], "little") * 0.01, 2
        )
    if len(payload) > 74:
        data["unknown_tail_session"] = payload[74:].hex()
    return data


def parse_charge_record(payload: bytes) -> dict[str, Any]:
    """Decode an uploaded charging record (command 0x000A).

    ``meter_end - meter_start == energy`` and ``end - start == duration``.
    """
    data: dict[str, Any] = {}

    data["port"] = _u8(payload, 0)
    data["start_reason"] = _text(payload, 1, 17)
    data["stop_reason"] = _text(payload, 17, 33)
    data["record_id"] = _text(payload, 33, 49)

    data["start"] = _epoch(_u32(payload, 64))
    data["end"] = _epoch(_u32(payload, 68))
    data["duration"] = _u32(payload, 72)
    data["meter_start"] = _scaled(_u32(payload, 76), 0.01)
    data["meter_end"] = _scaled(_u32(payload, 80), 0.01)
    data["energy"] = _scaled(_u32(payload, 84), 0.01)
    data["cost"] = _scaled(_u32(payload, 88), 0.01)

    # Trailing array of 16 bit little endian samples, unit unknown.
    if len(payload) > 96:
        tail = payload[96:]
        data["samples"] = [
            int.from_bytes(tail[i : i + 2], "little")
            for i in range(0, len(tail) - 1, 2)
        ]
    return data


def parse_login(payload: bytes) -> dict[str, Any]:
    """Decode the device description sent with commands 0x0001 / 0x0002.

    Every multi-byte field here is big endian, including the rated power.
    """
    return {
        "device_type": _u8(payload, 0),
        "brand": _text(payload, 1, 17),
        "model": _text(payload, 17, 33),
        "hardware_version": _text(payload, 33, 49),
        "rated_power": _u32(payload, 49),
        "rated_current": _u8(payload, 53),
        "hotline": _text(payload, 54, 70),
    }


def parse_system_time(payload: bytes) -> dict[str, Any]:
    """Decode the charger's clock (command 0x0101), payload ``subop + u32``."""
    if len(payload) < 5:
        return {}
    return {"charger_clock": int.from_bytes(payload[1:5], "big")}


def parse_version(payload: bytes) -> dict[str, Any]:
    """Decode the version answer (command 0x0106).

    Two 16 character strings, the running and the stored image, then a
    checksum and a type byte.
    """
    if len(payload) < 32:
        return {}
    return {
        "firmware_version": payload[0:16].decode("ascii", "replace").strip("\x00 "),
        "firmware_backup_version": payload[16:32].decode("ascii", "replace").strip("\x00 "),
    }


def parse_temperature_unit(payload: bytes) -> dict[str, Any]:
    """Decode the display unit (command 0x0112): 1 is Celsius, 2 is Fahrenheit."""
    if len(payload) < 2:
        return {}
    return {"temperature_unit_raw": payload[1]}


#: One weekly plan slot, as carried by command 0x010E.
WEEKLY_SLOT_LEN = 9


def parse_weekly_plan(payload: bytes) -> dict[str, Any]:
    """Decode the repeating weekly plan (command 0x010E).

    A sub-operation byte followed by seven nine byte slots, one per weekday::

        flag(1) hour(1) minute(1) duration_minutes(2) limit(4)

    Flag 1 is off and 3 is on. ``0xFFFF`` in the duration means no limit.
    """
    body = payload[1:]
    slots = [
        body[i : i + WEEKLY_SLOT_LEN]
        for i in range(0, len(body) - WEEKLY_SLOT_LEN + 1, WEEKLY_SLOT_LEN)
    ]
    if not slots:
        return {}
    plan = []
    for slot in slots:
        duration = int.from_bytes(slot[3:5], "big")
        plan.append(
            {
                # Only 1 (off) and 3 (on) have been observed; bit 1 is the
                # enable bit in both.
                "enabled": bool(slot[0] & 0x02),
                "flag": slot[0],
                "hour": slot[1],
                "minute": slot[2],
                "duration_minutes": None if duration == SENTINEL_16 else duration,
                "limit": slot[5:9].hex(),
            }
        )
    return {
        "weekly_plan": plan,
        "weekly_plan_active": any(entry["enabled"] for entry in plan),
    }


def parse_monitoring(payload: bytes) -> dict[str, Any]:
    """Store the answer to command 0x0162 verbatim.

    Format is ``0x03`` then two slowly changing bytes and padding. Meaning
    unknown, so the payload is passed through rather than interpreted.
    """
    return {"monitoring_raw": payload.hex()}


def parse_wifi_info(payload: bytes) -> dict[str, Any]:
    """Decode the Wi-Fi configuration (command 0x010A).

    The passphrase at offset 33 is not returned; it would otherwise reach the
    state machine, the recorder and diagnostics downloads.
    """
    if len(payload) < WIFI_PAYLOAD_LEN:
        return {}
    ssid = payload[WIFI_SSID_SLICE].decode("utf-8", "replace").rstrip("\x00")
    return {
        "wifi_ssid": ssid or None,
        "wifi_server_ip": str(ipaddress.IPv4Address(payload[WIFI_SERVER_IP_SLICE])),
        "wifi_server_port": int.from_bytes(payload[WIFI_SERVER_PORT_SLICE], "big"),
    }


def build_wifi_payload(
    ssid: str,
    password: str,
    server_ip: str = "0.0.0.0",
    server_port: int = DEFAULT_LISTEN_PORT,
) -> bytes:
    """Build the payload that points the charger at a Wi-Fi network.

    Raises:
        ProtocolError: if either credential exceeds its fixed field.
    """
    ssid_bytes = ssid.encode("utf-8")
    password_bytes = password.encode("utf-8")
    ssid_len = WIFI_SSID_SLICE.stop - WIFI_SSID_SLICE.start
    password_len = WIFI_PASSWORD_SLICE.stop - WIFI_PASSWORD_SLICE.start
    if not ssid_bytes or len(ssid_bytes) > ssid_len:
        raise ProtocolError(f"network name must be 1-{ssid_len} bytes")
    if len(password_bytes) > password_len:
        raise ProtocolError(f"network password must be at most {password_len} bytes")

    payload = bytearray(WIFI_PAYLOAD_LEN)
    payload[0] = SUBOP_SET
    payload[WIFI_SSID_SLICE.start : WIFI_SSID_SLICE.start + len(ssid_bytes)] = ssid_bytes
    payload[
        WIFI_PASSWORD_SLICE.start : WIFI_PASSWORD_SLICE.start + len(password_bytes)
    ] = password_bytes
    payload[WIFI_SERVER_IP_SLICE] = ipaddress.IPv4Address(server_ip).packed
    payload[WIFI_SERVER_PORT_SLICE] = int(server_port).to_bytes(2, "big")
    return bytes(payload)


def parse_button_state(payload: bytes) -> dict[str, Any]:
    """Decode the "start by physical button" state (command 0x010D)."""
    if len(payload) < 2:
        return {}
    state = payload[1]
    if state not in (0, 1):
        _LOGGER.debug("Unexpected button state byte 0x%02X", state)
        return {}
    return {"button_start_enabled": state == 0}


class FrameReassembler:
    """Collects whole frames out of a stream of Bluetooth notifications.

    Frames run to 180 bytes and a notification carries as little as 20, so a
    frame spans several callbacks and one notification can hold the tail of one
    frame and the head of the next. Boundaries come from the declared length in
    bytes 2 and 3.
    """

    #: Upper bound used to reject a bogus length field.
    MAX_FRAME_LEN = 512

    def __init__(self) -> None:
        self._buffer = bytearray()

    def reset(self) -> None:
        self._buffer.clear()

    def feed(self, data: bytes) -> list[bytes]:
        """Add received bytes and return whatever frames are now complete."""
        self._buffer += data
        frames: list[bytes] = []
        while True:
            start = self._buffer.find(FRAME_MAGIC)
            if start < 0:
                # Keep a trailing 0x06: it may be the first half of the magic.
                tail = self._buffer[-1:] == FRAME_MAGIC[:1]
                self._buffer = bytearray(self._buffer[-1:]) if tail else bytearray()
                return frames
            if start:
                del self._buffer[:start]
            if len(self._buffer) < 4:
                return frames
            length = (self._buffer[2] << 8) | self._buffer[3]
            if not FRAME_MIN_LEN <= length <= self.MAX_FRAME_LEN:
                # Not a header after all; skip this magic and keep looking.
                del self._buffer[:2]
                continue
            if len(self._buffer) < length:
                return frames
            frames.append(bytes(self._buffer[:length]))
            del self._buffer[:length]


# --- payload builders -------------------------------------------------------


def build_start_charge_payload(
    user_id: str,
    charge_id: str,
    start_at: int,
    max_current: int,
    limit_duration: int = LIMIT_UNLIMITED,
    limit_energy: int = LIMIT_UNLIMITED,
    limit_cost: int = LIMIT_UNLIMITED,
) -> bytes:
    """Build the 47 byte payload for command 0x8007."""
    payload = bytearray(47)
    payload[0] = 1
    payload[1:17] = user_id.encode("ascii", "replace").ljust(16)[:16]
    payload[17:33] = charge_id.encode("ascii", "replace").ljust(16)[:16]
    payload[33] = 0
    payload[34:38] = int(start_at).to_bytes(4, "big")
    payload[38] = 1
    payload[39] = 1
    payload[40:42] = int(limit_duration).to_bytes(2, "big")
    payload[42:44] = int(limit_energy).to_bytes(2, "big")
    payload[44:46] = int(limit_cost).to_bytes(2, "big")
    payload[46] = max(1, min(255, int(max_current)))
    return bytes(payload)


def build_stop_charge_payload(user_id: str) -> bytes:
    """Build the 47 byte payload for command 0x8008."""
    payload = bytearray(47)
    payload[0] = 1
    payload[1:17] = user_id.encode("ascii", "replace").ljust(16)[:16]
    return bytes(payload)
