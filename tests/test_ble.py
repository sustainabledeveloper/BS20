"""Bluetooth transport tests.

The transport imports Home Assistant's Bluetooth helpers, so these skip when it
is not installed::

    python3 -m pytest tests/
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components"))

pytest.importorskip("homeassistant.components.bluetooth")
pytest.importorskip("bleak_retry_connector")

from besen.ble import BesenBleTransport, ble_name_for  # noqa: E402

READ_WRITE = ["read", "write", "write-without-response"]
WRITE = ["write", "write-without-response"]
WRITE_NR = ["write-without-response"]
NOTIFY = ["notify"]
READ_NOTIFY = ["read", "notify"]


class _Char:
    def __init__(self, short: str, properties: list[str]) -> None:
        self.uuid = f"0000{short}-0000-1000-8000-00805f9b34fb"
        self.properties = properties


class _Service:
    def __init__(self, uuid: str, characteristics: list[_Char]) -> None:
        self.uuid = uuid
        self.characteristics = characteristics


class _Client:
    def __init__(self, services: list[_Service]) -> None:
        self.services = services


#: The GATT table of a BS20. FD00 is listed first: it is a plausible looking
#: pair that connects and then carries nothing.
BS20_SERVICES = [
    _Service("fd00", [_Char("fd01", WRITE_NR),
                      _Char("fd02", ["write-without-response", "notify"])]),
    _Service("ffb0", [_Char("ffb1", READ_WRITE), _Char("ffb2", READ_WRITE)]),
    _Service("ffd0", [_Char("ffd1", READ_WRITE), _Char("ffd3", READ_NOTIFY)]),
    _Service("fff0", [_Char("fff1", READ_WRITE), _Char("fff2", WRITE),
                      _Char("fff3", READ_NOTIFY)]),
    _Service("ff90", [_Char("ff91", READ_WRITE), _Char("ff92", READ_WRITE)]),
    _Service("ffc0", [_Char("ffc1", WRITE_NR), _Char("ffc2", NOTIFY)]),
    _Service("ffe5", [_Char("ffe9", WRITE)]),
    _Service("ffe0", [_Char("ffe4", NOTIFY)]),
]


def _pick(services):
    write, notify = BesenBleTransport._pick_characteristics(_Client(services))
    short = lambda c: None if c is None else c.uuid[4:8]  # noqa: E731
    return short(write), short(notify)


def test_prefers_the_confirmed_pair_whatever_the_scan_order() -> None:
    """FD00 comes first and looks valid, but does not carry the protocol."""
    assert _pick(BS20_SERVICES) == ("ffe9", "ffe4")


def test_falls_back_to_the_next_known_pair() -> None:
    """A module using the other convention still works."""
    services = [
        _Service("fd00", [_Char("fd01", WRITE_NR),
                          _Char("fd02", ["write-without-response", "notify"])]),
        _Service("fff0", [_Char("fff2", WRITE), _Char("fff3", READ_NOTIFY)]),
    ]
    assert _pick(services) == ("fff2", "fff3")


def test_uses_an_unknown_module_rather_than_refusing() -> None:
    services = [_Service("abcd", [_Char("abce", WRITE), _Char("abcf", NOTIFY)])]
    write, notify = _pick(services)
    assert write is not None and notify is not None


def test_never_pairs_half_a_match() -> None:
    """A write with nothing to listen on is not a usable transport."""
    assert _pick([_Service("ffe5", [_Char("ffe9", WRITE)])]) == ("ffe9", None)


def test_ignores_characteristics_that_cannot_carry_traffic() -> None:
    services = [
        _Service("180a", [_Char("2a26", ["read"]), _Char("2a27", ["read"])]),
        _Service("ffe5", [_Char("ffe9", WRITE)]),
        _Service("ffe0", [_Char("ffe4", NOTIFY)]),
    ]
    assert _pick(services) == ("ffe9", "ffe4")


@pytest.mark.parametrize(
    ("serial", "expected"),
    [
        ("1122334455667788", "ACP#EVSE7788"),
        ("aabbccddeeff1234", "ACP#EVSE1234"),
    ],
)
def test_advertised_name_comes_from_the_serial(serial: str, expected: str) -> None:
    assert ble_name_for(serial) == expected


class _Info:
    def __init__(self, name: str, address: str) -> None:
        self.name = name
        self.address = address
        self.rssi = -70


def _transport(monkeypatch, discovered, address=None):
    from besen import ble

    monkeypatch.setattr(
        ble.bluetooth, "async_discovered_service_info", lambda _hass, _c: discovered
    )
    return BesenBleTransport(None, "1122334455667788", lambda _f: None, address)


def test_configured_address_wins(monkeypatch) -> None:
    other = _Info("ACP#EVSE7788", "AA:AA:AA:AA:AA:AA")
    mine = _Info("ACP#EVSE7788", "C0:FF:EE:00:12:34")
    found = _transport(monkeypatch, [other, mine], "c0:ff:ee:00:12:34").find_device()
    assert found is mine


def test_stale_address_falls_back_to_the_advertised_name(monkeypatch) -> None:
    """An address that nothing answers to must not hide a visible charger."""
    mine = _Info("ACP#EVSE7788", "C0:FF:EE:00:12:34")
    found = _transport(monkeypatch, [mine], "11:22:33:44:55:66").find_device()
    assert found is mine


def test_another_charger_is_not_mistaken_for_this_one(monkeypatch) -> None:
    found = _transport(
        monkeypatch, [_Info("ACP#EVSE1234", "11:22:33:44:55:66")], None
    ).find_device()
    assert found is None
