import sys
import random
import hid

from abc import ABCMeta, abstractmethod
from pyftdi.ftdi import Ftdi, FtdiError
from pyftdi.i2c import I2cController, I2cPort, I2cGpioPort, I2cNackError, I2cIOError
from usb.core import USBError


class Error(Exception):
    pass


class Device(metaclass=ABCMeta):
    serial = ''
    
    @abstractmethod
    def open(self):
        pass
    
    @abstractmethod
    def close(self):
        pass
    
    @abstractmethod
    def write(self, data: bytes):
        pass
    
    @abstractmethod
    def read(self):
        pass
    
    @staticmethod
    def get_ports(serial=None) -> list:
        return DeviceHid.get_ports(serial) + DeviceI2C.get_ports(serial)


class DeviceHid(Device):
    _USB_VID = 0x31CB
    _USB_PID = [0x00A1, 0x00A2]
    _buf = bytes()
    _length = 0
    
    def __init__(self, serial, vid, pid):
        self.serial = serial
        self._vid = vid
        self._pid = pid
        self._device = hid.device()
        
        self._cid = None
    
    def open(self):
        self._device.open(self._vid, self._pid, self.serial)
        
        init_cmds = [0xFF, 0xFF, 0xFF, 0xFF, 0x86, 0x00, 0x08]
        for i in range(8):
            init_cmds.append(random.randint(0, 255))
        if sys.platform.startswith('win'):
            init_cmds = [0x00, ] + init_cmds
        
        self._device.write(init_cmds)
        r = self._device.read(64, 30)
        if len(r) == 0:
            raise IOError('Open Fail')
        
        self._cid = r[15:19]
    
    def close(self):
        self._device.close()
    
    def write(self, data: bytes):
        length = len(data)
        hid_msg = [0xD0, ] + list(length.to_bytes(2, 'big')) + list(data)
        seq = 0
        while len(hid_msg) > 0:
            hid_msg = self._cid + hid_msg
            if len(hid_msg) > 64:
                send_msg = hid_msg[:64]
                hid_msg = [seq, ] + hid_msg[64:]
                seq += 1
                if seq > 127:
                    seq = 0
            else:
                send_msg = hid_msg[:]
                hid_msg.clear()
            if sys.platform.startswith('win'):
                send_msg = [0x00, ] + send_msg
            self._device.write(send_msg)
    
    def read(self):
        r = self._device.read(64, 30)
        if len(r) <= 0:
            return
        
        # hex_str = [hex(i) for i in r]
        # print(hex_str)
        if r[:4] != self._cid:
            print('cid invalid')
            return
        
        if self._length == 0:
            if r[4] != 0xD0:
                print('command invalid')
                return
            self._length = int.from_bytes(bytes(r[5:7]), 'big')
            self._buf = bytes(r[7:])
        else:
            self._buf += bytes(r[5:])
        if len(self._buf) < self._length:
            return
        
        buf = self._buf[:self._length]
        self._buf = []
        self._length = 0
        
        return buf
    
    @classmethod
    def get_ports(cls, serial=None):
        
        found_ports = list()
        for pid in DeviceHid._USB_PID:
            devices = hid.enumerate(DeviceHid._USB_VID, pid)
            for d in devices:
                if serial is not None:
                    if d['serial_number'] == serial:
                        return [cls(d['serial_number'], DeviceHid._USB_VID, pid)]
                else:
                    found_ports.append(cls(d['serial_number'], DeviceHid._USB_VID, pid))
        
        return found_ports


class DeviceSPI(Device):
    
    def __init__(self, vid, pid, serial, iface, desc):
        self._vid = vid
        self._pid = pid
        self._serial = serial
        self._iface = iface
        self._desc = desc
    
    def open(self):
        pass
    
    def close(self):
        pass
    
    def write(self, data: bytes):
        pass
    
    def read(self):
        pass
    
    @classmethod
    def get_ports(cls, serial=None):
        found_devices = list()
        
        found = Ftdi.find_all([(Ftdi.DEFAULT_VENDOR, 0x6014)])
        for d in found:
            if serial is not None:
                if d[2] == serial:
                    return cls(d[0], d[1], d[2], d[3], d[4])
                else:
                    found_devices.append(cls(d[0], d[1], d[2], d[3], d[4]))
        
        return found_devices


class DeviceI2C(Device):
    _SLAVE = 0x28
    _IRQ = 6
    
    def __init__(self, serial):
        self.serial = serial + '(I2C)'
        self._i2c = I2cController()
        self._i2c.configure('ftdi://::' + serial + '/1', frequency=1000000)
        
        self._device = None  # type: I2cPort
        self._gpio = None  # type: I2cGpioPort
    
    def open(self):
        self._device = self._i2c.get_port(self._SLAVE)
        self._gpio = self._i2c.get_gpio()
        self._gpio.set_direction((1 << self._IRQ), 0)
    
    def close(self):
        try:
            self._i2c.terminate()
        except FtdiError:
            pass
    
    def write(self, data: bytes):
        try:
            self._device.write(list(data))
        except FtdiError as e:
            raise Error(str(e))
        except I2cIOError as e:
            raise Error(str(e))
    
    def read(self):
        if (self._gpio.read() >> self._IRQ) == 1:
            r = self._device.read(8)
            length = int.from_bytes(r[4:8], 'little')
            r += self._device.read(length + 1)
            return r.tobytes()
    
    @classmethod
    def get_ports(cls, serial: str = None):
        found_devices = []
        
        if serial is not None:
            if not serial.endswith('(I2C)'):
                return found_devices
            serial = serial[:-5]
        try:
            found = Ftdi.find_all([(Ftdi.DEFAULT_VENDOR, 0x6014)], nocache=True)
        except USBError:
            return found_devices
        except ValueError:
            return found_devices
        
        for d in found:
            if serial is not None:
                if d[2] == serial:
                    found_devices.append(cls(d[2]))
                    return found_devices
            
            else:
                found_devices.append(cls(d[2]))
        
        return found_devices
