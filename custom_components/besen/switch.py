"""Switches for the Besen EV charger."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import (
    ENTITY_ID_FORMAT,
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import BesenConfigEntry
from .coordinator import BesenCoordinator
from .entity import BesenEntity, BesenLocalEntity

CHARGING = SwitchEntityDescription(
    key="charging",
    translation_key="charging",
    device_class=SwitchDeviceClass.SWITCH,
)

BUTTON_START = SwitchEntityDescription(
    key="button_start",
    translation_key="button_start",
    entity_category=EntityCategory.CONFIG,
)

# The 1.x "Unlock" switch. Kept visible so migrated automations that toggle
# it keep working.
UNLOCKED = SwitchEntityDescription(
    key="unlocked",
    translation_key="unlocked",
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BesenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switches."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            BesenChargingSwitch(coordinator, CHARGING),
            BesenButtonStartSwitch(coordinator, BUTTON_START),
            BesenUnlockSwitch(coordinator, UNLOCKED),
        ]
    )


class BesenChargingSwitch(BesenEntity, SwitchEntity):
    """Start and stop charging.

    The primary control; unlike the buttons it carries state.
    """

    _entity_id_format = ENTITY_ID_FORMAT

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data.get("plug_state") is None:
            return None
        return self.coordinator.is_charging

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_start_charge()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_stop_charge()


class BesenButtonStartSwitch(BesenEntity, SwitchEntity):
    """Whether the charger's own button may start a session."""

    _entity_id_format = ENTITY_ID_FORMAT

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.get("button_start_enabled")

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_button_start(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_button_start(False)


class BesenUnlockSwitch(BesenLocalEntity, SwitchEntity, RestoreEntity):
    """A local safety catch: while off, no command is sent to the charger.

    Its position is restored across restarts.
    """

    _entity_id_format = ENTITY_ID_FORMAT

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        unlocked = True if last_state is None else last_state.state == STATE_ON
        self.coordinator.async_set_unlocked(unlocked)

    @property
    def is_on(self) -> bool:
        return self.coordinator.unlocked

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.async_set_unlocked(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.async_set_unlocked(False)
        self.async_write_ha_state()
