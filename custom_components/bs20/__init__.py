from __future__ import annotations
import asyncio
import socket
from typing import Any

from aiohttp.web import Request, Response
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform

import logging
from .const import DOMAIN
from . import hub

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.NUMBER, Platform.SENSOR, Platform.BUTTON, Platform.SWITCH]

type HubConfigEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: HubConfigEntry) -> bool:
    entry.runtime_data = hub.Hub(hass, entry.data["serial"], entry.data["password"])

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    udp_port = 28376
    await start_udp_server(hass, udp_port, entry)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    # Close the UDP socket if it exists
    if hasattr(entry.runtime_data, 'udp_transport') and entry.runtime_data.udp_transport:
        entry.runtime_data.udp_transport.close()
        _LOGGER.info("UDP server closed")

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    return unload_ok

async def async_setup(hass: HomeAssistant, config: dict):

    return True

async def handle_udp_datagram(data: bytes, addr: tuple, entry: HubConfigEntry) -> None:
    """Handle incoming UDP datagrams."""
    await entry.runtime_data.decode_data(data, addr)


async def start_udp_server(hass: HomeAssistant, port: int, entry: HubConfigEntry) -> None:
    """Start the UDP server."""
    loop = asyncio.get_event_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: UDPProtocol(lambda data, addr: handle_udp_datagram(data, addr, entry)),
        local_addr=('0.0.0.0', port)
    )
    sock = transport.get_extra_info('socket')
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    entry.runtime_data.udp_transport = transport
    _LOGGER.info(f"UDP server started on port {port}")

class UDPProtocol:
    def __init__(self, handle_datagram):
        self.handle_datagram = handle_datagram

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        asyncio.create_task(self.handle_datagram(data, addr))

    def error_received(self, exc):
        _LOGGER.error(f"UDP error received: {exc}")

    def connection_lost(self, exc):
        _LOGGER.info("UDP connection closed")
