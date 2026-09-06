"""Shared entity base for the Besen integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription, async_generate_entity_id
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BesenCoordinator


class BesenEntity(CoordinatorEntity[BesenCoordinator]):
    """Base class carrying the device registry entry and availability."""

    _attr_has_entity_name = True

    #: Set by each platform to its ``ENTITY_ID_FORMAT``.
    _entity_id_format: str | None = None

    def __init__(
        self, coordinator: BesenCoordinator, description: EntityDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.serial}_{description.key}"

        # Pin the entity id to the English key. Home Assistant would
        # otherwise derive it from the translated name and the device name,
        # making ids depend on the interface language and on when the charger
        # first identified itself. Display names still follow the language.
        # Existing entities keep the id they were registered with.
        if self._entity_id_format:
            self.entity_id = async_generate_entity_id(
                self._entity_id_format,
                f"{DOMAIN}_{coordinator.serial}_{description.key}",
                hass=coordinator.hass,
            )

    @property
    def device_info(self) -> DeviceInfo:
        data = self.coordinator.data
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.serial)},
            name=self.coordinator.device_name,
            manufacturer=data.get("brand") or "Besen",
            model=data.get("model") or "BS20",
            hw_version=data.get("hardware_version"),
            serial_number=self.coordinator.serial,
        )

    @property
    def available(self) -> bool:
        return self.coordinator.available


class BesenLocalEntity(BesenEntity):
    """An entity whose state lives in Home Assistant, not on the charger.

    Stays usable while the charger is unreachable.
    """

    @property
    def available(self) -> bool:
        return True
