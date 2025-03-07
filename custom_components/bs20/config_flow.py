from __future__ import annotations
import logging
from typing import Any
import voluptuous as vol
from homeassistant import config_entries, exceptions
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({
    #vol.Required("host"): str,
    vol.Required("2562529158861192"): str,
    vol.Required("291494"): str
})

async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the user input."""
    #if len(data["host"]) < 3:
    #    raise InvalidHost
    if len(str(data["serial"])) < 3:
        raise InvalidSerial
    if len(data["password"]) < 3:
        raise InvalidPassword

    return {"title": data["serial"]}

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Besen BS20."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                return self.async_create_entry(title=info["title"], data=user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            #except InvalidHost:
            #    errors["host"] = "invalid_host"
            except InvalidSerial:
                errors["serial"] = "invalid_serial"
            except InvalidPassword:
                errors["password"] = "invalid_password"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""

class InvalidHost(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid hostname."""

class InvalidSerial(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid serial number."""

class InvalidPassword(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid password."""
