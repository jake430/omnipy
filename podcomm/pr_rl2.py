pr_rileylink.pyimport re
import subprocess
import struct
import time
from .packet_radio import PacketRadio, TxPower
from .definitions import *
from enum import IntEnum
from threading import Event
from .exceptions import PacketRadioError
from .manchester import ManchesterCodec

from bluepy.btle import Peripheral, Scanner, BTLEException

XGATT_BATTERYSERVICE_UUID = "180f"
XGATT_BATTERY_CHAR_UUID = "2a19"
RILEYLINK_SERVICE_UUID = "0235733b-99c5-4197-b856-69219c2a3845"
RILEYLINK_DATA_CHAR_UUID = "c842e849-5028-42e2-867c-016adada9155"
RILEYLINK_RESPONSE_CHAR_UUID = "6e6c7910-b89e-43a5-a0fe-50c5e2b81f4a"

class Command(IntEnum):
    GET_STATE = 1
    GET_VERSION = 2
    GET_PACKET = 3
    SEND_PACKET = 4
    SEND_AND_LISTEN = 5
    UPDATE_REGISTER = 6
    RESET = 7
    LED = 8
    READ_REGISTER = 9
    SET_MODE_REGISTERS = 10
    SET_SW_ENCODING = 11
    SET_PREAMBLE = 12
    RADIO_RESET_CONFIG = 13


class Response(IntEnum):
    PROTOCOL_SYNC = 0x00
    UNKNOWN_COMMAND = 0x22
    RX_TIMEOUT = 0xaa
    COMMAND_INTERRUPTED = 0xbb
    COMMAND_SUCCESS = 0xdd


class Register(IntEnum):
    SYNC1 = 0x00
    SYNC0 = 0x01
    PKTLEN = 0x02
    PKTCTRL1 = 0x03
    PKTCTRL0 = 0x04
    ADDR = 0x05
    CHANNR = 0x06
    FSCTRL1 = 0x07
    FSCTRL0 = 0x08
    FREQ2 = 0x09
    FREQ1 = 0x0a
    FREQ0 = 0x0b
    MDMCFG4 = 0x0c
    MDMCFG3 = 0x0d
    MDMCFG2 = 0x0e
    MDMCFG1 = 0x0f
    MDMCFG0 = 0x10
    DEVIATN = 0x11
    MCSM2 = 0x12
    MCSM1 = 0x13
    MCSM0 = 0x14
    FOCCFG = 0x15
    BSCFG = 0x16
    AGCCTRL2 = 0x17
    AGCCTRL1 = 0x18
    AGCCTRL0 = 0x19
    FREND1 = 0x1a
    FREND0 = 0x1b
    FSCAL3 = 0x1c
    FSCAL2 = 0x1d
    FSCAL1 = 0x1e
    FSCAL0 = 0x1f
    TEST1 = 0x24
    TEST0 = 0x25
    PATABLE0 = 0x2e


class Encoding(IntEnum):
    NONE = 0
    MANCHESTER = 1
    FOURBSIXB = 2

# 0xC0 +10
# 0xC8 +7
# 0x84 +5
# 0x60 0
# 0x62 -1
# 0x2C -5
# 0x34 -10
# 0x1D -15
# 0x0E -20
# 0x12 -30

g_rl_address = None
g_rl_version = None
g_rl_v_major = None
g_rl_v_minor = None

class RileyLink(PacketRadio):
    def __init__(self):
        self.peripheral = None
        self.data_handle = None
        self.logger = getLogger()
        self.packet_logger = get_packet_logger()
        self.address = g_rl_address
        self.service = None
        self.response_handle = None
        self.notify_event = Event()
        self.initialized = False
        self.manchester = ManchesterCodec()
        self.version = None

    def connect(self, force_initialize=False):
        try:
            already_connected = self._connect_internal()
            if not already_connected or force_initialize:
                self.init_radio(force_initialize)

        except BTLEException as be:
            if self.peripheral is not None:
                self.disconnect()
            raise PacketRadioError("Error while connecting") from be
        except Exception as e:
            raise PacketRadioError("Error while connecting") from e

    def _connect_internal(self):
        try:
            if self.peripheral is not None:
                try:
                    state = self.peripheral.getState()
                    if state == "conn":
                        return True
                except BTLEException:
                    pass

            if self.address is None:
                self.initialized = False
                self.address = self._findRileyLink()

            self.peripheral = Peripheral()
            self._connect_retry(3)

            self.service = self.peripheral.getServiceByUUID(RILEYLINK_SERVICE_UUID)
            self.peripheral = self.service.peripheral

            data_char = self.service.getCharacteristics(RILEYLINK_DATA_CHAR_UUID)[0]
            self.data_handle = data_char.getHandle()

            char_response = self.service.getCharacteristics(RILEYLINK_RESPONSE_CHAR_UUID)[0]
            self.response_handle = char_response.getHandle()

            response_notify_handle = self.response_handle + 1
            notify_setup = b"\x01\x00"
            self.peripheral.writeCharacteristic(response_notify_handle, notify_setup)
            return False

        except BTLEException as be:
            if self.peripheral is not None:
                self.disconnect()
            raise PacketRadioError("Error while connecting") from be
        except Exception as e:
            raise PacketRadioError("Error while connecting") from e

    def disconnect(self, ignore_errors=True):
        try:
            if self.peripheral is None:
                self.logger.info("Already disconnected")
                return
            self.logger.info("Disconnecting..")
            if self.response_handle is not None:
                response_notify_handle = self.response_handle + 1
                notify_setup = b"\x00\x00"
                self.peripheral.writeCharacteristic(response_notify_handle, notify_setup)
        except Exception as e:
            if not ignore_errors:
                raise PacketRadioError("Error while disconnecting") from e
        finally:
            try:
                if self.peripheral is not None:
                    self.peripheral.disconnect()
                    self.peripheral = None
            except BTLEException as be:
                if ignore_errors:
                    self.logger.exception("Ignoring btle exception during disconnect")
                else:
                    raise PacketRadioError("Error while disconnecting") from be
            except Exception as e:
                raise PacketRadioError("Error while disconnecting") from e

    def get_info(self):
        try:
            self.connect()
            bs = self.peripheral.getServiceByUUID(XGATT_BATTERYSERVICE_UUID)
            bc = bs.getCharacteristics(XGATT_BATTERY_CHAR_UUID)[0]
            bch = bc.getHandle()
            battery_value = int(self.peripheral.readCharacteristic(bch)[0])
            self.logger.debug("Battery level read: %d", battery_value)
            version, v_major, v_minor = self._read_version()
            return { "battery_level": battery_value, "mac_address": self.address,
                    "version_string": version, "version_major": v_major, "version_minor": v_minor }
        except Exception as e:
            raise PacketRadioError("Error communicating with RileyLink") from e
        finally:
            self.disconnect()

    def _read_version(self):
        global g_rl_version, g_rl_v_major, g_rl_v_minor
        version = None
        try:
            if g_rl_version is not None:
                return g_rl_version, g_rl_v_major, g_rl_v_minor
            else:
                response = self._command(Command.GET_VERSION)
                if response is not None and len(response) > 0:
                    version = response.decode("ascii")
                    self.logger.debug("RL reports version string: %s" % version)
                    g_rl_version = version

            if version is None:
                return "0.0", 0, 0

            try:
                m = re.search(".+([0-9]+)\\.([0-9]+)", version)
                if m is None:
                    raise PacketRadioError("Failed to parse firmware version string: %s" % version)

                g_rl_v_major = int(m.group(1))
                g_rl_v_minor = int(m.group(2))
                self.logger.debug("Interpreted version major: %d minor: %d" % (g_rl_v_major, g_rl_v_minor))

                return g_rl_version, g_rl_v_major, g_rl_v_minor

            except Exception as ex:
                raise PacketRadioError("Failed to parse firmware version string: %s" % version) from ex

        except PacketRadioError:
            raise
        except Exception as e:
            raise PacketRadioError("Error while reading version") from e

    def init_radio(self, force_init=False):
        try:
            if force_init:
                self.initialized = False
                self.logger.debug("force initialize, resetting RL")
                self.peripheral.writeCharacteristic(self.data_handle, bytes([1, Command.RESET]), withResponse=False)
                self.logger.debug("disconnecting")
                self.disconnect()
                time.sleep(3)
                self.logger.debug("reconnecting")
                self._connect_internal()

            if self.version is None:
                self.version = self._read_version()

            v_str, v_major, v_minor = self.version
            if v_major < 2:
                self.logger.error("Firmware version is below 2.0")
                raise PacketRadioError("Unsupported RileyLink firmware %s" % v_str)

            if not force_init:
                if v_major == 2 and v_minor < 3:
                    response = self._command(Command.READ_REGISTER, bytes([Register.PKTLEN, 0x00]))
                else:
                    response = self._command(Command.READ_REGISTER, bytes([Register.PKTLEN]))
                    if response is not None and len(response) > 0 and response[0] == 0x50:
                        self.initialized = True
                        return

            self._command(Command.RADIO_RESET_CONFIG)
            self._command(Command.SET_SW_ENCODING, bytes([Encoding.NONE]))
            self._command(Command.SET_PREAMBLE, bytes([0x66, 0x65]))

            self._command(Command.UPDATE_REGISTER, bytes([Register.SYNC1, 0xA5]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.SYNC0, 0x5A]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.PKTLEN, 0x50]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.PKTCTRL1, 0x20]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.PKTCTRL0, 0x00]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.ADDR, 0x00]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.CHANNR, 0x00]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.FSCTRL1, 0x0F]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.FSCTRL0, 0x00]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.FREQ2, 0x12]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.FREQ1, 0x14]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.FREQ0, 0x50]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.MDMCFG4, 0xFA])) # CA
            self._command(Command.UPDATE_REGISTER, bytes([Register.MDMCFG3, 0xB9])) # BC
            self._command(Command.UPDATE_REGISTER, bytes([Register.MDMCFG2, 0x12])) # 02
            self._command(Command.UPDATE_REGISTER, bytes([Register.MDMCFG1, 0x41])) # 40
            self._command(Command.UPDATE_REGISTER, bytes([Register.MDMCFG0, 0xF0])) # 11
            self._command(Command.UPDATE_REGISTER, bytes([Register.DEVIATN, 0x36])) # 54
            self._command(Command.UPDATE_REGISTER, bytes([Register.MCSM2, 0x07]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.MCSM1, 0x30]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.MCSM0, 0x19])) # 19
            self._command(Command.UPDATE_REGISTER, bytes([Register.FOCCFG, 0x00])) # 17
            self._command(Command.UPDATE_REGISTER, bytes([Register.BSCFG, 0x6C]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.AGCCTRL2, 0x43]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.AGCCTRL1, 0x40]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.AGCCTRL0, 0x91]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.FREND1, 0x56]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.FREND0, 0x10])) # 0x00
            self._command(Command.UPDATE_REGISTER, bytes([Register.FSCAL3, 0xE9])) # 0xEA
            self._command(Command.UPDATE_REGISTER, bytes([Register.FSCAL2, 0x2A]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.FSCAL1, 0x00]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.FSCAL0, 0x1F]))
            #self._command(Command.UPDATE_REGISTER, bytes([Register.TEST2, 0x88]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.TEST1, 0x31])) # 0x35
            self._command(Command.UPDATE_REGISTER, bytes([Register.TEST0, 0x09]))
            self._command(Command.UPDATE_REGISTER, bytes([Register.PATABLE0, 0x60])) # ?C8

            tx_mode = bytes([0x01,
                             Register.FREQ2, 0x12,
                             Register.FREQ1, 0x14,
                             Register.FREQ0, 0x56,
                             ])

            rx_mode = bytes([0x02,
                             Register.FREQ2, 0x12,
                             Register.FREQ1, 0x14,
                             Register.FREQ0, 0x71,
                             ])

            # self._command(Command.SET_MODE_REGISTERS, tx_mode)
            # self._command(Command.SET_MODE_REGISTERS, rx_mode)

            response = self._command(Command.GET_STATE)
            if response != b"OK":
                raise PacketRadioError("Rileylink state is not OK. Response returned: %s" % response)

            self.initialized = True

        except Exception as e:
            raise PacketRadioError("Error while initializing rileylink radio: %s", e)

    # def set_f(self, cf, ifb, of):
    #     self._command(Command.UPDATE_REGISTER, bytes([Register.FREQ2, cf >> 16 & 0xFF]))
    #     self._command(Command.UPDATE_REGISTER, bytes([Register.FREQ1, cf >> 8 & 0xFF]))
    #     self._command(Command.UPDATE_REGISTER, bytes([Register.FREQ0, cf & 0xFF]))
    #     self._command(Command.UPDATE_REGISTER, bytes([Register.FSCTRL1, ifb]))
    #     self._command(Command.UPDATE_REGISTER, bytes([Register.FSCTRL0, of & 0xFF]))
    #     self.freq_c = cf
    #     self.freq_if = ifb
    #     self.freq_of = of
    #     e_cf = cf*366.2109375
    #     e_ifb = ifb*23437.5
    #     e_of = of*1464.84375
    #     e_rx = e_cf + e_ifb + e_of
    #     self.logger.debug(f"Setting cf: {cf}, if: {ifb}, of: {of}")
    #     self.logger.debug(f"Parameters TX: {e_cf:.0f} RX: {e_rx:.0f} (IF: {e_ifb:.0f} OF: {e_of:.0f})")

    def tx_up(self):
        pass

    def tx_down(self):
        pass

    def set_tx_power(self, tx_power):
        pass

    def get_packet(self, timeout=5.0):
        try:
            self.connect()
            result = self._command(Command.GET_PACKET, struct.pack(">BL", 0, int(timeout * 1000)),
                                 timeout=float(timeout)+0.5)
            if result is not None:
                return result[0:2] + self.manchester.decode(result[2:])
            else:
                return None
        except Exception as e:
            raise PacketRadioError("Error while getting radio packet") from e

    def send_and_receive_packet(self, packet, repeat_count, delay_ms, timeout_ms, retry_count, preamble_ext_ms):
        try:
            self.connect()
            data = self.manchester.encode(packet)
            result = self._command(Command.SEND_AND_LISTEN,
                                  struct.pack(">BBHBLBH",
                                              0,
                                              repeat_count,
                                              delay_ms,
                                              0,
                                              timeout_ms,
                                              retry_count,
                                              preamble_ext_ms)
                                              + data,
                                  timeout=30)
            if result is not None:
                return result[0:2] + self.manchester.decode(result[2:])
            else:
                return None
        except Exception as e:
            raise PacketRadioError("Error while sending and receiving data") from e

    def send_packet(self, packet, repeat_count, delay_ms, preamble_extension_ms):
        try:
            self.connect()
            data = self.manchester.encode(packet)
            result = self._command(Command.SEND_PACKET, struct.pack(">BBHH", 0, repeat_count, delay_ms,
                                                                   preamble_extension_ms) + data,
                                  timeout=30)
            return result
        except Exception as e:
            raise PacketRadioError("Error while sending data") from e

    def _set_amp(self, index=None):
        pass

    def _findRileyLink(self):
        global g_rl_address
        scanner = Scanner()
        g_rl_address = None
        self.logger.debug("Scanning for RileyLink")
        retries = 10
        while g_rl_address is None and retries > 0:
            retries -= 1
            for result in scanner.scan(1.0):
                if result.getValueText(7) == RILEYLINK_SERVICE_UUID:
                    self.logger.debug("Found RileyLink")
                    g_rl_address = result.addr

        if g_rl_address is None:
            raise PacketRadioError("Could not find RileyLink")

        return g_rl_address

    def _connect_retry(self, retries):
        while retries > 0:
            retries -= 1
            self.logger.info("Connecting to RileyLink, retries left: %d" % retries)

            try:
                self.peripheral.connect(self.address)
                self.logger.info("Connected")
                break
            except BTLEException as btlee:
                self.logger.warning("BTLE exception trying to connect: %s" % btlee)
                try:
                    os.system("sudo killall -9 bluepy-helper")
                    # p = subprocess.Popen(["ps", "-A"], stdout=subprocess.PIPE)
                    # out, err = p.communicate()
                    # for line in out.splitlines():
                    #     if "bluepy-helper" in line:
                    #         pid = int(line.split(None, 1)[0])
                    #         os.kill(pid, 9)
                    #         break
                except:
                    self.logger.warning("Failed to kill bluepy-helper")
                time.sleep(1)

    def _command(self, command_type, command_data=None, timeout=10.0):
        try:
            if command_data is None:
                data = bytes([1, command_type])
            else:
                data = bytes([len(command_data) + 1, command_type]) + command_data

            self.peripheral.writeCharacteristic(self.data_handle, data, withResponse=True)

            if not self.peripheral.waitForNotifications(timeout):
                raise PacketRadioError("Timed out while waiting for a response from RileyLink")

            response = self.peripheral.readCharacteristic(self.data_handle)

            if response is None or len(response) == 0:
                raise PacketRadioError("RileyLink returned no response")
            else:
                if response[0] == Response.COMMAND_SUCCESS:
                    return response[1:]
                elif response[0] == Response.COMMAND_INTERRUPTED:
                    self.logger.warning("A previous command was interrupted")
                    return response[1:]
                elif response[0] == Response.RX_TIMEOUT:
                    return None
                else:
                    raise PacketRadioError("RileyLink returned error code: %02X. Additional response data: %s"
                                         % (response[0], response[1:]), response[0])
        except PacketRadioError:
            raise
        except Exception as e:
            raise PacketRadioError("Error executing command") from e