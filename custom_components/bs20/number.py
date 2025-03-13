from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.number import NumberEntity, NumberDeviceClass
from typing import cast

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub = config_entry.runtime_data
    try:
        await hub.init_numbers(hass, async_add_entities)
    except (TimeoutError, ConnectionError) as ex:
        # Retry setup later
        raise ConfigEntryNotReady(f"Unable to connect to device: {ex}") 
    

class MaxCurrent(NumberEntity):

    def __init__(self, hass, hub, id, name):
        self._hass = hass
        self._hub = hub
        self._id = id
        self._name = name

        self._attr_name = name
        self._attr_unique_id = f"bs20_{hub.serial()}_{id}"
        self._available = True

    @property
    def unique_id(self):
        return f"{self._attr_unique_id}"

    @property
    def name(self):
        return self._name

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
    
    @property
    def native_max_value(self) -> float:
        return 32
    
    @property
    def native_min_value(self) -> float:
        return 1
    
    @property
    def native_step(self) -> float:
        return 1
    
    @property
    def native_unit_of_measurement(self) -> str:
        return NumberDeviceClass.CURRENT
    
    async def async_set_native_value(self, value: float) -> None:
        await self._hub.set_max_current(value)
    
    @property
    def device_info(self):
        return {
            "identifiers": {("my_integration", self._hub.serial())},
            "name": f"BS20 {self._hub.serial()}",
            "manufacturer": "Besen",
            "model": "BS20",
            "sw_version": "1.0.2",
        }