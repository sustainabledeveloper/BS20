"""Sensors for the Besen EV charger."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.sensor import (
    ENTITY_ID_FORMAT,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BesenConfigEntry
from .const import CHARGER_STATE_OPTIONS, PLUG_STATE_OPTIONS, TRANSPORT_OPTIONS
from .coordinator import BesenCoordinator
from .entity import BesenEntity


@dataclass(frozen=True, kw_only=True)
class BesenSensorDescription(SensorEntityDescription):
    """Describes a Besen sensor."""

    value_fn: Callable[[BesenCoordinator], Any]
    #: Report a value even while the charger is unreachable.
    always_available: bool = False
    attrs_fn: Callable[[BesenCoordinator], dict[str, Any] | None] | None = None


def _key(name: str) -> Callable[[BesenCoordinator], Any]:
    return lambda coordinator: coordinator.data.get(name)


def _record(name: str) -> Callable[[BesenCoordinator], Any]:
    def _get(coordinator: BesenCoordinator) -> Any:
        record = coordinator.data.get("last_record") or {}
        return record.get(name)

    return _get


def _record_timestamp(name: str) -> Callable[[BesenCoordinator], datetime | None]:
    def _get(coordinator: BesenCoordinator) -> datetime | None:
        record = coordinator.data.get("last_record") or {}
        value = record.get(name)
        if not isinstance(value, int) or value <= 0:
            return None
        return datetime.fromtimestamp(value, timezone.utc)

    return _get


def _connection_attributes(coordinator: BesenCoordinator) -> dict[str, Any]:
    """Detail behind the connection state."""
    attrs: dict[str, Any] = {"charger_address": coordinator.host}
    link = coordinator.bluetooth_link
    if link is not None:
        attrs["bluetooth_link"] = link
        attrs["bluetooth_frames_received"] = coordinator.bluetooth_frames
    return attrs


MEASUREMENT_SENSORS: tuple[BesenSensorDescription, ...] = (
    *(
        BesenSensorDescription(
            key=f"voltage_l{phase}",
            translation_key=f"voltage_l{phase}",
            device_class=SensorDeviceClass.VOLTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            suggested_display_precision=1,
            value_fn=_key(f"voltage_l{phase}"),
        )
        for phase in (1, 2, 3)
    ),
    *(
        BesenSensorDescription(
            key=f"current_l{phase}",
            translation_key=f"current_l{phase}",
            device_class=SensorDeviceClass.CURRENT,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            suggested_display_precision=2,
            value_fn=_key(f"current_l{phase}"),
        )
        for phase in (1, 2, 3)
    ),
    BesenSensorDescription(
        key="power",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        value_fn=_key("power"),
    ),
    BesenSensorDescription(
        key="energy_total",
        translation_key="energy_total",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=_key("energy_total"),
    ),
    BesenSensorDescription(
        key="temperature_inner",
        translation_key="temperature_inner",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=_key("temperature_inner"),
    ),
    BesenSensorDescription(
        key="temperature_outer",
        translation_key="temperature_outer",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=_key("temperature_outer"),
    ),
)

STATE_SENSORS: tuple[BesenSensorDescription, ...] = (
    BesenSensorDescription(
        key="state",
        translation_key="state",
        device_class=SensorDeviceClass.ENUM,
        options=CHARGER_STATE_OPTIONS,
        value_fn=_key("state"),
    ),
    BesenSensorDescription(
        key="plug_state",
        translation_key="plug_state",
        device_class=SensorDeviceClass.ENUM,
        options=PLUG_STATE_OPTIONS,
        value_fn=_key("plug_state"),
    ),
)

SESSION_SENSORS: tuple[BesenSensorDescription, ...] = (
    BesenSensorDescription(
        key="session_energy",
        translation_key="session_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=_key("session_energy"),
    ),
    BesenSensorDescription(
        key="session_duration",
        translation_key="session_duration",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=_key("session_duration"),
    ),
    BesenSensorDescription(
        key="session_start",
        translation_key="session_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c: c.timestamp("session_start"),
    ),
    BesenSensorDescription(
        key="session_max_current",
        translation_key="session_max_current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        value_fn=_key("session_max_current"),
    ),
    BesenSensorDescription(
        key="session_user",
        translation_key="session_user",
        value_fn=_key("session_user"),
    ),
    BesenSensorDescription(
        key="session_id",
        translation_key="session_id",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_key("session_id"),
    ),
    BesenSensorDescription(
        key="session_cost",
        translation_key="session_cost",
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=2,
        value_fn=_key("session_cost"),
    ),
)

RECORD_SENSORS: tuple[BesenSensorDescription, ...] = (
    BesenSensorDescription(
        key="last_record_energy",
        translation_key="last_record_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=_record("energy"),
    ),
    BesenSensorDescription(
        key="last_record_end",
        translation_key="last_record_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_record_timestamp("end"),
    ),
    BesenSensorDescription(
        key="last_record_duration",
        translation_key="last_record_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=_record("duration"),
    ),
    BesenSensorDescription(
        key="last_record_stop_reason",
        translation_key="last_record_stop_reason",
        value_fn=_record("stop_reason"),
    ),
)

DIAGNOSTIC_SENSORS: tuple[BesenSensorDescription, ...] = (
    BesenSensorDescription(
        key="energy_at_session_start",
        translation_key="energy_at_session_start",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_key("energy_at_session_start"),
    ),
    BesenSensorDescription(
        key="energy_total_at_session",
        translation_key="energy_total_at_session",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_key("energy_total_at_session"),
    ),
    BesenSensorDescription(
        key="reservation_time",
        translation_key="reservation_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.timestamp("reservation_time"),
    ),
    # Not a diagnostic: on a charger that drops off Wi-Fi this is operational
    # information, and it has to keep reporting while the charger is
    # unreachable, which is when it says "none".
    BesenSensorDescription(
        key="connection",
        translation_key="connection",
        device_class=SensorDeviceClass.ENUM,
        options=TRANSPORT_OPTIONS,
        always_available=True,
        value_fn=lambda c: c.transport_name,
        attrs_fn=_connection_attributes,
    ),
    # The charger reports its network only in the answer to a Wi-Fi write, so
    # this stays unknown until a re-provision runs. Off by default rather than
    # sitting on every dashboard with no value.
    BesenSensorDescription(
        key="wifi_ssid",
        translation_key="wifi_ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_key("wifi_ssid"),
    ),
    BesenSensorDescription(
        key="charger_clock",
        translation_key="charger_clock",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.timestamp("charger_clock"),
    ),
    BesenSensorDescription(
        key="clock_drift",
        translation_key="clock_drift",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_key("clock_drift"),
    ),
    BesenSensorDescription(
        key="rated_current",
        translation_key="rated_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.rated_current,
    ),
    # Raw protocol fields. The app maps these to text but the tables are not
    # recoverable from its binary, so the raw value is exposed.
    BesenSensorDescription(
        key="start_type_raw",
        translation_key="start_type_raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_key("start_type_raw"),
    ),
    BesenSensorDescription(
        key="charge_type_raw",
        translation_key="charge_type_raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_key("charge_type_raw"),
    ),
    BesenSensorDescription(
        key="state_code",
        translation_key="state_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_key("state_code"),
    ),
    BesenSensorDescription(
        key="phase_count",
        translation_key="phase_count",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_key("phase_count_raw"),
    ),
    BesenSensorDescription(
        key="rated_power",
        translation_key="rated_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_key("rated_power"),
    ),
    # Meaning not established: an idle charger reports 2, so this is not an
    # "output energised" flag.
    BesenSensorDescription(
        key="port",
        translation_key="port",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_key("port"),
    ),
    BesenSensorDescription(
        key="emergency_stop_raw",
        translation_key="emergency_stop_raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_key("emergency_stop_raw"),
    ),
    BesenSensorDescription(
        key="power_reported",
        translation_key="power_reported",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_key("power_reported"),
    ),
    BesenSensorDescription(
        key="output_state_raw",
        translation_key="output_state_raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_key("output_state_raw"),
    ),
    BesenSensorDescription(
        key="monitoring_raw",
        translation_key="monitoring_raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_key("monitoring_raw"),
    ),
    BesenSensorDescription(
        key="unknown_tail_ac",
        translation_key="unknown_tail_ac",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_key("unknown_tail_ac"),
    ),
    BesenSensorDescription(
        key="unknown_tail_session",
        translation_key="unknown_tail_session",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_key("unknown_tail_session"),
    ),
)

SENSORS = (
    *MEASUREMENT_SENSORS,
    *STATE_SENSORS,
    *SESSION_SENSORS,
    *RECORD_SENSORS,
    *DIAGNOSTIC_SENSORS,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BesenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(BesenSensor(coordinator, description) for description in SENSORS)


class BesenSensor(BesenEntity, SensorEntity):
    """A value read from the charger."""

    _entity_id_format = ENTITY_ID_FORMAT

    entity_description: BesenSensorDescription

    @property
    def available(self) -> bool:
        if self.entity_description.always_available:
            return True
        return super().available

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if (fn := self.entity_description.attrs_fn) is None:
            return None
        return fn(self.coordinator)

    @property
    def native_value(self) -> Any:
        value = self.entity_description.value_fn(self.coordinator)
        if isinstance(value, timedelta):
            return value.total_seconds()
        return value
