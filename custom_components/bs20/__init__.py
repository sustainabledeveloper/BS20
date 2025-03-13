from __future__ import annotations
import asyncio
import socket
from typing import Any, Dict, Optional

from aiohttp.web import Request, Response
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform, EVENT_HOMEASSISTANT_STOP

import logging
from .const import DOMAIN
from . import hub

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.NUMBER, Platform.SENSOR, Platform.BUTTON, Platform.SWITCH]

type HubConfigEntry = ConfigEntry

# Global storage for the UDP socket and entries
global_udp_transport: Optional[asyncio.DatagramTransport] = None
global_udp_protocol: Optional[UDPProtocol] = None
global_udp_entries: Dict[str, HubConfigEntry] = {}  # Track entries using entry.entry_id

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration."""
    # Listen for Home Assistant shutdown to stop the UDP server
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, lambda event: stop_udp_server())
    return True

async def async_setup_entry(hass: HomeAssistant, entry: HubConfigEntry) -> bool:
    """Set up a device entry."""

    # Initialize the device's runtime data
    entry.runtime_data = hub.Hub(hass, entry.data["serial"], entry.data["password"])

    # Add the entry to the global dictionary
    global_udp_entries[entry.entry_id] = entry

    # Start the UDP server if it's not already running
    await start_udp_server(hass, 28376)

    # Forward platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a device entry."""
    # Remove the entry from the global dictionary
    if entry.entry_id in global_udp_entries:
        del global_udp_entries[entry.entry_id]

    # Stop the UDP server if no devices are left
    if not global_udp_entries:
        await stop_udp_server()

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    return unload_ok

async def start_udp_server(hass: HomeAssistant, port: int, retries: int = 5) -> None:
    """Start the UDP server globally with retries on port conflict."""
    global global_udp_transport, global_udp_protocol

    if global_udp_transport:
        _LOGGER.info("UDP server already running.")
        return

    loop = asyncio.get_event_loop()
    for attempt in range(retries):
        try:
            transport, protocol = await loop.create_datagram_endpoint(
                lambda: UDPProtocol(handle_udp_datagram),
                local_addr=('0.0.0.0', port)
            )
            sock = transport.get_extra_info('socket')
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

            global_udp_transport = transport
            global_udp_protocol = protocol
            _LOGGER.info(f"UDP server started on port {port}")
            return
        except OSError as e:
            if e.errno == 98 and attempt < retries - 1:  # Address in use
                _LOGGER.warning(f"Port {port} in use, retrying in 1 second...")
                await asyncio.sleep(1)  # Wait for the port to be released
            else:
                raise

async def stop_udp_server() -> None:
    """Stop the global UDP server."""
    global global_udp_transport, global_udp_protocol

    if global_udp_transport:
        global_udp_transport.close()
        global_udp_transport = None
        global_udp_protocol = None
        _LOGGER.info("UDP server stopped.")
        await asyncio.sleep(1)  # Wait for the port to be released

async def handle_udp_datagram(data: bytes, addr: tuple) -> None:
    """Handle incoming UDP datagrams and forward them to all registered entries."""
    for entry in global_udp_entries.values():
        await entry.runtime_data.decode_data(data, addr)

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
        if exc:
            _LOGGER.error(f"UDP connection lost due to error: {exc}")