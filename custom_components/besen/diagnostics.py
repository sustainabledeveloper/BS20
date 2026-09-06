"""Diagnostics for the Besen EV charger integration.

Covers enough to explain an unreachable charger without needing debug logging.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from . import BesenConfigEntry
from .const import (
    CONF_PASSWORD,
    DOMAIN,
    OPT_BLE_ADDRESS,
    OPT_ENABLE_BLE,
    OPT_WIFI_PASSWORD,
    OPT_WIFI_SSID,
)

TO_REDACT = {CONF_PASSWORD, OPT_WIFI_PASSWORD, OPT_WIFI_SSID}


def _bluetooth_report(hass: HomeAssistant, entry: BesenConfigEntry) -> dict[str, Any]:
    """Describe what Bluetooth can see, without raising."""
    coordinator = entry.runtime_data
    report: dict[str, Any] = {
        "enabled_in_options": entry.options.get(OPT_ENABLE_BLE, False),
        "configured_address": entry.options.get(OPT_BLE_ADDRESS) or None,
        "expected_advertised_name": None,
        "transport_attached": False,
        "connected": False,
        "charger_visible": None,
        "scanner_count": None,
        "chargers_in_range": [],
    }

    try:
        from homeassistant.components import bluetooth  # noqa: PLC0415
        from .ble import BLE_NAME_PREFIX, ble_name_for  # noqa: PLC0415
    except ImportError as err:
        report["error"] = f"bluetooth support unavailable: {err}"
        return report

    report["expected_advertised_name"] = ble_name_for(coordinator.serial)
    transport = getattr(coordinator, "_ble", None)
    report["transport_attached"] = transport is not None
    report["connected"] = bool(transport and transport.connected)
    report["retry_pending"] = coordinator.bluetooth_retry_pending
    report["last_attempt_at"] = coordinator.bluetooth_last_attempt
    report["frames_received"] = coordinator.bluetooth_frames
    report["wifi_provision_attempts"] = coordinator.wifi_provision_attempts
    if transport is not None:
        report["write_characteristic"] = transport.write_uuid
        report["notify_characteristic"] = transport.notify_uuid
        report["mtu"] = transport.mtu
        report["frames_sent"] = transport.frames_sent
        report["split_writes"] = transport.split_writes
        report["notifications_received"] = transport.notifications
        report["bytes_received"] = transport.bytes_received
        report["last_write_error"] = transport.last_write_error
        report["connection_attempts"] = transport.attempts
        report["last_error"] = transport.last_error
        report["rssi_at_last_attempt"] = transport.last_rssi

    try:
        report["scanner_count"] = bluetooth.async_scanner_count(hass, connectable=True)
        discovered = list(bluetooth.async_discovered_service_info(hass, True))
    except RuntimeError as err:
        report["error"] = f"Home Assistant has no Bluetooth set up: {err}"
        return report

    report["bluetooth_devices_in_range"] = len(discovered)
    for info in discovered:
        name = (info.name or "").upper()
        if name.startswith(BLE_NAME_PREFIX):
            report["chargers_in_range"].append(
                {"name": info.name, "address": info.address, "rssi": info.rssi}
            )
    report["charger_visible"] = any(
        entry_.get("name", "").upper() == report["expected_advertised_name"]
        or entry_.get("address") == report["configured_address"]
        for entry_ in report["chargers_in_range"]
    )
    return report


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BesenConfigEntry
) -> dict[str, Any]:
    """Return everything needed to debug a report, without the credentials."""
    coordinator = entry.runtime_data
    integration = await async_get_integration(hass, DOMAIN)
    return {
        "integration": {
            "version": str(integration.version),
            "entry_version": entry.version,
        },
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "charger": {
            "serial": coordinator.serial,
            "host": coordinator.host,
            "available": coordinator.available,
            "transport": coordinator.transport_name,
            "rated_current": coordinator.rated_current,
            "unlocked": coordinator.unlocked,
            "wifi_credentials_configured": bool(entry.options.get(OPT_WIFI_SSID)),
        },
        "bluetooth": _bluetooth_report(hass, entry),
        # The charger reports the network it is joined to.
        "decoded": async_redact_data(dict(coordinator.data), TO_REDACT),
    }
