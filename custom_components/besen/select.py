"""Select entities for the Besen EV charger."""

from __future__ import annotations

from homeassistant.components.select import (
    ENTITY_ID_FORMAT,
    SelectEntity,
    SelectEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BesenConfigEntry
from .const import TEMPERATURE_UNIT_OPTIONS
from .entity import BesenEntity

TEMPERATURE_UNIT = SelectEntityDescription(
    key="temperature_unit",
    translation_key="temperature_unit",
    options=TEMPERATURE_UNIT_OPTIONS,
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BesenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the select entities."""
    async_add_entities([BesenTemperatureUnit(entry.runtime_data, TEMPERATURE_UNIT)])


class BesenTemperatureUnit(BesenEntity, SelectEntity):
    """The unit the charger shows on its own display."""

    _entity_id_format = ENTITY_ID_FORMAT

    @property
    def current_option(self) -> str | None:
        return self.coordinator.temperature_unit

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_temperature_unit(option)
