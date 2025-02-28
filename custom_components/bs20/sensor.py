from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor import SensorDeviceClass
from typing import cast

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub = config_entry.runtime_data
    try:
        await hub.init_sensors(hass, async_add_entities)
    except (TimeoutError, ConnectionError) as ex:
        # Retry setup later
        raise ConfigEntryNotReady(f"Unable to connect to device: {ex}") 
    

class Voltage(SensorEntity):

    def __init__(self, hass, hub, id, name):
        self._hass = hass
        self._hub = hub
        self._id = id
        self._name = name

        self._attr_name = name
        self._attr_unique_id = f"bs20_{hub.serial()}_{id}"
        self._available = True

    @property
    def native_value(self) -> float | None:
        """Return the value of the entity."""
        return cast(float | None, self._hub.device_data[self._id])
    
    @property
    def device_class(self):
        return SensorDeviceClass.VOLTAGE
    
    @property
    def native_unit_of_measurement(self):
        return "V"
    
    @callback
    def async_update_callback(self, reason):
        self.async_schedule_update_ha_state()
    
    @property
    def available(self) -> bool:
        return self._hub.available
    
class Current(SensorEntity):

    def __init__(self, hass, hub, id, name):
        self._hass = hass
        self._hub = hub
        self._id = id
        self._name = name

        self._attr_name = name
        self._attr_unique_id = f"bs20_{hub.serial()}_{id}"
        self._available = True

    @property
    def native_value(self) -> float | None:
        """Return the value of the entity."""
        return cast(float | None, self._hub.device_data[self._id])
    
    @property
    def device_class(self):
        return SensorDeviceClass.CURRENT
    
    @property
    def native_unit_of_measurement(self):
        return "A"
    
    @callback
    def async_update_callback(self, reason):
        self.async_schedule_update_ha_state()
    
    @property
    def available(self) -> bool:
        return self._hub.available
    
class Power(SensorEntity):

    def __init__(self, hass, hub, id, name):
        self._hass = hass
        self._hub = hub
        self._id = id
        self._name = name

        self._attr_name = name
        self._attr_unique_id = f"bs20_{hub.serial()}_{id}"
        self._available = True

    @property
    def native_value(self) -> float | None:
        """Return the value of the entity."""
        return cast(float | None, self._hub.device_data[self._id])
    
    @property
    def device_class(self):
        return SensorDeviceClass.POWER
    
    @property
    def native_unit_of_measurement(self):
        return "kW"
    
    @callback
    def async_update_callback(self, reason):
        self.async_schedule_update_ha_state()
    
    @property
    def available(self) -> bool:
        return self._hub.available
    
class Work(SensorEntity):

    def __init__(self, hass, hub, id, name):
        self._hass = hass
        self._hub = hub
        self._id = id
        self._name = name

        self._attr_name = name
        self._attr_unique_id = f"bs20_{hub.serial()}_{id}"
        self._available = True

    @property
    def native_value(self) -> float | None:
        """Return the value of the entity."""
        return cast(float | None, self._hub.device_data[self._id])
    
    @property
    def device_class(self):
        return SensorDeviceClass.ENERGY_STORAGE
    
    @property
    def native_unit_of_measurement(self):
        return "kWh"
    
    @callback
    def async_update_callback(self, reason):
        self.async_schedule_update_ha_state()
    
    @property
    def available(self) -> bool:
        return self._hub.available
    
class Temperature(SensorEntity):

    def __init__(self, hass, hub, id, name):
        self._hass = hass
        self._hub = hub
        self._id = id
        self._name = name

        self._attr_name = name
        self._attr_unique_id = f"bs20_{hub.serial()}_{id}"
        self._available = True

    @property
    def native_value(self) -> float | None:
        """Return the value of the entity."""
        return cast(float | None, self._hub.device_data[self._id])
    
    @property
    def device_class(self):
        return SensorDeviceClass.TEMPERATURE
    
    @property
    def native_unit_of_measurement(self):
        return "°C"
    
    @callback
    def async_update_callback(self, reason):
        self.async_schedule_update_ha_state()
    
    @property
    def available(self) -> bool:
        return self._hub.available
    
class OtherSensor(SensorEntity):

    def __init__(self, hass, hub, id, name):
        self._hass = hass
        self._hub = hub
        self._id = id
        self._name = name

        self._attr_name = name
        self._attr_unique_id = f"bs20_{hub.serial()}_{id}"
        self._available = True

    @property
    def native_value(self) -> float | None:
        """Return the value of the entity."""
        return cast(float | None, self._hub.device_data[self._id])
    
    @callback
    def async_update_callback(self, reason):
        self.async_schedule_update_ha_state()
    
    @property
    def available(self) -> bool:
        return self._hub.available