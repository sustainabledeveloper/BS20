"""The Besen EV charger integration."""

from __future__ import annotations

import asyncio
import errno
import logging
import socket
from typing import Any

from homeassistant import loader
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import slugify

from . import protocol as proto
from .const import (
    DEFAULT_LISTEN_PORT,
    DOMAIN,
    OPT_BLE_ADDRESS,
    OPT_ENABLE_BLE,
    V1_ENTITIES,
)
from .coordinator import BesenCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

type BesenConfigEntry = ConfigEntry[BesenCoordinator]

DATA_LISTENER = "listener"


class BesenListener(asyncio.DatagramProtocol):
    """One shared UDP socket, fanned out to the configured chargers.

    Chargers broadcast, so a single bound socket serves all of them. Frames are
    routed by serial number so several chargers can coexist.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.transport: asyncio.DatagramTransport | None = None
        self._coordinators: dict[str, BesenCoordinator] = {}

    # asyncio.DatagramProtocol ------------------------------------------------

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]
        for coordinator in self._coordinators.values():
            coordinator.attach_transport(transport)  # type: ignore[arg-type]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        frame = proto.parse_frame(data)
        if frame is None:
            return
        coordinator = self._coordinators.get(frame.serial)
        if coordinator is None:
            _LOGGER.debug(
                "Ignoring frame from unconfigured charger %s at %s", frame.serial, addr[0]
            )
            return
        # Already on the event loop; no task needed.
        coordinator.handle_frame(frame, addr)

    def error_received(self, exc: Exception) -> None:
        _LOGGER.error("UDP socket error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        if exc:
            _LOGGER.error("UDP socket closed unexpectedly: %s", exc)

    # registry ---------------------------------------------------------------

    @callback
    def register(self, coordinator: BesenCoordinator) -> None:
        self._coordinators[coordinator.serial] = coordinator
        if self.transport is not None:
            coordinator.attach_transport(self.transport)

    @callback
    def unregister(self, serial: str) -> None:
        self._coordinators.pop(serial, None)

    @property
    def empty(self) -> bool:
        return not self._coordinators

    def close(self) -> None:
        if self.transport is not None:
            self.transport.close()
            self.transport = None


async def _async_get_listener(hass: HomeAssistant) -> BesenListener:
    """Return the shared listener, creating and binding it on first use."""
    domain_data: dict[str, Any] = hass.data.setdefault(DOMAIN, {})
    if (listener := domain_data.get(DATA_LISTENER)) is not None:
        return listener

    listener = BesenListener(hass)
    try:
        await hass.loop.create_datagram_endpoint(
            lambda: listener,
            local_addr=("0.0.0.0", DEFAULT_LISTEN_PORT),
            allow_broadcast=True,
            reuse_port=True,
        )
    except OSError as err:
        if err.errno == errno.EADDRINUSE:
            raise ConfigEntryNotReady(
                f"UDP port {DEFAULT_LISTEN_PORT} is already in use by another "
                "process. Home Assistant will retry."
            ) from err
        raise ConfigEntryNotReady(
            f"Could not open UDP port {DEFAULT_LISTEN_PORT}: {err}"
        ) from err

    if listener.transport is not None:
        sock = listener.transport.get_extra_info("socket")
        if sock is not None:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    domain_data[DATA_LISTENER] = listener
    _LOGGER.debug("Listening for chargers on UDP port %s", DEFAULT_LISTEN_PORT)

    async def _stop(_event: Any) -> None:
        listener.close()
        domain_data.pop(DATA_LISTENER, None)

    domain_data["stop_unsub"] = hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STOP, _stop
    )
    return listener


async def async_setup_entry(hass: HomeAssistant, entry: BesenConfigEntry) -> bool:
    """Set up one charger."""
    # Logged so a support report identifies the build.
    integration = await loader.async_get_integration(hass, DOMAIN)
    _LOGGER.info("Setting up Besen %s for charger %s",
                 integration.version, entry.data["serial"])

    coordinator = BesenCoordinator(hass, entry)
    entry.runtime_data = coordinator

    listener = await _async_get_listener(hass)
    listener.register(coordinator)
    _async_attach_bluetooth(hass, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


@callback
def _async_attach_bluetooth(hass: HomeAssistant, coordinator: BesenCoordinator) -> None:
    """Give the coordinator a Bluetooth fallback, if available.

    Imported lazily: Bluetooth is optional and the import would fail on an
    installation without the stack.
    """
    if not coordinator.entry.options.get(OPT_ENABLE_BLE, False):
        return
    try:
        from .ble import BesenBleTransport  # noqa: PLC0415 - optional dependency
    except ImportError as err:
        _LOGGER.warning(
            "Bluetooth fallback is enabled but unavailable on this system: %s", err
        )
        return
    coordinator.attach_bluetooth(
        BesenBleTransport(
            hass,
            coordinator.serial,
            coordinator.handle_ble_frame,
            coordinator.entry.options.get(OPT_BLE_ADDRESS) or None,
        )
    )
    _LOGGER.debug("Bluetooth fallback armed for %s", coordinator.serial)


async def _async_reload_entry(hass: HomeAssistant, entry: BesenConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: BesenConfigEntry) -> bool:
    """Tear down one charger, keeping the socket if others still need it."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    coordinator = entry.runtime_data
    await coordinator.async_shutdown()

    domain_data = hass.data.get(DOMAIN, {})
    if (listener := domain_data.get(DATA_LISTENER)) is not None:
        listener.unregister(coordinator.serial)
        if listener.empty:
            listener.close()
            domain_data.pop(DATA_LISTENER, None)
            if (unsub := domain_data.pop("stop_unsub", None)) is not None:
                unsub()
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Bring an entry created by an earlier release up to date.

    Migrates entity unique ids to the current scheme, clears the labels 1.x
    wrote into the entity registry so translations apply, resolves duplicates
    in favour of the id already in use, and re-keys the device entry. Runs for
    any entry below the current version.
    """
    if entry.version >= 5:
        return True

    _LOGGER.info(
        "Migrating Besen config entry %s from version %s", entry.title, entry.version
    )
    try:
        serial = proto.normalise_serial(entry.data["serial"])
    except proto.ProtocolError:
        _LOGGER.error(
            "Cannot migrate entry %s: serial %r is not 16 hex digits. "
            "Remove and re-add the integration.",
            entry.title,
            entry.data.get("serial"),
        )
        return False

    _async_migrate_entities(hass, entry, serial)
    _async_migrate_device(hass, entry, serial)

    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, "serial": serial},
        unique_id=serial,
        version=5,
    )
    return True


@callback
def _async_migrate_entities(
    hass: HomeAssistant, entry: ConfigEntry, serial: str
) -> None:
    """Rename, relabel or retire every entity created by 1.x.

    Entity ids are what dashboards, automations and history reference, so they
    are preserved. Where both a 1.x entity and a replacement exist, the
    replacement is removed.
    """
    registry = er.async_get(hass)
    raw_serial = entry.data["serial"]
    old_prefix = f"bs20_{raw_serial}_"
    was_v1 = any(
        e.unique_id.startswith(old_prefix)
        or e.entity_id.split(".", 1)[1].startswith(f"bs20_{raw_serial}_")
        for e in registry.entities.values()
        if e.config_entry_id == entry.entry_id
    )
    #: new key -> the label 1.x stored, for ids already renamed
    labels_by_new_key = {
        new_key: label for label, new_key in V1_ENTITIES.values() if new_key
    }

    for registry_entry in list(registry.entities.values()):
        if registry_entry.config_entry_id != entry.entry_id:
            continue
        if registry_entry.entity_id not in registry.entities:
            # Removed earlier in this pass as a duplicate.
            continue
        unique_id = registry_entry.unique_id

        if unique_id.startswith(old_prefix):
            old_key = unique_id[len(old_prefix) :]
            known = V1_ENTITIES.get(old_key)
            if known is None:
                continue
            label, new_key = known

            if new_key is None:
                _LOGGER.debug("Removing retired entity %s", registry_entry.entity_id)
                registry.async_remove(registry_entry.entity_id)
                continue

            target = f"{serial}_{new_key}"
            existing = registry.async_get_entity_id(
                registry_entry.domain, DOMAIN, target
            )
            if existing and existing != registry_entry.entity_id:
                # Drop the replacement, not this: this is the id already
                # referenced by dashboards, automations and history.
                _LOGGER.debug(
                    "Removing %s so %s can keep its id",
                    existing,
                    registry_entry.entity_id,
                )
                registry.async_remove(existing)

            updates: dict[str, Any] = {"new_unique_id": target}
            if registry_entry.name == label:
                updates["name"] = None
            registry.async_update_entity(registry_entry.entity_id, **updates)
            continue

        # Already on the new unique id, but possibly still carrying 1.x's
        # label, or a new entity id where the 1.x one should have been kept.
        if unique_id.startswith(f"{serial}_"):
            new_key = unique_id[len(serial) + 1 :]
            if registry_entry.name and registry_entry.name == labels_by_new_key.get(
                new_key
            ):
                registry.async_update_entity(registry_entry.entity_id, name=None)
            if was_v1:
                _async_restore_entity_id(
                    registry, registry_entry, raw_serial, new_key
                )


@callback
def _async_restore_entity_id(
    registry: er.EntityRegistry,
    registry_entry: er.RegistryEntry,
    raw_serial: str,
    new_key: str,
) -> None:
    """Put an entity back on the id 1.x gave it, if that id is free.

    Only entities that lost their id are moved. The id is taken from the
    registry's record of the entity 1.x created, and only reconstructed from
    the label when that record is gone.
    """
    old_prefix = f"bs20_{raw_serial}_"
    if registry_entry.entity_id.split(".", 1)[1].startswith(old_prefix):
        # Still on a 1.x id. Labels changed between 1.x releases, so the id
        # here is the only reliable record of what the user's dashboards
        # reference: leave it alone.
        return

    old_key = next((key for key, (_, new) in V1_ENTITIES.items() if new == new_key), None)
    if old_key is None:
        return

    deleted = registry.deleted_entities.get(
        (registry_entry.domain, DOMAIN, f"{old_prefix}{old_key}")
    )
    if deleted is not None:
        wanted = deleted.entity_id
    else:
        label = V1_ENTITIES[old_key][0]
        wanted = f"{registry_entry.domain}.{old_prefix}{slugify(label)}"

    if registry_entry.entity_id == wanted:
        return
    if registry.async_get(wanted) is not None:
        return
    _LOGGER.info("Restoring %s to its previous id %s", registry_entry.entity_id, wanted)
    registry.async_update_entity(registry_entry.entity_id, new_entity_id=wanted)


@callback
def _async_migrate_device(
    hass: HomeAssistant, entry: ConfigEntry, serial: str
) -> None:
    """Leave one device entry holding every entity of this charger.

    1.x keyed its device on a placeholder identifier. Where a 2.x device was
    created alongside it the two have to be merged, or the entities end up
    split between them, showing two different device names, and re-keying
    collides on the identifier.
    """
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    placeholder = ("my_integration", entry.data["serial"])

    # The 1.x entry is the one the user has had all along, with whatever area,
    # name and labels they gave it, so it is the one that survives.
    keep = next((d for d in devices if placeholder in d.identifiers), None)
    if keep is None:
        keep = next((d for d in devices if (DOMAIN, serial) in d.identifiers), None)
    if keep is None:
        return

    for device in devices:
        if device.id == keep.id:
            continue
        for registry_entry in er.async_entries_for_device(
            entity_registry, device.id, include_disabled_entities=True
        ):
            entity_registry.async_update_entity(
                registry_entry.entity_id, device_id=keep.id
            )
        device_registry.async_remove_device(device.id)

    if keep.identifiers != {(DOMAIN, serial)}:
        device_registry.async_update_device(
            keep.id, new_identifiers={(DOMAIN, serial)}
        )
