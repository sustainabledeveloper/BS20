"""Number entities for the Besen EV charger."""

from __future__ import annotations

from homeassistant.components.number import (
    ENTITY_ID_FORMAT,
    NumberDeviceClass,
    NumberEntityDescription,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfEnergy,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BesenConfigEntry
from .coordinator import BesenCoordinator
from .entity import BesenEntity, BesenLocalEntity

CHARGING_CURRENT = NumberEntityDescription(
    key="charging_current",
    translation_key="charging_current",
    device_class=NumberDeviceClass.CURRENT,
    native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
    native_min_value=1,
    native_step=1,
    mode=NumberMode.SLIDER,
)

# Session limits written into the start command. Their wire units are not
# confirmed, so they ship disabled and default to unlimited. See README.
LIMIT_DURATION = NumberEntityDescription(
    key="limit_duration",
    translation_key="limit_duration",
    native_unit_of_measurement=UnitOfTime.MINUTES,
    native_min_value=0,
    native_max_value=1440,
    native_step=1,
    mode=NumberMode.BOX,
    entity_category=EntityCategory.CONFIG,
    entity_registry_enabled_default=False,
)

LIMIT_ENERGY = NumberEntityDescription(
    key="limit_energy",
    translation_key="limit_energy",
    native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    native_min_value=0,
    native_max_value=655,
    native_step=0.01,
    mode=NumberMode.BOX,
    entity_category=EntityCategory.CONFIG,
    entity_registry_enabled_default=False,
)

LIMIT_COST = NumberEntityDescription(
    key="limit_cost",
    translation_key="limit_cost",
    native_min_value=0,
    native_max_value=655,
    native_step=0.01,
    mode=NumberMode.BOX,
    entity_category=EntityCategory.CONFIG,
    entity_registry_enabled_default=False,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BesenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the number entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            BesenChargingCurrent(coordinator, CHARGING_CURRENT),
            BesenSessionLimit(coordinator, LIMIT_DURATION, "duration", 1),
            BesenSessionLimit(coordinator, LIMIT_ENERGY, "energy", 100),
            BesenSessionLimit(coordinator, LIMIT_COST, "cost", 100),
        ]
    )


class BesenChargingCurrent(BesenEntity, RestoreNumber):
    """The current limit applied to the charging session.

    The charger only reports it back during a session, so the last set value
    is restored on startup.
    """

    _entity_id_format = ENTITY_ID_FORMAT

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.coordinator.data.get("charging_current") is not None:
            return
        if (last := await self.async_get_last_number_data()) is None:
            return
        if last.native_value is not None:
            self.coordinator.data["charging_current"] = int(last.native_value)

    @property
    def native_max_value(self) -> float:
        """The charger's own rating."""
        return float(self.coordinator.rated_current)

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        value = data.get("charging_current")
        if value is None:
            value = data.get("session_max_current")
        return None if value is None else float(value)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_max_current(int(value))


class BesenSessionLimit(BesenLocalEntity, RestoreNumber):
    """A limit stored in Home Assistant and sent when a charge is started."""

    _entity_id_format = ENTITY_ID_FORMAT

    def __init__(
        self,
        coordinator: BesenCoordinator,
        description: NumberEntityDescription,
        limit: str,
        wire_scale: int,
    ) -> None:
        super().__init__(coordinator, description)
        self._limit = limit
        self._wire_scale = wire_scale
        self._value: float = 0.0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_number_data()) is not None:
            if last.native_value is not None:
                self._value = float(last.native_value)
        self._push()

    @property
    def native_value(self) -> float:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        self._value = value
        self._push()
        self.async_write_ha_state()

    def _push(self) -> None:
        """Zero means unlimited, sent as 0xFFFF."""
        raw = int(round(self._value * self._wire_scale)) if self._value else None
        self.coordinator.async_set_limit(self._limit, raw)
