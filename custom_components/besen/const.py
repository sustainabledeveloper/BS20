"""Constants for the Besen EV charger integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "besen"

CONF_SERIAL: Final = "serial"
CONF_PASSWORD: Final = "password"

OPT_ACK_RECORDS: Final = "ack_charge_records"
OPT_SYNC_CLOCK: Final = "sync_clock"
OPT_ENABLE_BLE: Final = "enable_bluetooth"
OPT_WIFI_SSID: Final = "wifi_ssid"
OPT_WIFI_PASSWORD: Final = "wifi_password"
OPT_WIFI_AUTO: Final = "wifi_auto_reprovision"
OPT_BLE_ADDRESS: Final = "ble_address"

DEFAULT_LISTEN_PORT: Final = 28376

#: The charger is considered offline when nothing arrives for this long.
OFFLINE_TIMEOUT: Final = 90

# --- Bluetooth --------------------------------------------------------------

#: Advertising name is this prefix plus the last two bytes of the serial.
BLE_NAME_PREFIX: Final = "ACP#EVSE"
BLE_CONNECT_TIMEOUT: Final = 20

#: Write/notify pairs that carry the protocol, in priority order. A BS20 uses
#: FFE9 to write and FFE4 to listen; the rest are the conventions used by other
#: modules in this family. Chargers expose a stock GATT table containing several
#: unrelated write/notify pairs, so the order matters.
BLE_CHARACTERISTIC_PAIRS: Final = (
    ("ffe9", "ffe4"),
    ("fff2", "fff3"),
    ("ffc1", "ffc2"),
    ("fd01", "fd02"),
)

#: How long the charger must be silent on the network before Bluetooth is
#: tried, and how often to retry once it is.
BLE_FALLBACK_DELAY: Final = 120
#: Delay before the first attempt when the charger has never been seen.
BLE_INITIAL_DELAY: Final = 20
BLE_RETRY_INTERVAL: Final = 60

#: Field layout of the Wi-Fi configuration payload (command 0x010A / 0x810A).
#: The port field reads 28376, the port the charger broadcasts to.
WIFI_PAYLOAD_LEN: Final = 105
WIFI_SSID_SLICE: Final = slice(1, 33)
WIFI_PASSWORD_SLICE: Final = slice(33, 97)
WIFI_SERVER_IP_SLICE: Final = slice(99, 103)
WIFI_SERVER_PORT_SLICE: Final = slice(103, 105)

#: How the charger is currently being reached.
TRANSPORT_OPTIONS: Final = ["wifi", "bluetooth", "none"]

#: Fired on the HA event bus for every completed charging record the charger
#: uploads (command 0x000A).  Consumers can log these to build a session history.
EVENT_CHARGE_RECORD: Final = f"{DOMAIN}_charge_record"

# --- Protocol ---------------------------------------------------------------

FRAME_MAGIC: Final = b"\x06\x01"
FRAME_TAIL: Final = b"\x0f\x02"
FRAME_HEADER_LEN: Final = 21
FRAME_TRAILER_LEN: Final = 4
FRAME_MIN_LEN: Final = FRAME_HEADER_LEN + FRAME_TRAILER_LEN
SERIAL_LEN: Final = 8
PASSWORD_LEN: Final = 6

#: Device -> app commands.  The app answers with ``RESPONSE_FLAG | command``.
CMD_LOGIN_REQUEST: Final = 0x0001
CMD_LOGIN_CONFIRM: Final = 0x0002
CMD_HEARTBEAT: Final = 0x0003
CMD_AC_STATUS: Final = 0x0004
CMD_CHARGE_STATUS: Final = 0x0005
CMD_CHARGE_STATUS_ALT: Final = 0x0006
CMD_CHARGE_RECORD: Final = 0x000A
CMD_AC_STATUS_ALT: Final = 0x000D
CMD_BUTTON_STATE: Final = 0x010D

RESPONSE_FLAG: Final = 0x8000

#: App -> device commands.
CMD_LOGIN_ACK: Final = 0x8001
CMD_LOGIN: Final = 0x8002
CMD_START_CHARGE: Final = 0x8007
CMD_STOP_CHARGE: Final = 0x8008
CMD_SET_MAX_CURRENT: Final = 0x8107
CMD_BUTTON_CONTROL: Final = 0x810D
CMD_SYSTEM_TIME: Final = 0x8101
CMD_VERSION: Final = 0x8106
CMD_TEMPERATURE_UNIT: Final = 0x8112
CMD_WEEKLY_PLAN: Final = 0x810E
CMD_WIFI: Final = 0x810A

#: Device -> app answers for the settings above.
CMD_SYSTEM_TIME_STATE: Final = 0x0101
CMD_VERSION_STATE: Final = 0x0106
CMD_TEMPERATURE_UNIT_STATE: Final = 0x0112
CMD_WEEKLY_PLAN_STATE: Final = 0x010E
CMD_WIFI_STATE: Final = 0x010A
CMD_MONITORING_STATE: Final = 0x0162

#: Sub-operation byte shared by the 0x81xx family.
SUBOP_SET: Final = 0x01
SUBOP_QUERY: Final = 0x02

#: ``0xFFFF`` in a limit field means "no limit".
LIMIT_UNLIMITED: Final = 0xFFFF
#: ``0xFF`` / ``0xFFFF`` in a measurement field means "not available".
SENTINEL_8: Final = 0xFF
SENTINEL_16: Final = 0xFFFF

TEMPERATURE_OFFSET: Final = 20000
TEMPERATURE_SCALE: Final = 0.01

#: Timestamps are a local wall clock encoded as if it were UTC+8. Rendering a
#: raw value in UTC+8 gives the wall clock the charger means.
DEVICE_TZ_OFFSET: Final = 8 * 3600

#: Temperature display unit reported by command 0x0112.
TEMPERATURE_UNITS: Final = {1: "celsius", 2: "fahrenheit"}
TEMPERATURE_UNIT_OPTIONS: Final = ["celsius", "fahrenheit"]

# --- Enumerations -----------------------------------------------------------

STATE_UNKNOWN: Final = "unknown"

#: Plug state, byte 18 of the AC status payload.
PLUG_STATES: Final = {
    1: "not_connected",
    2: "connected",
    4: "charging",
}
PLUG_STATE_OPTIONS: Final = [*PLUG_STATES.values(), STATE_UNKNOWN]

#: Charger state, byte 20 (and byte 34 when it is not 0xFF) of the AC status
#: payload.  The texts behind these keys live in ``strings.json`` and mirror the
#: EVSEMaster wording.
CHARGER_STATES: Final = {
    1: "fault",
    2: "fault",
    3: "fault",
    10: "waiting_for_card",
    11: "waiting_for_button",
    12: "plug_not_connected",
    13: "ready_to_start",
    14: "charging",
    15: "finished_unplug",
    17: "fully_charged",
    18: "stopped_by_ev",
    20: "scheduled",
    255: STATE_UNKNOWN,
}
#: ``14`` means charging only while the plug also reports charging; otherwise
#: the session has started and the car is not drawing current yet.
STATE_CODE_CHARGING: Final = 14
STATE_WAITING_FOR_EV: Final = "waiting_for_ev"

CHARGER_STATE_OPTIONS: Final = sorted(
    {*CHARGER_STATES.values(), STATE_WAITING_FOR_EV}
)

#: States that mean a session is running, whether or not the car draws yet.
ACTIVE_STATES: Final = {"charging", STATE_WAITING_FOR_EV}
#: States that mean something is wrong.
FAULT_STATES: Final = {"fault"}


#: Entities created by 1.x, as
#: ``old key -> (label 1.x stored, new key, or None to remove)``.
#:
#: The list is exhaustive; anything omitted would be left behind as an entity
#: nothing updates. 1.x wrote its labels into the entity registry's name field,
#: which overrides translations, so the label is kept here to tell those labels
#: apart from a user's own rename.
V1_ENTITIES: Final[dict[str, tuple[str, str | None]]] = {
    # controls
    "maxCurrent": ("Max charging current", "charging_current"),
    "lock": ("Unlock", "unlocked"),
    "button": ("Button", "button_start"),
    "startCharging": ("Start Charging", "start_charging"),
    "stopCharging": ("Stop Charging", "stop_charging"),
    # measurements
    "currentVoltageL1": ("Current Voltage L1", "voltage_l1"),
    "currentVoltageL2": ("Current Voltage L2", "voltage_l2"),
    "currentVoltageL3": ("Current Voltage L3", "voltage_l3"),
    "currentCurrentL1": ("Current Current L1", "current_l1"),
    "currentCurrentL2": ("Current Current L2", "current_l2"),
    "currentCurrentL3": ("Current Current L3", "current_l3"),
    "currentPower": ("Charging power", "power"),
    "currentAmount": ("Cumulative Amount", "energy_total"),
    "innerTemperature": ("Inner temperature", "temperature_inner"),
    "outerTemperature": ("Outer temperature", "temperature_outer"),
    # state
    "buttonState": ("Button state", "emergency_stop_raw"),
    "chargingState": ("Charger plug state", "plug_state"),
    "outputState": ("Output state", "output_state_raw"),
    "currentState": ("Current state", "state"),
    # session
    "chargedTime": ("Charging time", "session_duration"),
    "chargePower": ("Currently charged amount", "session_energy"),
    "chargeType": ("Charging type", "charge_type_raw"),
    "startType": ("Starting type", "start_type_raw"),
    "reservationDate": ("Scheduled date", "reservation_time"),
    "chargeStartPower": ("Overall power at charge start", "energy_at_session_start"),
    "maxElectricity": ("Charging max current", "session_max_current"),
    "port": ("Charging port", "port"),
    "chargeId": ("Charging id", "session_id"),
    "chargeCurrentPower": ("Overall charged power", "energy_total_at_session"),
    "startDate": ("Start date", "session_start"),
    # undecoded bytes that were shipped to users; nothing replaces them
    "chargeCurrentState": ("Charging current state", None),
    "missing1": ("Unknown 1", None),
    "missing2": ("Unknown 2", None),
    "missing3": ("Unknown 3", None),
    "missing4": ("Unknown 4", None),
}
