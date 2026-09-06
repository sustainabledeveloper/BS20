"""Binary sensors for the Besen EV charger."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    ENTITY_ID_FORMAT,
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BesenConfigEntry
from .const import FAULT_STATES
from .coordinator import BesenCoordinator
from .entity import BesenEntity


@dataclass(frozen=True, kw_only=True)
class BesenBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a Besen binary sensor."""

    value_fn: Callable[[BesenCoordinator], bool | None]
    attrs_fn: Callable[[BesenCoordinator], dict[str, Any] | None] | None = None


def _plugged_in(coordinator: BesenCoordinator) -> bool | None:
    state = coordinator.data.get("plug_state")
    if state is None:
        return None
    return state in ("connected", "charging")


def _problem(coordinator: BesenCoordinator) -> bool | None:
    data = coordinator.data
    state = data.get("state")
    emergency = data.get("emergency_stop")
    if state is None and emergency is None:
        return None
    return state in FAULT_STATES or bool(emergency)


#: Weekday order of the slots in command 0x010E.
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday")


def _weekly_plan_attributes(coordinator: BesenCoordinator) -> dict[str, Any] | None:
    """Expose the seven plan slots so a schedule set from the app is visible.

    The plan is read only; the integration cannot write it.
    """
    plan = coordinator.data.get("weekly_plan")
    if not plan:
        return None
    return {
        day: (
            f"{entry['hour']:02d}:{entry['minute']:02d}"
            + (
                f" for {entry['duration_minutes']} min"
                if entry["duration_minutes"]
                else ""
            )
            if entry["enabled"]
            else "off"
        )
        for day, entry in zip(_WEEKDAYS, plan)
    }


BINARY_SENSORS: tuple[BesenBinarySensorDescription, ...] = (
    BesenBinarySensorDescription(
        key="plugged_in",
        translation_key="plugged_in",
        device_class=BinarySensorDeviceClass.PLUG,
        value_fn=_plugged_in,
    ),
    BesenBinarySensorDescription(
        # Not "charging": that key belongs to switch.charging.
        key="charging_active",
        translation_key="charging_active",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda c: (
            None if c.data.get("plug_state") is None else c.data["plug_state"] == "charging"
        ),
    ),
    BesenBinarySensorDescription(
        key="problem",
        translation_key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_problem,
    ),
    BesenBinarySensorDescription(
        key="emergency_stop",
        translation_key="emergency_stop",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.data.get("emergency_stop"),
    ),
    BesenBinarySensorDescription(
        key="weekly_plan_active",
        translation_key="weekly_plan_active",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.data.get("weekly_plan_active"),
        attrs_fn=_weekly_plan_attributes,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BesenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        BesenBinarySensor(coordinator, description) for description in BINARY_SENSORS
    )


class BesenBinarySensor(BesenEntity, BinarySensorEntity):
    """A boolean state read from the charger."""

    _entity_id_format = ENTITY_ID_FORMAT

    entity_description: BesenBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if (fn := self.entity_description.attrs_fn) is None:
            return None
        return fn(self.coordinator)
