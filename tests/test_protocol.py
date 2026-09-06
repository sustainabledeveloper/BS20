"""Protocol tests.

Run without Home Assistant::

    python3 -m pytest tests/

Fixtures are frames captured from a three phase BS20 with no vehicle connected.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components"))

from besen import protocol as proto  # noqa: E402
from besen.const import (  # noqa: E402
    CMD_AC_STATUS,
    DEVICE_TZ_OFFSET,
    CMD_CHARGE_RECORD,
    CMD_CHARGE_STATUS,
    CMD_HEARTBEAT,
    RESPONSE_FLAG,
)

SERIAL = "1122334455667788"
PASSWORD = "123456"

HEARTBEAT = bytes.fromhex(
    "06010019001122334455667788ffffffffffff000308810f02"
)
AC_STATUS = bytes.fromhex(
    "06010041001122334455667788ffffffffffff0004010941000000000000000267f45aba5aba"
    "0101020c00000000091200000902000003ff00000000000db20f02"
)
CHARGE_STATUS = bytes.fromhex(
    "06010069001122334455667788ffffffffffff0005010c3230323630393032313834353131"
    "33300101ffffffffffff6a9852924b657920202020202020202020202020206a97fd240000"
    "bbec00000000000267f40000161200000000010000ff00000000001d250f02"
)
CHARGE_RECORD = bytes.fromhex(
    "060100b4001122334455667788ffffffffffff000a014b6579202020202020202020202020"
    "20506f77657220446f776e2020202020204b6579202020313738313737373130310005010b"
    "40ffffffffff02000000006a33c2cd6a3483040000c03700014a9800015cd70000123f0000"
    "000001000000291a9a1a861a721a9a1a7c1ad61aa41a7c1aa41a541acc1aea1b1c1af41af4"
    "1b081b3a1b4e1b6c1b580000000000000000000000000000000000002cdd0f02"
)


# --- framing ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "command"),
    [
        (HEARTBEAT, CMD_HEARTBEAT),
        (AC_STATUS, CMD_AC_STATUS),
        (CHARGE_STATUS, CMD_CHARGE_STATUS),
        (CHARGE_RECORD, CMD_CHARGE_RECORD),
    ],
)
def test_parses_live_frames(raw: bytes, command: int) -> None:
    frame = proto.parse_frame(raw)
    assert frame is not None
    assert frame.serial == SERIAL
    assert frame.command == command


def test_rejects_bad_checksum() -> None:
    corrupted = bytearray(AC_STATUS)
    corrupted[25] ^= 0xFF
    assert proto.parse_frame(bytes(corrupted)) is None


def test_rejects_wrong_declared_length() -> None:
    corrupted = bytearray(AC_STATUS)
    corrupted[3] = 0x40  # claim one byte less than we hold
    assert proto.parse_frame(bytes(corrupted)) is None


@pytest.mark.parametrize("cut", [0, 10, 24])
def test_rejects_short_frames(cut: int) -> None:
    assert proto.parse_frame(AC_STATUS[:cut]) is None


def test_rejects_foreign_traffic() -> None:
    assert proto.parse_frame(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n" + b"\x00" * 20) is None


def test_build_round_trip() -> None:
    raw = proto.build_frame(SERIAL, PASSWORD, RESPONSE_FLAG | CMD_HEARTBEAT)
    frame = proto.parse_frame(raw)
    assert frame is not None
    assert frame.command == 0x8003
    assert frame.serial == SERIAL
    assert raw[13:19] == PASSWORD.encode()


def test_checksum_matches_the_charger() -> None:
    """The charger's own checksum must validate under our implementation."""
    assert proto.checksum(HEARTBEAT[:-4]) == int.from_bytes(HEARTBEAT[-4:-2], "big")


# --- credentials -----------------------------------------------------------


@pytest.mark.parametrize(
    "serial", ["", "abc", "1122334455667788aa", "zz22334455667788"]
)
def test_rejects_invalid_serial(serial: str) -> None:
    with pytest.raises(proto.ProtocolError):
        proto.normalise_serial(serial)


def test_normalises_serial_case_and_separators() -> None:
    assert proto.normalise_serial("11-22-33-44-55-66-77-88") == SERIAL
    assert proto.normalise_serial(SERIAL.upper()) == SERIAL


@pytest.mark.parametrize("password", ["", "12345", "1234567", "é23456"])
def test_rejects_invalid_password(password: str) -> None:
    """A wrong length password would corrupt the command bytes."""
    with pytest.raises(proto.ProtocolError):
        proto.encode_password(password)


# --- payload decoding ------------------------------------------------------


def test_ac_status_values() -> None:
    data = proto.parse_ac_status(proto.parse_frame(AC_STATUS).payload)
    assert data["voltage_l1"] == 236.9
    assert data["voltage_l2"] == 232.2
    assert data["voltage_l3"] == 230.6
    assert data["current_l1"] == data["current_l2"] == data["current_l3"] == 0.0
    assert data["power"] == 0
    assert data["energy_total"] == 1576.84
    assert data["temperature_inner"] == 32.26
    assert data["temperature_outer"] == 32.26
    assert data["plug_state"] == "not_connected"
    assert data["emergency_stop"] is False


def test_ac_status_prefers_the_primary_state_byte() -> None:
    """Byte 34 is 0xFF on this firmware, so byte 20 holds the state."""
    data = proto.parse_ac_status(proto.parse_frame(AC_STATUS).payload)
    assert data["state_code_secondary"] == 0xFF
    assert data["state_code"] == 12
    assert data["state"] == "plug_not_connected"


def test_temperature_sentinel_is_16_bit() -> None:
    assert proto._temperature(0xFFFF) is None
    assert proto._temperature(0x5ABA) == 32.26


def test_charge_status_values() -> None:
    data = proto.parse_charge_status(proto.parse_frame(CHARGE_STATUS).payload)
    assert data["session_id"] == "2026090218451130"
    assert data["session_user"] == "Key"
    assert data["session_max_current"] == 32
    assert data["session_duration"] == 48108
    assert data["session_energy"] == 56.5
    assert data["energy_total_at_session"] == 1576.84
    # 0xFFFF means "no limit"
    assert data["limit_duration"] is None
    assert data["limit_energy"] is None
    assert data["limit_cost"] is None


def test_timestamps_are_wall_clock_encoded_as_utc_plus_8() -> None:
    """A raw timestamp rendered in UTC+8 is the wall clock the charger means.

    The session id spells out that wall clock, so the two must agree.
    """
    import datetime as dt

    data = proto.parse_charge_status(proto.parse_frame(CHARGE_STATUS).payload)
    rendered = dt.datetime.fromtimestamp(
        data["session_start"] + DEVICE_TZ_OFFSET, dt.timezone.utc
    ).replace(tzinfo=None)
    stated = dt.datetime.strptime(data["session_id"][:12], "%Y%m%d%H%M")

    # The id is created when the command is issued, a few minutes after the
    # session actually starts.
    assert abs((rendered - stated).total_seconds()) < 15 * 60, (
        f"{rendered} does not match the session id's {stated}"
    )
    for wrong_offset in (0, 7 * 3600):
        other = dt.datetime.fromtimestamp(
            data["session_start"] + wrong_offset, dt.timezone.utc
        ).replace(tzinfo=None)
        assert abs((other - stated).total_seconds()) > 30 * 60


# --- settings ---------------------------------------------------------------


def test_system_time() -> None:
    """Captured from a charger whose clock read 17:04 local."""
    import datetime as dt

    data = proto.parse_system_time(bytes.fromhex("016a9bdb09"))
    rendered = dt.datetime.fromtimestamp(
        data["charger_clock"] + DEVICE_TZ_OFFSET, dt.timezone.utc
    )
    assert rendered.strftime("%Y-%m-%d %H:%M") == "2026-09-05 17:04"


def test_version() -> None:
    data = proto.parse_version(
        bytes.fromhex(
            "36382e333235312e3131384330303733"
            "36382e333235312e3131384330303733"
            "52e41ecf0b"
        )
    )
    assert data["firmware_version"] == "68.3251.118C0073"
    assert data["firmware_backup_version"] == "68.3251.118C0073"


@pytest.mark.parametrize(("raw", "expected"), [("0201", 1), ("0102", 2)])
def test_temperature_unit(raw: str, expected: int) -> None:
    assert proto.parse_temperature_unit(bytes.fromhex(raw))["temperature_unit_raw"] == expected


def test_weekly_plan_has_one_slot_per_weekday() -> None:
    """The idle state: every day off."""
    data = proto.parse_weekly_plan(bytes.fromhex("02" + "011600ffffffffffff" * 7))
    assert len(data["weekly_plan"]) == 7
    assert data["weekly_plan"][0] == {
        "enabled": False, "flag": 1, "hour": 22, "minute": 0,
        "duration_minutes": None, "limit": "ffffffff",
    }
    assert data["weekly_plan_active"] is False


def test_weekly_plan_reads_the_two_days_the_app_switched_on() -> None:
    """Monday and Tuesday enabled at 00:00 for 120 minutes."""
    data = proto.parse_weekly_plan(
        bytes.fromhex("02" + "0300000078ffffffff" * 2 + "0100000000ffffffff" * 5)
    )
    assert data["weekly_plan_active"] is True
    assert [d["enabled"] for d in data["weekly_plan"]] == [True, True, False, False, False, False, False]
    assert data["weekly_plan"][0]["duration_minutes"] == 120
    assert data["weekly_plan"][0]["hour"] == 0
    assert data["weekly_plan"][2]["duration_minutes"] == 0


def test_weekly_plan_ignores_a_truncated_tail() -> None:
    data = proto.parse_weekly_plan(bytes.fromhex("02" + "011600ffffffffffff" * 2 + "0116"))
    assert len(data["weekly_plan"]) == 2


def test_charge_record_is_self_consistent() -> None:
    data = proto.parse_charge_record(proto.parse_frame(CHARGE_RECORD).payload)
    assert data["start_reason"] == "Key"
    assert data["stop_reason"] == "Power Down"
    assert data["end"] - data["start"] == data["duration"]
    assert round(data["meter_end"] - data["meter_start"], 2) == data["energy"]


# --- login -----------------------------------------------------------------

LOGIN_PAYLOAD = bytes.fromhex(
    "0b"                                  # device type
    "45565345" + "00" * 12                # brand   "EVSE"
    + "42533230" + "00" * 12              # model   "BS20"
    + "36382e333235312e3131384330303733"  # hardware "68.3251.118C0073"
    + "00005640"                          # rated power, big endian
    + "20"                                # rated current
    + "5757572e455653452e434f4d" + "00" * 4  # hotline "WWW.EVSE.COM"
)


def test_login_describes_the_device() -> None:
    data = proto.parse_login(LOGIN_PAYLOAD)
    assert data["brand"] == "EVSE"
    assert data["model"] == "BS20"
    assert data["hardware_version"] == "68.3251.118C0073"
    assert data["hotline"] == "WWW.EVSE.COM"


def test_login_rated_power_is_big_endian() -> None:
    """22080 W over three phases is 32 A, which byte 53 confirms.

    Reading this field as little endian gives 1_079_377_920.
    """
    data = proto.parse_login(LOGIN_PAYLOAD)
    assert data["rated_power"] == 22080
    assert data["rated_current"] == 32
    assert round(data["rated_power"] / (3 * 230)) == data["rated_current"]


# --- Wi-Fi configuration ----------------------------------------------------

#: Trailer of a 0x010A frame: two reserved bytes, the server address 0.0.0.0
#: meaning broadcast, and the port 28376.
WIFI_TRAILER = bytes.fromhex("0000" "00000000" "6ed8")


def test_wifi_payload_layout() -> None:
    payload = proto.build_wifi_payload("HomeNetwork", "correct horse battery")
    assert len(payload) == 105
    assert payload[0] == 1
    assert payload[1:33] == b"HomeNetwork".ljust(32, b"\x00")
    assert payload[33:97] == b"correct horse battery".ljust(64, b"\x00")
    assert payload[97:105] == WIFI_TRAILER


def test_wifi_payload_defaults_to_the_broadcast_endpoint() -> None:
    payload = proto.build_wifi_payload("N", "p")
    assert payload[99:103] == bytes(4)
    assert int.from_bytes(payload[103:105], "big") == 28376


def test_wifi_payload_keeps_a_custom_endpoint() -> None:
    payload = proto.build_wifi_payload("N", "p", "192.168.10.5", 28376)
    assert payload[99:103] == bytes([192, 168, 10, 5])


def test_wifi_round_trip_never_returns_the_password() -> None:
    """The passphrase must not reach the state machine or diagnostics."""
    payload = proto.build_wifi_payload("HomeNetwork", "correct horse battery")
    parsed = proto.parse_wifi_info(payload)
    assert parsed["wifi_ssid"] == "HomeNetwork"
    assert parsed["wifi_server_port"] == 28376
    assert not any("password" in key for key in parsed)
    assert not any(
        isinstance(v, str) and "correct" in v for v in parsed.values()
    )


@pytest.mark.parametrize(
    ("ssid", "password"),
    [("", "x"), ("N" * 33, "x"), ("N", "p" * 65)],
)
def test_wifi_payload_rejects_oversized_credentials(ssid: str, password: str) -> None:
    """A truncated network name would be hard to diagnose."""
    with pytest.raises(proto.ProtocolError):
        proto.build_wifi_payload(ssid, password)


def test_wifi_payload_accepts_the_field_maxima() -> None:
    payload = proto.build_wifi_payload("N" * 32, "p" * 64)
    assert len(payload) == 105
    assert payload[97:105] == WIFI_TRAILER


def test_wifi_parse_ignores_a_short_payload() -> None:
    assert proto.parse_wifi_info(bytes(40)) == {}


# --- Bluetooth reassembly ---------------------------------------------------

#: Captured from the FFE4 notify characteristic of a BS20.
BLE_HEARTBEAT = bytes.fromhex(
    "06010019001122334455667788ffffffffffff000308810f02"
)
BLE_AC_STATUS = bytes.fromhex(
    "06010041001122334455667788ffffffffffff000401092f000000000000000267f4"
    "584058400101020c00000000092200000914000003ff00000000000cca0f02"
)


def test_bluetooth_frames_are_identical_to_the_udp_ones() -> None:
    """The charger uses one framing for both transports."""
    assert BLE_HEARTBEAT == HEARTBEAT
    frame = proto.parse_frame(BLE_AC_STATUS)
    assert frame is not None
    assert frame.command == CMD_AC_STATUS
    assert frame.serial == SERIAL
    data = proto.parse_ac_status(frame.payload)
    assert data["voltage_l1"] == 235.1
    assert data["voltage_l2"] == 233.8
    assert data["voltage_l3"] == 232.4
    assert data["temperature_inner"] == 25.92
    assert data["state"] == "plug_not_connected"


def test_reassembler_passes_a_whole_frame_through() -> None:
    assert proto.FrameReassembler().feed(BLE_AC_STATUS) == [BLE_AC_STATUS]


@pytest.mark.parametrize("chunk", [1, 3, 20, 64, 180])
def test_reassembler_joins_split_notifications(chunk: int) -> None:
    """A 65 byte frame does not fit in a 20 byte notification."""
    reassembler = proto.FrameReassembler()
    out: list[bytes] = []
    for i in range(0, len(BLE_AC_STATUS), chunk):
        out += reassembler.feed(BLE_AC_STATUS[i : i + chunk])
    assert out == [BLE_AC_STATUS]


def test_reassembler_splits_back_to_back_frames() -> None:
    reassembler = proto.FrameReassembler()
    assert reassembler.feed(BLE_HEARTBEAT + BLE_AC_STATUS) == [
        BLE_HEARTBEAT,
        BLE_AC_STATUS,
    ]


def test_reassembler_recovers_after_leading_noise() -> None:
    reassembler = proto.FrameReassembler()
    assert reassembler.feed(b"\xde\xad\xbe\xef" + BLE_HEARTBEAT) == [BLE_HEARTBEAT]


def test_reassembler_skips_a_false_magic() -> None:
    """0x06 0x01 can occur inside a payload; a bad length must not wedge it."""
    reassembler = proto.FrameReassembler()
    assert reassembler.feed(b"\x06\x01\x00\x02rubbish" + BLE_HEARTBEAT) == [
        BLE_HEARTBEAT
    ]


def test_reassembler_keeps_a_dangling_magic_byte() -> None:
    reassembler = proto.FrameReassembler()
    assert reassembler.feed(b"\x06") == []
    assert reassembler.feed(BLE_HEARTBEAT[1:]) == [BLE_HEARTBEAT]


def test_reassembler_survives_a_truncated_frame_then_resyncs() -> None:
    reassembler = proto.FrameReassembler()
    assert reassembler.feed(BLE_AC_STATUS[:30]) == []
    assert reassembler.feed(BLE_AC_STATUS[30:]) == [BLE_AC_STATUS]


# --- outbound payloads -----------------------------------------------------


def test_start_payload_keeps_the_user_id_intact() -> None:
    """The user id must survive the padding of its fixed width field."""
    payload = proto.build_start_charge_payload(
        user_id="Key", charge_id="202609051200ABCD", start_at=1788367506, max_current=16
    )
    assert len(payload) == 47
    assert payload[0] == 1
    assert payload[1:17] == b"Key             "
    assert payload[17:33] == b"202609051200ABCD"
    assert int.from_bytes(payload[34:38], "big") == 1788367506
    assert payload[40:46] == b"\xff\xff\xff\xff\xff\xff"
    assert payload[46] == 16


def test_start_payload_carries_limits() -> None:
    payload = proto.build_start_charge_payload(
        user_id="APP", charge_id="x", start_at=0, max_current=32,
        limit_duration=120, limit_energy=4000, limit_cost=1500,
    )
    assert int.from_bytes(payload[40:42], "big") == 120
    assert int.from_bytes(payload[42:44], "big") == 4000
    assert int.from_bytes(payload[44:46], "big") == 1500


def test_stop_payload() -> None:
    payload = proto.build_stop_charge_payload("Key")
    assert len(payload) == 47
    assert payload[0] == 1
    assert payload[1:17] == b"Key             "


def test_long_user_id_is_truncated_not_overflowed() -> None:
    payload = proto.build_stop_charge_payload("A" * 40)
    assert len(payload) == 47
    assert payload[1:17] == b"A" * 16
    assert payload[17] == 0
