"""Config flow for the Besen EV charger integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import protocol as proto
from .const import (
    CONF_PASSWORD,
    CONF_SERIAL,
    DOMAIN,
    BLE_NAME_PREFIX,
    OPT_ACK_RECORDS,
    OPT_BLE_ADDRESS,
    OPT_ENABLE_BLE,
    OPT_SYNC_CLOCK,
    OPT_WIFI_AUTO,
    OPT_WIFI_PASSWORD,
    OPT_WIFI_SSID,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SERIAL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)

STEP_REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


def _validate(user_input: Mapping[str, Any]) -> tuple[dict[str, str], str | None]:
    """Check the credentials fit the fixed width fields in every frame.

    A serial that is not 16 hex digits, or a password that is not exactly six
    characters, would corrupt the outgoing frame.
    """
    errors: dict[str, str] = {}
    serial: str | None = None

    if CONF_SERIAL in user_input:
        try:
            serial = proto.normalise_serial(str(user_input[CONF_SERIAL]))
        except proto.ProtocolError:
            errors[CONF_SERIAL] = "invalid_serial"

    try:
        proto.encode_password(str(user_input[CONF_PASSWORD]))
    except proto.ProtocolError:
        errors[CONF_PASSWORD] = "invalid_password"

    return errors, serial


class BesenConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Besen config flow."""

    VERSION = 5

    def __init__(self) -> None:
        self._discovered: BluetoothServiceInfoBleak | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a charger seen over Bluetooth.

        The advertised name ends in the last two bytes of the serial: enough to
        recognise a configured charger and fill in its address, not enough to
        identify one outright, so the full serial is still asked for.
        """
        suffix = (discovery_info.name or "")[len(BLE_NAME_PREFIX) :].upper()
        matching = [
            entry
            for entry in self._async_current_entries()
            if str(entry.data.get(CONF_SERIAL, "")).upper().endswith(suffix)
        ]

        if len(matching) > 1:
            # Two chargers whose serials end in the same four characters
            # advertise the same name; the address has to be set by hand.
            _LOGGER.warning(
                "Bluetooth device %s at %s could be any of %s. Set the Bluetooth "
                "address by hand in the options of the right one.",
                discovery_info.name,
                discovery_info.address,
                ", ".join(e.data[CONF_SERIAL] for e in matching),
            )
            return self.async_abort(reason="already_configured")

        if matching:
            entry = matching[0]
            # Remember the address so the fallback need not match on name.
            if entry.options.get(OPT_BLE_ADDRESS) != discovery_info.address:
                self.hass.config_entries.async_update_entry(
                    entry,
                    options={**entry.options, OPT_BLE_ADDRESS: discovery_info.address},
                )
            return self.async_abort(reason="already_configured")

        self._discovered = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name or "Besen"}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the credentials of a charger found over Bluetooth."""
        assert self._discovered is not None
        name = self._discovered.name or ""
        suffix = name[len(BLE_NAME_PREFIX) :].upper()
        errors: dict[str, str] = {}

        if user_input is not None:
            errors, serial = _validate(user_input)
            if not errors and serial is not None:
                if not serial.upper().endswith(suffix):
                    errors[CONF_SERIAL] = "serial_mismatch"
                else:
                    await self.async_set_unique_id(serial)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=serial.upper(),
                        data={
                            CONF_SERIAL: serial,
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                        },
                        options={
                            OPT_BLE_ADDRESS: self._discovered.address,
                            OPT_ENABLE_BLE: True,
                        },
                    )

        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input
            ),
            errors=errors,
            description_placeholders={"name": name, "suffix": suffix},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a charger."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, serial = _validate(user_input)
            if not errors and serial is not None:
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=serial.upper(),
                    data={
                        CONF_SERIAL: serial,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the serial or password of an existing charger."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            errors, serial = _validate(user_input)
            if not errors and serial is not None:
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_mismatch(reason="wrong_charger")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_SERIAL: serial,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input or dict(entry.data)
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle a password that the charger rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, _ = _validate(user_input)
            if not errors:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BesenOptionsFlow()


class BesenOptionsFlow(OptionsFlow):
    """Options for one charger."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            options = dict(user_input)
            for key in (OPT_WIFI_SSID, OPT_WIFI_PASSWORD, OPT_BLE_ADDRESS):
                value = str(options.get(key) or "").strip()
                if value:
                    options[key] = value
                else:
                    options.pop(key, None)
            return self.async_create_entry(data=options)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        OPT_SYNC_CLOCK,
                        default=self.config_entry.options.get(OPT_SYNC_CLOCK, True),
                    ): bool,
                    vol.Optional(
                        OPT_ENABLE_BLE,
                        default=self.config_entry.options.get(OPT_ENABLE_BLE, False),
                    ): bool,
                    vol.Optional(
                        OPT_ACK_RECORDS,
                        default=self.config_entry.options.get(OPT_ACK_RECORDS, False),
                    ): bool,
                    vol.Optional(
                        OPT_WIFI_SSID,
                        description={
                            "suggested_value": self.config_entry.options.get(
                                OPT_WIFI_SSID, ""
                            )
                        },
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                    vol.Optional(
                        OPT_WIFI_PASSWORD,
                        description={
                            "suggested_value": self.config_entry.options.get(
                                OPT_WIFI_PASSWORD, ""
                            )
                        },
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                    vol.Optional(
                        OPT_BLE_ADDRESS,
                        description={
                            "suggested_value": self.config_entry.options.get(
                                OPT_BLE_ADDRESS, ""
                            )
                        },
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                    vol.Optional(
                        OPT_WIFI_AUTO,
                        default=self.config_entry.options.get(OPT_WIFI_AUTO, False),
                    ): bool,
                }
            ),
        )
