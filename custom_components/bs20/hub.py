
import random
import string
import socket
import logging
import asyncio
from datetime import datetime
import time
from zoneinfo import ZoneInfo

from typing import Any

from homeassistant.helpers import entity_registry as er
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.sensor import SensorStateClass

from .sensor import Current, OtherSensor, Power, Temperature, Voltage, Work

from .number import MaxCurrent
from .switch import Lock
from .button import StartCharging, StopCharging

_LOGGER = logging.getLogger(__name__)

class Hub:

    _devices = {}
    device_data = {}
    _online_timer = None

    def __init__(self, hass: HomeAssistant, serial: str, password: str) -> None:
        self._hass = hass
        self._host = None
        self._serial = serial
        self._password = password
        self.online = False
        self.udp_transport = None
        self._current_userId = None
        self._current_current = None
        self._unlocked = False

    async def init_numbers(self, hass, async_add_entities: AddEntitiesCallback):
        new_devices = []
        instance = MaxCurrent(hass, self, "maxCurrent", "Max charging current")
        self._devices["maxCurrent"] = instance
        self.device_data["maxCurrent"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "number", "max_charging_current")

        async_add_entities(new_devices)
        entity_registry = er.async_get(hass)
        for entity in new_devices:
            entity_registry.async_update_entity(
                entity.entity_id,
                name=entity.friendly_name,
            )
        return
    
    async def init_switches(self, hass, async_add_entities: AddEntitiesCallback):
        new_devices = []
        instance = Lock(hass, self, "lock", "Unlock")
        self._devices["lock"] = instance
        new_devices.append(instance)
        self.remove_sensor(hass, "switch", "unlock")

        async_add_entities(new_devices)
        entity_registry = er.async_get(hass)
        for entity in new_devices:
            entity_registry.async_update_entity(
                entity.entity_id,
                name=entity.friendly_name,
            )
        return
    
    async def init_buttons(self, hass, async_add_entities: AddEntitiesCallback):
        new_devices = []
        instance = StartCharging(hass, self, "startCharging", "Start Charging")
        self._devices["startCharging"] = instance
        new_devices.append(instance)
        self.remove_sensor(hass, "button", "start_charging")

        instance = StopCharging(hass, self, "stopCharging", "Stop Charging")
        self._devices["stopCharging"] = instance
        new_devices.append(instance)
        self.remove_sensor(hass, "button", "stop_charging")

        async_add_entities(new_devices)
        entity_registry = er.async_get(hass)
        for entity in new_devices:
            entity_registry.async_update_entity(
                entity.entity_id,
                name=entity.friendly_name,
            )
        return
    
    def serial(self) -> str:
        return self._serial
    
    def remove_sensor(self, hass, platform, name):
        entity_reg = er.async_get(hass)
        entry = entity_reg.async_get_entity_id("besen", platform, name)
        if entry in entity_reg.entities:
            entity_reg.async_remove(entry)
            hass.states.async_remove(entry)

    async def init_sensors(self, hass, async_add_entities: AddEntitiesCallback):
        new_devices = []
        instance = Voltage(hass, self, "currentVoltageL1", "Current Voltage L1", SensorStateClass.MEASUREMENT)
        self._devices["currentVoltageL1"] = instance
        self.device_data["currentVoltageL1"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "current_voltage_l1")

        instance = Voltage(hass, self, "currentVoltageL2", "Current Voltage L2", SensorStateClass.MEASUREMENT)
        self._devices["currentVoltageL2"] = instance
        self.device_data["currentVoltageL2"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "current_voltage_l2")

        instance = Voltage(hass, self, "currentVoltageL3", "Current Voltage L3", SensorStateClass.MEASUREMENT)
        self._devices["currentVoltageL3"] = instance
        self.device_data["currentVoltageL3"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "current_voltage_l3")

        instance = Current(hass, self, "currentCurrentL1", "Current Current L1", SensorStateClass.MEASUREMENT)
        self._devices["currentCurrentL1"] = instance
        self.device_data["currentCurrentL1"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "current_current_l1")

        instance = Current(hass, self, "currentCurrentL2", "Current Current L2", SensorStateClass.MEASUREMENT)
        self._devices["currentCurrentL2"] = instance
        self.device_data["currentCurrentL2"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "current_current_l2")

        instance = Current(hass, self, "currentCurrentL3", "Current Current L3", SensorStateClass.MEASUREMENT)
        self._devices["currentCurrentL3"] = instance
        self.device_data["currentCurrentL3"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "current_current_l3")

        instance = Power(hass, self, "currentPower", "Charging power", SensorStateClass.MEASUREMENT)
        self._devices["currentPower"] = instance
        self.device_data["currentPower"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "charging_power")

        instance = Work(hass, self, "currentAmount", "Cumulative Amount", SensorStateClass.TOTAL_INCREASING)
        self._devices["currentAmount"] = instance
        self.device_data["currentAmount"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "cumulative_amount")

        instance = Temperature(hass, self, "innerTemperature", "Inner temperature")
        self._devices["innerTemperature"] = instance
        self.device_data["innerTemperature"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "inner_temperature")

        instance = Temperature(hass, self, "outerTemperature", "Outer temperature")
        self._devices["outerTemperature"] = instance
        self.device_data["outerTemperature"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "outer_temperature")

        instance = OtherSensor(hass, self, "buttonState", "Button state")
        self._devices["buttonState"] = instance
        self.device_data["buttonState"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "button_state")

        instance = OtherSensor(hass, self, "chargingState", "Charger plug state")
        self._devices["chargingState"] = instance
        self.device_data["chargingState"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "charger_plug_state")

        instance = OtherSensor(hass, self, "outputState", "Output state")
        self._devices["outputState"] = instance
        self.device_data["outputState"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "output_state")

        instance = OtherSensor(hass, self, "currentState", "Current state")
        self._devices["currentState"] = instance
        self.device_data["currentState"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "current_state")

        #charge states
        instance = OtherSensor(hass, self, "chargedTime", "Charging time")
        self._devices["chargedTime"] = instance
        self.device_data["chargedTime"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "charging_time")

        instance = Work(hass, self, "chargePower", "Currently charged power", SensorStateClass.MEASUREMENT)
        self._devices["chargePower"] = instance
        self.device_data["chargePower"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "currently_charged_power")

        instance = OtherSensor(hass, self, "chargeType", "Charging type")
        self._devices["chargeType"] = instance
        self.device_data["chargeType"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "charging_type")

        instance = OtherSensor(hass, self, "startType", "Starting type")
        self._devices["startType"] = instance
        self.device_data["startType"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "starting_type")

        instance = OtherSensor(hass, self, "reservationDate", "Scheduled date")
        self._devices["reservationDate"] = instance
        self.device_data["reservationDate"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "scheduled_date")

        instance = Work(hass, self, "chargeStartPower", "Overall power at charge start", SensorStateClass.TOTAL)
        self._devices["chargeStartPower"] = instance
        self.device_data["chargeStartPower"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "overall_power_at_charge_start")

        instance = Current(hass, self, "maxElectricity", "Charging max current", SensorStateClass.MEASUREMENT)
        self._devices["maxElectricity"] = instance
        self.device_data["maxElectricity"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "charging_max_current")

        instance = OtherSensor(hass, self, "port", "Charging port")
        self._devices["port"] = instance
        self.device_data["port"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "charging_port")

        instance = OtherSensor(hass, self, "chargeId", "Charging id")
        self._devices["chargeId"] = instance
        self.device_data["chargeId"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "charging_id")

        instance = Work(hass, self, "chargeCurrentPower", "Overall charged power", SensorStateClass.TOTAL_INCREASING)
        self._devices["chargeCurrentPower"] = instance
        self.device_data["chargeCurrentPower"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "overall_charged_power")

        # instance = OtherSensor(hass, self, "chargeCurrentState", "Charging current state")
        # self._devices["chargeCurrentState"] = instance
        # self.device_data["chargeCurrentState"] = None
        # new_devices.append(instance)

        instance = OtherSensor(hass, self, "startDate", "Start date")
        self._devices["startDate"] = instance
        self.device_data["startDate"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "start_date")

        #missings
        instance = OtherSensor(hass, self, "missing1", "Unknown 1")
        self._devices["missing1"] = instance
        self.device_data["missing1"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "unknown_1")

        instance = OtherSensor(hass, self, "missing2", "Unknown 2")
        self._devices["missing2"] = instance
        self.device_data["missing2"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "unknown_2")

        instance = OtherSensor(hass, self, "missing3", "Unknown 3")
        self._devices["missing3"] = instance
        self.device_data["missing3"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "unknown_3")

        instance = OtherSensor(hass, self, "missing4", "Unknown 4")
        self._devices["missing4"] = instance
        self.device_data["missing4"] = None
        new_devices.append(instance)
        self.remove_sensor(hass, "sensor", "unknown_4")

        async_add_entities(new_devices)
        entity_registry = er.async_get(hass)
        for entity in new_devices:
            entity_registry.async_update_entity(
                entity.entity_id,
                name=entity.friendly_name,
            )

    @property
    def available(self) -> bool:
        return self.online
    
    async def _reset_online_timer(self):
        if self._online_timer:
            self._online_timer.cancel()

        self._online_timer = asyncio.create_task(self._set_offline_after_timeout())

    async def _set_offline_after_timeout(self):
        await asyncio.sleep(60)  # Wait for 60 seconds
        self.online = False

    async def decode_data(self, data: bytes, addr: tuple) -> None:
        self._port = addr[1]
        
        calculatedLen = data[2] << 8 + data[3] & 0xff
        if len(data) >= calculatedLen and len(data) >= 25 and data[0] == 0x06 and data[1] == 0x01:
            serial = data[5:13].hex()
            command = data[19] * 256 + data[20]
            newData = data[21:len(data)-4]
            await self.process_command(command, serial, newData, addr[0])

    async def process_command(self, command: int, serial: string, data: bytes, host: str):
        await self._reset_online_timer()
        self.online = True

        if command == 1:
            await self.process_login(data)
            self._host = host
            await self.login_request()
        elif command == 2:
            await self.process_login(data)
            await self.login_response_response()
        elif command == 3:
            await self.keep_alive_response()
        elif command == 4 or command == 13:
            await self.process_single_ac_status(data)
        elif command == 5 or command == 6:
            await self.process_charging_status(data)

    def trim_bytes(self, data: bytes) -> bytes:
        return data.rstrip(b'\x00')

    def int_from_bytes(self, data: bytes) -> int:
        return int.from_bytes(data, byteorder='big')

    def int_from_bytes_little(self, data: bytes) -> int:
        return int.from_bytes(data, byteorder='little')

    async def process_login(self, data: bytes):
        type = data[0] & 0xff
        brand = self.trim_bytes(data[1:17]).decode('ascii')
        model = self.trim_bytes(data[17:33]).decode('ascii')
        hardware_version = self.trim_bytes(data[33:49]).decode('ascii')
        output_power = int.from_bytes(data[49:53], byteorder='little')
        output_electricity = data[53]
        hotline = self.trim_bytes(data[54:70]).decode('ascii')

        return

    async def login_request(self):
        cmd = self.get_tg_short(self._serial, self._password, 0x8002)
        await self.send_cmd(cmd)
        return

    async def login_response_response(self):
        cmd = self.get_tg(self._serial, self._password, 0x8001, [1])
        await self.send_cmd(cmd)
        return

    async def keep_alive_response(self):
        cmd = self.get_tg(self._serial, self._password, 32771, [])
        await self.send_cmd(cmd)
        return
    
    def update_sensor(self, key: str, value):
        if key not in self.device_data or value != self.device_data[key]:
            self.device_data[key] = value
            self._devices[key].async_update_callback(value)

    async def process_single_ac_status(self, data: bytes):
        lineId = data[0]

        currentVoltage = round(self.int_from_bytes(data[1:3]) * 0.1, 2)
        self.update_sensor("currentVoltageL1", currentVoltage)

        currentElectricity = round(self.int_from_bytes(data[3:5]) * 0.01, 2)
        self.update_sensor("currentCurrentL1", currentElectricity)

        currentPower = self.int_from_bytes(data[5:9]) / 1000.
        self.update_sensor("currentPower", currentPower)

        currentAmount = self.int_from_bytes(data[9:13]) * 0.01
        self.update_sensor("currentAmount", currentAmount)

        innerTemp = self.int_from_bytes(data[13:15])
        if innerTemp == 255:
            innerTemp = -1
        else:
            innerTemp = (innerTemp - 20000) * 0.01
        self.update_sensor("innerTemperature", innerTemp)

        outerTemp = self.int_from_bytes(data[15:17])
        if outerTemp == 255:
            outerTemp = -1
        else:
            outerTemp = (outerTemp - 20000) * 0.01
        self.update_sensor("outerTemperature", outerTemp)

        emergencyBtnState = data[17]
        self.update_sensor("buttonState", emergencyBtnState)

        chargingState = data[18]
        if chargingState == 1:
            chargingState = "Not connected"
        elif chargingState == 2:
            chargingState = "Connected"
        elif chargingState == 4:
            chargingState = "Charging"
        self.update_sensor("chargingState", chargingState)

        outputState = data[19]
        self.update_sensor("outputState", outputState)

        currentState = data[20]

        bVoltage = round(self.int_from_bytes(data[25:27]) * 0.1, 2)
        self.update_sensor("currentVoltageL2", bVoltage)

        bElectricity = round(self.int_from_bytes(data[27:29]) * 0.01, 2)
        self.update_sensor("currentCurrentL2", bElectricity)

        cVoltage = round(self.int_from_bytes(data[29:31]) * 0.1, 2)
        self.update_sensor("currentVoltageL3", cVoltage)

        cElectricity = round(self.int_from_bytes(data[31:33]) * 0.01, 2)
        self.update_sensor("currentCurrentL3", cElectricity)

        if len(data) > 33:
            currentState = data[34]

        if currentState == 1 or currentState == 2 or currentState == 3:
            currentState = "ERROR"
        elif currentState == 10:
            currentState = "Wait for the swipe to start."
        elif currentState == 11:
            currentState = "Wait for the button to activate."
        elif currentState == 12:
            currentState =="Unable to charge, the charging plug is not connected, please start charging after connecting."
        elif currentState == 13:
            currentState = "The device is connected, please press START to enter the charging status."
        elif currentState == 14:
            if chargingState == 4:
                currentState = "Currently charging."
            elif chargingState == 2:
                currentState = "Charging has started, waiting for the EV to be ready."
        elif currentState == 15:
            currentState = "Charging is completed, please unplug the charging plug."
        elif currentState == 17:
            currentState = "100% Full charge."
        elif currentState == 18:
            currentState == "Stopped by EV."
        elif currentState == 20:
            currentState = "Charging reservation."
        elif currentState == 255:
            currentState = "--"

        self.update_sensor("currentState", currentState)
        
        #missing indexes: 21-24 32-33 35+
        missing2 = data[21:25].hex()
        self.update_sensor("missing2", missing2)

        missing3 = data[32:34].hex()
        self.update_sensor("missing3", missing3)

        if len(data) > 35:
            missing4 = data[35:len(data)].hex()
            self.update_sensor("missing4", missing4)

        return

    async def process_charging_status(self, data: bytes):
        port = data[0]
        self.update_sensor("port", port)

        # currentState = data[1]
        # if len(data) > 74:
        #     currentState = data[74]
        # self.device_data["chargeCurrentState"] = currentState
        # self._devices["chargeCurrentState"].async_update_callback(currentState)

        chargeId = self.trim_bytes(data[2:18]).decode('ascii')
        self.update_sensor("chargeId", chargeId)

        startType = data[18]
        self.update_sensor("startType", startType)

        chargeType = data[19]
        self.update_sensor("chargeType", chargeType)

        chargeParam1 = self.int_from_bytes(data[20:22])
        chargeParam2 = self.int_from_bytes(data[22:24])
        chargeParam3 = self.int_from_bytes(data[24:26])

        reservationDate = self.int_from_bytes(data[26:30])
        if reservationDate == 0:
            reservationDate = "--"
        else:
            reservationDate = self.convert_bad_timestamp(reservationDate, self._hass.config.time_zone)
        self.update_sensor("reservationDate", reservationDate)

        self._current_userId = self.trim_bytes(data[30:46]).decode('ascii')

        self._current_current = data[46]
        self.update_sensor("maxElectricity", self._current_current)
        self.update_sensor("maxCurrent", self._current_current)

        startDate = self.convert_bad_timestamp(self.int_from_bytes(data[47:51]), self._hass.config.time_zone)
        self.update_sensor("startDate", startDate)

        chargedTime = self.seconds_to_hhmmss(self.int_from_bytes(data[51:55]))
        self.update_sensor("chargedTime", chargedTime)

        chargeStartPower = self.int_from_bytes(data[55:59]) * 0.01
        self.update_sensor("chargeStartPower", chargeStartPower)

        chargeCurrentPower = self.int_from_bytes(data[59:63]) * 0.01
        self.update_sensor("chargeCurrentPower", chargeCurrentPower)

        chargePower = self.int_from_bytes(data[63:67]) * 0.01
        self.update_sensor("chargePower", chargePower)

        chargePrice = self.int_from_bytes_little(data[67:71]) * 0.01

        feeType = data[71]

        chargeFee = self.int_from_bytes_little(data[72:74]) * 0.01

        #missin indexes: 
        if len(data) > 47:
            missing1 = data[74:len(data)].hex()
            self.update_sensor("missing1", missing1)
        return

    def get_tg_short(self, serial: string, password: string, cmd: int) -> bytes:
        length = 25
        tg = bytearray(length)

        tg[0] = 0x06
        tg[1] = 0x01
        tg[2] = (length >> 8) & 0xff
        tg[3] = length % 256
        tg[4] = 0x00
        #serialNo
        hex_bytes = bytes.fromhex(serial)
        tg[5 : 5 + len(hex_bytes)] = hex_bytes
        #pass
        ascii_bytes = password.encode('ascii')
        tg[13 : 13 + len(ascii_bytes)] = ascii_bytes
        tg[19] = (cmd >> 8) & 0xff
        tg[20] = cmd % 256

        crc = 0
        for index in range(21):
            crc = crc + (tg[index] & 0xff)

        crc = crc % 65536
        tg[21] = (crc >> 8)
        tg[22] = (crc % 256)
        tg[23] = 0x0f
        tg[24] = 0x02
        return tg

    def get_tg(self, serial: string, password: string, cmd: int, data: bytes) -> bytes:
        length = 25 + max(len(data), 16)
        tg = bytearray(length)

        tg[0] = 0x06
        tg[1] = 0x01
        tg[2] = (length >> 8) & 0xff
        tg[3] = length % 256
        tg[4] = 0x00
        #serialNo
        hex_bytes = bytes.fromhex(serial)
        tg[5 : 5 + len(hex_bytes)] = hex_bytes
        #pass
        ascii_bytes = password.encode('ascii')
        tg[13 : 13 + len(ascii_bytes)] = ascii_bytes
        tg[19] = (cmd >> 8) & 0xff
        tg[20] = cmd % 256

        #data
        tg[21 : 21 + len(data)] = data

        crc = 0
        for index in range(length - 4):
            crc = crc + (tg[index] & 0xff)

        crc = crc % 65536
        tg[length - 4] = (crc >> 8)
        tg[length - 3] = (crc % 256)
        tg[length - 2] = 0x0f
        tg[length - 1] = 0x02
        return tg

    async def send_cmd(self, tg: bytes):
        if self._host != None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(tg, (self._host, self._port))
        return
    
    def convert_bad_timestamp(self, bad_timestamp: int, home_assistant_timezone: str) -> str:
        utc_time = datetime.fromtimestamp(bad_timestamp + 7 * 60 * 60, ZoneInfo('UTC'))

        home_assistant_tz = ZoneInfo(home_assistant_timezone)
        local_time_ha = utc_time.astimezone(home_assistant_tz)

        formatted_time = local_time_ha.strftime('%Y-%m-%d %H:%M')

        return formatted_time
    
    def seconds_to_hhmmss(self, seconds: int) -> str:
        hours = seconds // 3600
        remainder = seconds % 3600
        minutes = remainder // 60
        seconds = remainder % 60
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    
    async def stop_charge(self):
        if self._unlocked and self._current_userId != None:
            data = bytearray(47)
            data[0] = 1
            ascii_bytes = self._current_userId.encode('ascii')
            data[1:1 + len(ascii_bytes)] = ascii_bytes
            for idx in range(len(ascii_bytes), 16):
                data[idx] = 32
            cmd = self.get_tg(self._serial, self._password, 32776, data)
            await self.send_cmd(cmd)
        return
    
    async def start_charge(self):
        if self._unlocked:
            chargeId = datetime.now().strftime("%Y%m%d%H%M") + ''.join(str(random.randint(0, 9)) for _ in range(4))
            reservationDate = int(time.time() * 1000) // 1000
            param1 = 65535
            param2 = 65535
            param3 = 65535

            idx = 0
            data = bytearray(47)
            data[0] = 1
            idx = idx + 1

            ascii_bytes = self._current_userId.encode('ascii')
            data[idx:idx + len(ascii_bytes)] = ascii_bytes
            for i in range(len(ascii_bytes), 16):
                data[i] = 32
            idx = idx + 16
            
            ascii_bytes = chargeId.encode('ascii')
            data[idx:idx + len(ascii_bytes)] = ascii_bytes
            idx = idx + len(ascii_bytes)

            data[idx] = 0
            idx = idx + 1

            data[idx] = (reservationDate >> 24) & 0xff
            data[idx + 1] = (reservationDate >> 16) & 0xff
            data[idx + 2] = (reservationDate >> 8) & 0xff
            data[idx + 3] = reservationDate % 256
            idx = idx + 4

            data[idx] = 1
            idx = idx + 1

            data[idx] = 1
            idx = idx + 1

            data[idx] = (param1 >> 8) & 0xff
            data[idx + 1] = param1 % 256
            idx = idx + 2

            data[idx] = (param2 >> 8) & 0xff
            data[idx + 1] = param2 % 256
            idx = idx + 2

            data[idx] = (param3 >> 8) & 0xff
            data[idx + 1] = param3 % 256
            idx = idx + 2

            data[idx] = self._current_current
            idx = idx + 1

            cmd = self.get_tg(self._serial, self._password, 32775, data)
            await self.send_cmd(cmd)

    async def set_max_current(self, current: int):
        if self._unlocked:
            if current < 1 or current > 32:
                return
            data = bytearray(2)
            data[0] = 1
            data[1] = int(current)
            cmd = self.get_tg(self._serial, self._password, 33031, data)
            await self.send_cmd(cmd)

    async def set_unlocked(self, unlocked: bool):
        self._unlocked = unlocked
        self._devices["lock"].async_update_callback(self._unlocked)

    def is_unlocked(self) -> bool:
        return self._unlocked