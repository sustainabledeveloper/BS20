"""Push based coordinator for one Besen charger."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    ACTIVE_STATES,
    DEFAULT_LISTEN_PORT,
    CMD_AC_STATUS,
    CMD_SYSTEM_TIME,
    CMD_SYSTEM_TIME_STATE,
    CMD_TEMPERATURE_UNIT,
    CMD_TEMPERATURE_UNIT_STATE,
    CMD_VERSION_STATE,
    CMD_WEEKLY_PLAN,
    CMD_WEEKLY_PLAN_STATE,
    CMD_WIFI,
    CMD_WIFI_STATE,
    DEVICE_TZ_OFFSET,
    TEMPERATURE_UNITS,
    CMD_AC_STATUS_ALT,
    CMD_BUTTON_CONTROL,
    CMD_BUTTON_STATE,
    CMD_CHARGE_RECORD,
    CMD_CHARGE_STATUS,
    CMD_CHARGE_STATUS_ALT,
    CMD_HEARTBEAT,
    CMD_LOGIN,
    CMD_LOGIN_ACK,
    CMD_LOGIN_CONFIRM,
    CMD_MONITORING_STATE,
    CMD_PASSWORD_ERROR,
    CMD_LOGIN_REQUEST,
    CMD_SET_MAX_CURRENT,
    CMD_START_CHARGE,
    CMD_STOP_CHARGE,
    DOMAIN,
    EVENT_CHARGE_RECORD,
    LIMIT_UNLIMITED,
    OFFLINE_TIMEOUT,
    BLE_ADVERT_DEBOUNCE,
    BLE_ADVERT_MAX_AGE,
    BLE_ADVERT_POLL_INTERVAL,
    BLE_FALLBACK_DELAY,
    BLE_INITIAL_DELAY,
    BLE_RECONNECT_DELAY,
    BLE_RETRY_INTERVAL,
    OPT_ACK_RECORDS,
    OPT_ENABLE_BLE,
    OPT_SYNC_CLOCK,
    OPT_WIFI_AUTO,
    OPT_WIFI_PASSWORD,
    OPT_WIFI_SSID,
    RESPONSE_FLAG,
    SUBOP_QUERY,
    SUBOP_SET,
)
from . import protocol as proto

if TYPE_CHECKING:
    from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

    from .ble import BesenBleTransport

_LOGGER = logging.getLogger(__name__)

#: Identifier written into the session when Home Assistant starts a charge.
#: The charger echoes it back as the session user.
DEFAULT_USER_ID = "APP"

#: The login exchange settles within about a dozen frames. Past this the
#: integration stops answering instead of trading packets indefinitely.
MAX_LOGIN_FRAMES = 60

#: Seconds to wait after the login exchange before reading the settings.
SETTINGS_SWEEP_DELAY = 6

#: Commands whose only expected answer is a bare acknowledgement.
_ACK_COMMANDS = {
    CMD_AC_STATUS,
    CMD_AC_STATUS_ALT,
    CMD_CHARGE_STATUS,
    CMD_CHARGE_STATUS_ALT,
}


class BesenCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Owns the decoded state of a single charger.

    The charger pushes datagrams on its own schedule, so there is no polling
    loop; ``async_set_updated_data`` is called whenever a frame arrives and a
    watchdog marks the device unavailable when the stream stops.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.serial = proto.normalise_serial(entry.data["serial"])
        self._password = entry.data["password"]

        # Per instance; several chargers may be configured at once.
        self._data: dict[str, Any] = {}
        self._host: str | None = None
        self._port: int | None = None
        self._transport: asyncio.DatagramTransport | None = None
        self._ble: "BesenBleTransport | None" = None
        self._ble_retry: CALLBACK_TYPE | None = None
        self._ble_task: asyncio.Task[None] | None = None
        self._ble_unsub: list[CALLBACK_TYPE] = []
        self._ble_last_try: float | None = None
        self._watchdog: CALLBACK_TYPE | None = None
        self._online = False
        self._unlocked = True
        self._last_frame: float | None = None
        self._login_frames = 0
        self._sweep_done = False
        self._wifi_repaired = False
        self.password_rejected = False
        self.bluetooth_last_attempt: str | None = None
        self.bluetooth_frames = 0
        self.bluetooth_triggers = {"advertisement": 0, "timer": 0, "reconnect": 0}
        self.bluetooth_last_connected: str | None = None
        self.wifi_provision_attempts = 0
        self._last_transport = "none"

        # Session limits are held locally and applied when a charge is started;
        # the charger only reports them back while a session is running.
        self.limit_duration: int | None = None
        self.limit_energy: int | None = None
        self.limit_cost: int | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {self.serial}",
            update_interval=None,
            config_entry=entry,
        )
        self.data = self._data

    async def _async_update_data(self) -> dict[str, Any]:
        """Return the current state.

        The charger pushes on its own schedule; this exists so a manual
        refresh cannot fail.
        """
        return self._data

    # --- lifecycle ----------------------------------------------------------

    @callback
    def attach_transport(self, transport: asyncio.DatagramTransport) -> None:
        """Give the coordinator the shared listening socket to answer on."""
        self._transport = transport

    @callback
    def attach_bluetooth(self, transport: "BesenBleTransport") -> None:
        """Enable the Bluetooth fallback for this charger.

        An attempt is queued immediately: the offline watchdog only fires once
        the charger has been heard from, which never happens for a charger that
        is already off the network at startup.
        """
        self._ble = transport
        if not self.entry.options.get(OPT_ENABLE_BLE, False):
            return
        _LOGGER.info(
            "Bluetooth fallback armed for %s; looking for %s in %s seconds, or "
            "as soon as it advertises",
            self.serial,
            transport.name,
            BLE_INITIAL_DELAY,
        )
        self._schedule_bluetooth_attempt(BLE_INITIAL_DELAY)
        # Connect while the charger is advertising: on a weak link it is heard
        # only every few minutes, and an attempt made on an older sighting
        # finds no adapter that can still reach it.
        if unsub := transport.async_track_advertisements(
            self._async_bluetooth_advertised
        ):
            self._ble_unsub.append(unsub)
        self._ble_unsub.append(
            async_track_time_interval(
                self.hass,
                self._async_check_last_advertisement,
                timedelta(seconds=BLE_ADVERT_POLL_INTERVAL),
            )
        )

    async def async_shutdown(self) -> None:
        """Cancel timers and stop touching Home Assistant."""
        for cancel in (self._watchdog, self._ble_retry, *self._ble_unsub):
            if cancel is not None:
                cancel()
        self._watchdog = self._ble_retry = None
        self._ble_unsub.clear()
        self._transport = None
        # Cleared first so a link dropping from here on schedules nothing.
        ble, self._ble = self._ble, None
        if self._ble_task is not None and not self._ble_task.done():
            # A connection completing after unload would hold the charger's
            # only Bluetooth slot.
            self._ble_task.cancel()
            await asyncio.wait({self._ble_task})
        self._ble_task = None
        if ble is not None:
            await ble.async_disconnect()
        await super().async_shutdown()

    # --- inbound ------------------------------------------------------------

    @callback
    def handle_frame(
        self, frame: proto.Frame, addr: tuple[str, int] | None = None
    ) -> None:
        """Process one validated frame, from either transport."""
        self._last_transport = "wifi" if addr is not None else "bluetooth"
        if addr is not None:
            # Reply to wherever the charger speaks from. Some firmwares never
            # send the login broadcast, so it cannot be the only source.
            self._host, self._port = addr
            if self._ble is not None and self._ble.connected:
                # Network is back. Drop the Bluetooth link: these chargers
                # accept one connection at a time.
                self.hass.async_create_task(self._ble.async_disconnect())
        self._last_frame = time.monotonic()
        self._mark_online()

        command = frame.command
        try:
            if command == CMD_PASSWORD_ERROR:
                self._handle_password_error()
            elif command in (CMD_LOGIN_REQUEST, CMD_LOGIN_CONFIRM):
                self._data.update(proto.parse_login(frame.payload))
                self._refresh_device_registry()
                if command == CMD_LOGIN_CONFIRM:
                    # Only sent once the password is accepted.
                    self.password_rejected = False
                elif self.password_rejected and addr is None:
                    # Over Bluetooth the charger repeats its login until one
                    # succeeds, and answering it with the same password
                    # achieves nothing. Over the network the answers keep
                    # its status broadcasts coming, so they continue.
                    self.async_set_updated_data(self._data)
                    return
                # Both halves are acknowledged, but only the confirm half is
                # followed by the settings query. Querying on both, or replying
                # with another 0x8002, keeps the charger repeating the exchange.
                self._login_frames += 1
                if self._login_frames > MAX_LOGIN_FRAMES:
                    if self._login_frames == MAX_LOGIN_FRAMES + 1:
                        _LOGGER.warning(
                            "Charger %s keeps repeating the login exchange; "
                            "no longer answering it. Please open an issue with "
                            "the diagnostics download.",
                            self.serial,
                        )
                else:
                    self._send(CMD_LOGIN_ACK, bytes([1]))
                    if command == CMD_LOGIN_CONFIRM:
                        self.async_request_button_state()
                        self._schedule_settings_sweep()
            elif command == CMD_HEARTBEAT:
                self._send(RESPONSE_FLAG | CMD_HEARTBEAT)
            elif command in (CMD_AC_STATUS, CMD_AC_STATUS_ALT):
                self._data.update(proto.parse_ac_status(frame.payload))
                self._acknowledge(command)
            elif command in (CMD_CHARGE_STATUS, CMD_CHARGE_STATUS_ALT):
                self._data.update(proto.parse_charge_status(frame.payload))
                self._acknowledge(command)
            elif command == CMD_CHARGE_RECORD:
                self._handle_charge_record(frame)
            elif command == CMD_BUTTON_STATE:
                self._data.update(proto.parse_button_state(frame.payload))
            elif command == CMD_SYSTEM_TIME_STATE:
                self._data.update(proto.parse_system_time(frame.payload))
                self._measure_clock_drift()
            elif command == CMD_VERSION_STATE:
                self._data.update(proto.parse_version(frame.payload))
                self._refresh_device_registry()
            elif command == CMD_TEMPERATURE_UNIT_STATE:
                self._data.update(proto.parse_temperature_unit(frame.payload))
            elif command == CMD_WEEKLY_PLAN_STATE:
                self._data.update(proto.parse_weekly_plan(frame.payload))
            elif command == CMD_MONITORING_STATE:
                self._data.update(proto.parse_monitoring(frame.payload))
            elif command == CMD_WIFI_STATE:
                # The passphrase in this frame is dropped by the parser rather
                # than carried into the state machine.
                self._data.update(proto.parse_wifi_info(frame.payload))
            else:
                _LOGGER.debug(
                    "Unhandled command 0x%04X from %s: %s",
                    command,
                    self.serial,
                    frame.payload.hex(),
                )
                self._data.setdefault("unhandled_commands", {})[
                    f"0x{command:04X}"
                ] = frame.payload.hex()
        except Exception:  # noqa: BLE001 - a bad frame must not kill the listener
            _LOGGER.exception(
                "Failed to decode command 0x%04X from %s (payload %s)",
                command,
                self.serial,
                frame.payload.hex(),
            )
            return

        self.async_set_updated_data(self._data)

    @callback
    def _handle_password_error(self) -> None:
        """Ask for the password once the charger has refused it.

        Over the network the charger broadcasts its status regardless, but
        over Bluetooth it sends nothing until a login succeeds.
        """
        if self.password_rejected:
            return
        self.password_rejected = True
        _LOGGER.error(
            "Charger %s rejected the stored password: commands are ignored, and "
            "over Bluetooth no status arrives, until it is corrected",
            self.serial,
        )
        self.entry.async_start_reauth(self.hass)

    def _handle_charge_record(self, frame: proto.Frame) -> None:
        """Record uploads are broadcast until acknowledged."""
        record = proto.parse_charge_record(frame.payload)
        record_id = record.get("record_id")
        if record_id and record_id != self._data.get("last_record_id"):
            self._data["last_record_id"] = record_id
            self._data["last_record"] = record
            self.hass.bus.async_fire(
                EVENT_CHARGE_RECORD, {"serial": self.serial, **record}
            )
        if self.entry.options.get(OPT_ACK_RECORDS, False):
            self._send(RESPONSE_FLAG | CMD_CHARGE_RECORD, bytes([1]))

    @callback
    def _schedule_settings_sweep(self) -> None:
        """Read the settings once the login exchange has gone quiet."""
        if self._sweep_done:
            return
        self._sweep_done = True
        async_call_later(
            self.hass, SETTINGS_SWEEP_DELAY, lambda _now: self.async_request_settings()
        )

    def _refresh_device_registry(self) -> None:
        """Write the charger's self-description onto the device entry.

        The login answer arrives after the entities are registered, so
        ``device_info`` is already stale by then.
        """
        registry = dr.async_get(self.hass)
        # Looked up within this entry: identifiers are no longer unique across
        # config entries, and async_get_device stops working in 2027.8.
        device = next(
            (
                device
                for device in dr.async_entries_for_config_entry(
                    registry, self.entry.entry_id
                )
                if (DOMAIN, self.serial) in device.identifiers
            ),
            None,
        )
        if device is None:
            return
        updates: dict[str, str] = {}
        for field, key in (
            ("manufacturer", "brand"),
            ("model", "model"),
            ("hw_version", "hardware_version"),
            ("sw_version", "firmware_version"),
        ):
            value = self._data.get(key)
            if value and getattr(device, field) != value:
                updates[field] = value
        if device.name != self.device_name:
            updates["name"] = self.device_name
        if updates:
            registry.async_update_device(device.id, **updates)

    def _acknowledge(self, command: int) -> None:
        if command in _ACK_COMMANDS:
            self._send(RESPONSE_FLAG | command, bytes([1]))

    # --- availability -------------------------------------------------------

    @property
    def available(self) -> bool:
        """Whether the charger has been heard from recently."""
        return self._online

    @callback
    def _mark_online(self) -> None:
        was_online = self._online
        self._online = True
        if self._watchdog is not None:
            self._watchdog()
        self._watchdog = async_call_later(
            self.hass, OFFLINE_TIMEOUT, self._mark_offline
        )
        if not was_online:
            _LOGGER.info("Charger %s is online at %s", self.serial, self._host)
            # The login answer ends with a settings query, so only ask
            # directly when the description is already known.
            self._login_frames = 0
            self._sweep_done = False
            self._wifi_repaired = False
            if self._data.get("brand") is None:
                self.async_request_device_info()
            else:
                self.async_request_button_state()

    @callback
    def _mark_offline(self, _now: datetime) -> None:
        self._watchdog = None
        if not self._online:
            return
        self._online = False
        _LOGGER.warning(
            "No data from charger %s for %s seconds, marking unavailable",
            self.serial,
            OFFLINE_TIMEOUT,
        )
        self._schedule_bluetooth_attempt(BLE_FALLBACK_DELAY - OFFLINE_TIMEOUT)
        # Push the change so every entity re-evaluates `available`.
        self.async_update_listeners()

    # --- bluetooth fallback -------------------------------------------------

    @property
    def _reachable(self) -> bool:
        """Whether traffic can flow right now, so Bluetooth has nothing to do.

        Online over Bluetooth with the link down only means the watchdog has
        not caught up with a drop yet.
        """
        return self._online and (
            self._last_transport == "wifi"
            or (self._ble is not None and self._ble.connected)
        )

    @callback
    def _schedule_bluetooth_attempt(self, delay: float, trigger: str = "timer") -> None:
        """Queue a Bluetooth connection attempt while the network is silent."""
        if self._ble is None or not self.entry.options.get(OPT_ENABLE_BLE, False):
            return
        if self._ble_retry is not None:
            self._ble_retry()
        self._ble_retry = async_call_later(
            self.hass, max(1.0, delay), partial(self._async_bluetooth_timer, trigger)
        )

    @callback
    def _async_bluetooth_timer(self, trigger: str, _now: datetime) -> None:
        self._ble_retry = None
        self._start_bluetooth_attempt(trigger)

    @callback
    def _async_bluetooth_advertised(self, info: BluetoothServiceInfoBleak) -> None:
        """Connect on a fresh advertisement, while the charger is listening."""
        ble = self._ble
        if ble is None or ble.connected or self._reachable:
            return
        # Registering replays the last sighting, which can be minutes old.
        if ble.advert_age(info) > BLE_ADVERT_MAX_AGE:
            return
        if (
            self._ble_last_try is not None
            and time.monotonic() - self._ble_last_try < BLE_ADVERT_DEBOUNCE
        ):
            return
        self._start_bluetooth_attempt("advertisement", info)

    @callback
    def _async_check_last_advertisement(self, _now: datetime) -> None:
        """Catch the repeated advertisements Home Assistant does not report."""
        if self._ble is None or self._ble.connected or self._reachable:
            return
        if (info := self._ble.last_advertisement()) is not None:
            self._async_bluetooth_advertised(info)

    @callback
    def handle_ble_disconnect(self) -> None:
        """Retry soon after the Bluetooth link drops on its own.

        Without this the next attempt waits for the offline watchdog. Closing
        the link on purpose (network back, unload) does not land here.
        """
        if self._ble is None or self.hass.is_stopping:
            return
        self._schedule_bluetooth_attempt(BLE_RECONNECT_DELAY, "reconnect")

    @callback
    def _start_bluetooth_attempt(
        self, trigger: str, info: BluetoothServiceInfoBleak | None = None
    ) -> None:
        """Run one attempt in the background, never two at once."""
        if self._ble_task is not None and not self._ble_task.done():
            return
        self.bluetooth_triggers[trigger] += 1
        self._ble_task = self.entry.async_create_background_task(
            self.hass,
            self._async_try_bluetooth(info),
            f"{DOMAIN} {self.serial} bluetooth connect",
        )

    async def _async_try_bluetooth(
        self, info: BluetoothServiceInfoBleak | None = None
    ) -> None:
        """Reach the charger over Bluetooth because the network cannot."""
        # This attempt stands in for any queued one.
        if self._ble_retry is not None:
            self._ble_retry()
            self._ble_retry = None
        self._ble_last_try = time.monotonic()
        self.bluetooth_last_attempt = dt_util.utcnow().isoformat()
        if self._ble is None or self._reachable:
            return
        _LOGGER.debug("Trying to reach %s over Bluetooth", self._ble.name)
        if await self._ble.async_connect(info):
            self.bluetooth_last_connected = dt_util.utcnow().isoformat()
            # Speak first: over UDP the charger broadcasts unprompted, but
            # over Bluetooth it stays silent until asked.
            self.async_request_device_info()
            self.async_request_button_state()
            if self.entry.options.get(OPT_WIFI_AUTO, False):
                await self._async_repair_wifi()
            return
        self._schedule_bluetooth_attempt(BLE_RETRY_INTERVAL)

    async def _async_repair_wifi(self) -> None:
        """Re-send the network credentials over Bluetooth.

        Runs once per outage: repeating it on a charger that still cannot join
        achieves nothing.
        """
        if self._wifi_repaired or not self.entry.options.get(OPT_WIFI_SSID):
            return
        try:
            await self.async_provision_wifi(require_online=False)
        except HomeAssistantError as err:
            # Left unmarked so the next connection retries.
            _LOGGER.warning("Could not re-send Wi-Fi settings to %s: %s", self.serial, err)
            return
        self._wifi_repaired = True

    @callback
    def handle_ble_frame(self, raw: bytes) -> None:
        """Feed a frame that arrived over Bluetooth into the normal path.

        The advertised name carries only the last two bytes of the serial, so
        two chargers can match it. Every frame carries the whole serial, which
        settles identity.
        """
        frame = proto.parse_frame(raw)
        if frame is None:
            return
        self.bluetooth_frames += 1
        if frame.serial != self.serial:
            _LOGGER.error(
                "Bluetooth device answering for %s is charger %s, not %s. "
                "Set the correct Bluetooth address in the integration options.",
                self._ble.name if self._ble else "?",
                frame.serial,
                self.serial,
            )
            if self._ble is not None:
                self.hass.async_create_task(self._ble.async_disconnect())
            return
        self.handle_frame(frame)

    @property
    def bluetooth_retry_pending(self) -> bool:
        """Whether a Bluetooth attempt is queued but has not run yet."""
        return self._ble_retry is not None

    @property
    def transport_name(self) -> str:
        """Which transport is carrying traffic.

        Not simply which link is open: a Bluetooth connection can stay up with
        nothing coming over it.
        """
        if not self._online:
            return "none"
        return self._last_transport

    @property
    def bluetooth_link(self) -> str | None:
        """State of the Bluetooth link itself, whatever is flowing over it."""
        if self._ble is None:
            return None
        return "connected" if self._ble.connected else "disconnected"

    # --- outbound -----------------------------------------------------------

    def _send(self, command: int, payload: bytes = b"") -> None:
        """Send one frame over whichever transport is up."""
        over_ble = self._ble is not None and self._ble.connected
        if not over_ble and (
            self._transport is None or self._host is None or self._port is None
        ):
            _LOGGER.warning(
                "Cannot send command 0x%04X: charger %s has not been heard from yet",
                command,
                self.serial,
            )
            return
        try:
            frame = proto.build_frame(self.serial, self._password, command, payload)
        except proto.ProtocolError as err:
            # Only reachable if the stored credentials became unusable.
            _LOGGER.error("Cannot build frame for %s: %s", self.serial, err)
            self.entry.async_start_reauth(self.hass)
            return
        if over_ble:
            _LOGGER.debug("-> bluetooth cmd=0x%04X payload=%s", command, payload.hex())
            self.hass.async_create_task(self._ble.async_send(frame))
            return
        _LOGGER.debug(
            "-> %s:%s cmd=0x%04X payload=%s",
            self._host,
            self._port,
            command,
            payload.hex(),
        )
        self._transport.sendto(frame, (self._host, self._port))

    def _require_control(self) -> None:
        # Online alone is not enough: after a Bluetooth drop the charger stays
        # online until the watchdog fires, with no link to send on.
        if not self._online or not (
            (self._ble is not None and self._ble.connected) or self._host is not None
        ):
            raise HomeAssistantError(
                f"Charger {self.serial} is not reachable; no command was sent."
            )
        if not self._unlocked:
            raise HomeAssistantError(
                "Commands are locked. Turn the 'Commands unlocked' switch on first."
            )

    # --- commands -----------------------------------------------------------

    @callback
    def async_request_settings(self) -> None:
        """Read back the settings the charger does not send unprompted.

        Sub-operation 0x02 is the read. The clock is absent: only a write
        (0x01) is known for it, and a guessed read could land as a write.
        """
        self._send(CMD_TEMPERATURE_UNIT, bytes([SUBOP_QUERY, 0x00]))
        self._send(CMD_WEEKLY_PLAN, bytes([SUBOP_QUERY, 0x00]))
        if self.entry.options.get(OPT_SYNC_CLOCK, True):
            # Nothing else corrects this clock, and the charger's timestamps
            # all derive from it.
            self._send_clock()

    @callback
    def async_request_device_info(self) -> None:
        """Ask the charger to describe itself.

        The reply carries the current rating, which bounds the current control.
        """
        self._send(CMD_LOGIN)

    @callback
    def async_request_button_state(self) -> None:
        """Ask the charger whether starting from the physical button is enabled."""
        self._send(CMD_BUTTON_CONTROL, bytes([SUBOP_QUERY, 0x00]))

    async def async_start_charge(self) -> None:
        """Start a charging session."""
        self._require_control()
        user_id = self._data.get("session_user") or DEFAULT_USER_ID
        max_current = (
            self._data.get("charging_current")
            or self._data.get("session_max_current")
            or self.rated_current
        )
        charge_id = dt_util.now().strftime("%Y%m%d%H%M") + "".join(
            str(random.randint(0, 9)) for _ in range(4)
        )
        payload = proto.build_start_charge_payload(
            user_id=user_id,
            charge_id=charge_id,
            start_at=self.datetime_to_device_time(dt_util.utcnow()),
            max_current=int(max_current),
            limit_duration=self.limit_duration or LIMIT_UNLIMITED,
            limit_energy=self.limit_energy or LIMIT_UNLIMITED,
            limit_cost=self.limit_cost or LIMIT_UNLIMITED,
        )
        self._send(CMD_START_CHARGE, payload)

    async def async_stop_charge(self) -> None:
        """Stop the running session."""
        self._require_control()
        user_id = self._data.get("session_user") or DEFAULT_USER_ID
        self._send(CMD_STOP_CHARGE, proto.build_stop_charge_payload(user_id))

    async def async_set_max_current(self, current: int) -> None:
        """Set the charging current limit, in amperes."""
        self._require_control()
        limit = self.rated_current
        if not 1 <= current <= limit:
            raise HomeAssistantError(
                f"{current} A is outside the charger's range of 1-{limit} A."
            )
        self._send(CMD_SET_MAX_CURRENT, bytes([SUBOP_SET, int(current)]))
        # Reflect it immediately; the charger only reports the value back while
        # a session is running.
        self._data["charging_current"] = int(current)
        self.async_set_updated_data(self._data)

    @callback
    def _send_clock(self) -> None:
        """Write Home Assistant's time to the charger.

        The charger broadcasts its clock afterwards, which is where the sensor
        picks it up.
        """
        raw = self.datetime_to_device_time(dt_util.utcnow())
        self._send(CMD_SYSTEM_TIME, bytes([SUBOP_SET]) + raw.to_bytes(4, "big"))

    async def async_sync_clock(self) -> None:
        """Set the charger's clock from Home Assistant, on demand."""
        self._require_control()
        self._send_clock()

    async def async_set_temperature_unit(self, unit: str) -> None:
        """Switch the charger's own display between Celsius and Fahrenheit."""
        self._require_control()
        raw = {v: k for k, v in TEMPERATURE_UNITS.items()}.get(unit)
        if raw is None:
            raise HomeAssistantError(f"Unknown temperature unit {unit!r}")
        self._send(CMD_TEMPERATURE_UNIT, bytes([SUBOP_SET, raw]))
        self._data["temperature_unit_raw"] = raw
        self.async_set_updated_data(self._data)

    async def async_provision_wifi(self, require_online: bool = True) -> None:
        """Point the charger at the configured Wi-Fi network."""
        options = self.entry.options
        ssid = options.get(OPT_WIFI_SSID)
        password = options.get(OPT_WIFI_PASSWORD)
        if not ssid:
            raise HomeAssistantError(
                "No Wi-Fi network is configured for this charger. Add the name "
                "and password in the integration options first."
            )
        if require_online:
            self._require_control()
        elif not self._unlocked:
            raise HomeAssistantError("Commands are locked.")

        try:
            payload = proto.build_wifi_payload(
                ssid,
                password or "",
                # Keep whatever the charger last reported, so a non default
                # setup is not quietly rewritten to the broadcast default.
                self._data.get("wifi_server_ip") or "0.0.0.0",
                self._data.get("wifi_server_port") or DEFAULT_LISTEN_PORT,
            )
        except proto.ProtocolError as err:
            raise HomeAssistantError(str(err)) from err

        _LOGGER.info(
            "Sending Wi-Fi settings for network %s to charger %s over %s",
            ssid,
            self.serial,
            self.transport_name,
        )
        self.wifi_provision_attempts += 1
        if self._ble is not None and self._ble.connected:
            # Awaited so a failed write surfaces as an error.
            frame = proto.build_frame(self.serial, self._password, CMD_WIFI, payload)
            if not await self._ble.async_send(frame):
                raise HomeAssistantError(
                    "The Wi-Fi settings could not be written over Bluetooth."
                )
            return
        self._send(CMD_WIFI, payload)

    async def async_set_button_start(self, enabled: bool) -> None:
        """Enable or disable starting a charge from the charger's own button."""
        self._require_control()
        self._send(CMD_BUTTON_CONTROL, bytes([SUBOP_SET, 0 if enabled else 1]))
        self._data["button_start_enabled"] = enabled
        self.async_set_updated_data(self._data)

    # --- local switches -----------------------------------------------------

    @property
    def unlocked(self) -> bool:
        return self._unlocked

    @callback
    def async_set_unlocked(self, unlocked: bool) -> None:
        self._unlocked = unlocked
        self.async_update_listeners()

    @callback
    def async_set_limit(self, key: str, value: int | None) -> None:
        setattr(self, f"limit_{key}", value)
        self.async_update_listeners()

    # --- derived properties -------------------------------------------------

    @property
    def rated_current(self) -> int:
        """Maximum current the charger reports, defaulting to 32 A.

        Taken from the login frame; bounds the current control.
        """
        value = self._data.get("rated_current")
        if isinstance(value, int) and 1 <= value <= 125:
            return value
        return 32

    @property
    def device_name(self) -> str:
        model = self._data.get("model")
        return f"{model} {self.serial}" if model else f"Besen {self.serial}"

    @property
    def is_charging(self) -> bool:
        """Whether a session is running, drawing current or not."""
        return (
            self._data.get("plug_state") == "charging"
            or self._data.get("state") in ACTIVE_STATES
        )

    @property
    def host(self) -> str | None:
        return self._host

    def timestamp(self, key: str) -> datetime | None:
        """Return a device timestamp as an aware datetime.

        The raw value is rendered in UTC+8 to recover the wall clock, then
        stamped with Home Assistant's timezone. See ``DEVICE_TZ_OFFSET``.
        """
        raw = self._data.get(key)
        if not isinstance(raw, int) or raw <= 0:
            return None
        return self.device_time_to_datetime(raw)

    def device_time_to_datetime(self, raw: int) -> datetime | None:
        """Convert one raw device timestamp into local time."""
        try:
            wall_clock = datetime.fromtimestamp(
                raw + DEVICE_TZ_OFFSET, timezone.utc
            ).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
        return wall_clock.replace(tzinfo=dt_util.get_default_time_zone())

    def datetime_to_device_time(self, when: datetime) -> int:
        """Convert local time into the raw form the charger expects."""
        wall_clock = dt_util.as_local(when).replace(tzinfo=timezone.utc)
        return int(wall_clock.timestamp()) - DEVICE_TZ_OFFSET

    @callback
    def _measure_clock_drift(self) -> None:
        """Record the clock difference at the moment it was reported.

        There is no read command for the clock, so the difference has to be
        captured on arrival; recomputing later would just count elapsed time.
        """
        raw = self._data.get("charger_clock")
        if isinstance(raw, int) and raw > 0:
            self._data["clock_drift"] = raw - self.datetime_to_device_time(
                dt_util.utcnow()
            )

    @property
    def temperature_unit(self) -> str | None:
        return TEMPERATURE_UNITS.get(self._data.get("temperature_unit_raw"))

    def duration(self, key: str) -> timedelta | None:
        value = self._data.get(key)
        if not isinstance(value, int):
            return None
        return timedelta(seconds=value)
