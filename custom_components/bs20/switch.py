from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.switch import SwitchEntity
from typing import cast

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub = config_entry.runtime_data
    try:
        await hub.init_switches(hass, async_add_entities)
    except (TimeoutError, ConnectionError) as ex:
        # Retry setup later
        raise ConfigEntryNotReady(f"Unable to connect to device: {ex}") 
    

class Lock(SwitchEntity):

    def __init__(self, hass, hub, id, name):
        self._hass = hass
        self._hub = hub
        self._id = id
        self._name = name
        self._unique_name = f"BS20 {hub.serial()} {name}"

        self._attr_name = name
        self._attr_unique_id = f"bs20_{hub.serial()}_{id}"
        self._available = True
    
    async def async_turn_on(self, **kwargs):
        await self._hub.set_unlocked(True)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        await self._hub.set_unlocked(False)
        self._attr_is_on = False
        self.async_write_ha_state()

    @property
    def unique_id(self):
        return f"{self._attr_unique_id}"

    @property
    def name(self):
        return self._unique_name
    
    @property
    def friendly_name(self):
        return self._name
    
    @callback
    def async_update_callback(self, reason):
        self.async_schedule_update_ha_state()
    
    @property
    def available(self) -> bool:
        return True
    
    @property
    def is_on(self) -> bool:
        return self._hub.is_unlocked()
    
    @property
    def device_info(self):
        return {
            "identifiers": {("my_integration", self._hub.serial())},
            "name": f"BS20 {self._hub.serial()}",
            "manufacturer": "Besen",
            "model": "BS20",
            "sw_version": "1.0.2",
        }