from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.button import ButtonEntity
from typing import cast

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub = config_entry.runtime_data
    try:
        await hub.init_buttons(hass, async_add_entities)
    except (TimeoutError, ConnectionError) as ex:
        # Retry setup later
        raise ConfigEntryNotReady(f"Unable to connect to device: {ex}") 
    

class StartCharging(ButtonEntity):

    def __init__(self, hass, hub, id, name):
        self._hass = hass
        self._hub = hub
        self._id = id
        self._name = name

        self._attr_name = name
        self._attr_unique_id = f"bs20_{hub.serial()}_{id}"
        self._available = True
    
    @property
    def available(self) -> bool:
        return self._hub.available
    
    async def async_press(self) -> None:
        self._hub.start_charge()
    
class StopCharging(ButtonEntity):

    def __init__(self, hass, hub, id, name):
        self._hass = hass
        self._hub = hub
        self._id = id
        self._name = name

        self._attr_name = name
        self._attr_unique_id = f"bs20_{hub.serial()}_{id}"
        self._available = True
    
    @property
    def available(self) -> bool:
        return self._hub.available
    
    async def async_press(self) -> None:
        self._hub.stop_charge()