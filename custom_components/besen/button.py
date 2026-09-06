"""Buttons for the Besen EV charger.

``switch.charging`` is the primary control.  These two buttons are kept so
existing automations that call ``button.press`` keep working.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import (
    ENTITY_ID_FORMAT,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BesenConfigEntry
from .coordinator import BesenCoordinator
from .entity import BesenEntity


@dataclass(frozen=True, kw_only=True)
class BesenButtonDescription(ButtonEntityDescription):
    """Describes a Besen button."""

    press_fn: Callable[[BesenCoordinator], Awaitable[None]]
    #: Stay pressable while the charger is unreachable.
    always_available: bool = False


BUTTONS: tuple[BesenButtonDescription, ...] = (
    BesenButtonDescription(
        key="start_charging",
        translation_key="start_charging",
        press_fn=lambda coordinator: coordinator.async_start_charge(),
    ),
    BesenButtonDescription(
        key="stop_charging",
        translation_key="stop_charging",
        press_fn=lambda coordinator: coordinator.async_stop_charge(),
    ),
    BesenButtonDescription(
        key="reprovision_wifi",
        translation_key="reprovision_wifi",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        always_available=True,
        press_fn=lambda coordinator: coordinator.async_provision_wifi(),
    ),
    BesenButtonDescription(
        key="sync_clock",
        translation_key="sync_clock",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda coordinator: coordinator.async_sync_clock(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BesenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the buttons."""
    coordinator = entry.runtime_data
    async_add_entities(BesenButton(coordinator, description) for description in BUTTONS)


class BesenButton(BesenEntity, ButtonEntity):
    """A one shot command."""

    _entity_id_format = ENTITY_ID_FORMAT

    entity_description: BesenButtonDescription

    @property
    def available(self) -> bool:
        if self.entity_description.always_available:
            return True
        return super().available

    async def async_press(self) -> None:
        await self.entity_description.press_fn(self.coordinator)
