from typing import Dict, Optional, Any, Union, Callable

import hid
import random
import sys
import threading
from enum import IntEnum
from queue import Queue, Empty
from time import sleep

from multipledispatch import dispatch

"""
SISOUL NFC API
"""


class Message:
    CMD_HEADER_SIZE = 9
    RSP_HEADER_SIZE = 8
    
    _TYPES = {'cmd': b'\x01', 'rsp': b'\x02', 'evt': b'\x03'}
    _GID = dict(system=b'\xD9', nfc=b'\xE9')
    _CID = dict(system=dict(buzzer=b'\x21', led=b'\x22', info=b'\x23', set_gpio=b'\x24', error=b'\31',
                            set_serial=b'\xE0', debug=b'\xF0', download=b'\xFE'),
                nfc=dict(discovery=b'\x11',
                         get_tag_info=b'\x21', read=b'\x22', write=b'\x23', removal=b'\x24', ndef_read=b'\x25',
                         ndef_write=b'\x26',
                         mfc_auth=b'\x31', mfc_read=b'\x32', mfc_write=b'\x33', mfc_dec=b'\x34', mfc_inc=b'\x35',
                         mfc_restore=b'\x36', mfc_transfer=b'\x37',
                         apdu_transfer=b'\x41', raw=b'\x42', emv=b'\x51', conf_reactive=b'\xC0'))
    
    _type = None
    _gid = None
    _cid = None
    _param1 = None
    _param2 = None
    _length = 0
    _payload = None
    _bcc = None
    _bytes = None
    _status = None
    
    @dispatch()
    def __init__(self):
        self._bytes = None
    
    @dispatch(bytes)
    def __init__(self, byte):
        self._bytes = byte
    
    @dispatch(str, str, str)
    def __init__(self, t, gid, cid):
        self._init_cmd(t, gid, cid)
    
    @dispatch(str, str, str, bytes, bytes)
    def __init__(self, t, gid, cid, param1, param2):
        self._init_cmd(t, gid, cid, param1, param2)
    
    @dispatch(str, str, str, bytes, bytes, bytes)
    def __init__(self, t, gid, cid, param1, param2, payload):
        self._init_cmd(t, gid, cid, param1, param2, payload)
    
    @dispatch(str, str, str, int)
    def __init__(self, t, gid, cid, status):
        self._init_rsp(t, gid, cid, status)
    
    @dispatch(str, str, str, int, bytes)
    def __init__(self, t, gid, cid, status, payload):
        self._init_rsp(t, gid, cid, status, payload)
    
    def __add__(self, other):
        if self._bytes is None:
            return other
        else:
            return self._bytes + other
    
    def __iadd__(self, other):
        if self._bytes is None:
            self._bytes = b''
        self._bytes += other
        return self
    
    def _init_cmd(self, t, gid, cid, param1=b'\x00', param2=b'\x00', payload=None):
        self._type = t
        self._gid = gid
        self._cid = cid
        self._param1 = param1
        self._param2 = param2
        self._payload = payload
        if payload is not None:
            self._length = len(payload)
        else:
            self._length = 0
    
    def _init_rsp(self, t, gid, cid, status, payload=None):
        self._type = t
        self._gid = gid
        self._cid = cid
        self._status = status
        self._payload = payload
        if payload is not None:
            self._length = len(payload)
        else:
            self._length = 0
    
    def set_type(self, t):
        self._type = t
    
    def set_gid(self, gid):
        self._gid = gid
    
    def set_cid(self, cid):
        self._cid = cid
    
    def set_param1(self, param1):
        self._param1 = param1
    
    def set_param2(self, param2):
        self._param2 = param2
    
    def set_status(self, status):
        self._status = status
    
    def set_payload(self, payload):
        self._payload = payload
        if payload is not None:
            self._length = len(payload)
        else:
            self._length = 0
    
    def check_complete_bytes(self):
        if self._bytes is None:
            return False
        
        t = self._get_key(self._bytes[0:1], self._TYPES)
        if t is None:
            raise ValueError('Type(0x%02X) is Invalid'.format(self._bytes[0:1]))
        
        length = len(self._bytes)
        if t == 'cmd':
            header_size = self.CMD_HEADER_SIZE
        else:
            header_size = self.RSP_HEADER_SIZE
        
        if length < header_size + 1:
            return False
        
        gid = self._get_key(self._bytes[1:2], self._GID)
        if gid is None:
            raise ValueError('Gid(0x%02X) is Invalid'.format(self._bytes[1:2]))
        
        cid = self._get_key(self._bytes[2:3], self._CID[gid])
        if cid is None:
            raise ValueError('Cid(0x%02X) is Invalid'.format(self._bytes[2:3]))
        
        if t == 'cmd':
            lc = int.from_bytes(self._bytes[5:9], 'little')
        else:
            lc = int.from_bytes(self._bytes[4:8], 'little')
        
        if length < (lc + header_size + 1):
            return False
        
        if self._make_bcc(self._bytes[0:-1]).to_bytes(1, 'little') != self._bytes[-1:]:
            raise ValueError('BCC is incorrect')
        
        return True
    
    @dispatch(bytes, dict)
    def _get_key(self, b, d):
        for k, v in d.items():
            if v == b:
                return k
        return None
    
    @staticmethod
    def _make_bcc(b: bytes) -> int:
        bcc = 0
        for i in b:
            bcc ^= i
        return bcc
    
    def encode(self):
        if self._bytes is None:
            lc = self._length.to_bytes(4, 'little')
            self._bytes = self._TYPES[self._type] + self._GID[self._gid] + self._CID[self._gid][self._cid]
            if self._type == 'cmd':
                self._bytes += self._param1 + self._param2
            else:
                self._bytes += self._status.to_bytes(1, 'little')
            self._bytes += lc
            if self._payload is not None:
                self._bytes += self._payload
            
            self._bytes += self._make_bcc(self._bytes).to_bytes(1, 'little')
        
        return self._bytes
    
    def decode(self):
        if self._type is None:
            self._type = self._get_key(self._bytes[0:1], self._TYPES)
            self._gid = self._get_key(self._bytes[1:2], self._GID)
            self._cid = self._get_key(self._bytes[2:3], self._CID[self._gid])
            if self._type == 'cmd':
                self._param1 = self._bytes[3:4]
                self._param2 = self._bytes[4:5]
                self._length = int.from_bytes(self._bytes[5:9], 'little')
                if self._length > 0:
                    self._payload = self._bytes[self.CMD_HEADER_SIZE:self.CMD_HEADER_SIZE + self._length]
            else:
                self._status = self._bytes[3]
                self._length = int.from_bytes(self._bytes[4:8], 'little')
                if self._length > 0:
                    self._payload = self._bytes[self.RSP_HEADER_SIZE:self.RSP_HEADER_SIZE + self._length]
        
        if self._type == 'cmd':
            return {'type': self._type, 'gid': self._gid, 'cid': self._cid,
                    'param1': self._param1, 'param2': self._param2, 'payload': self._payload}
        else:
            return {'type': self._type, 'gid': self._gid, 'cid': self._cid, 'status': self._status,
                    'payload': self._payload}
    
    def pprint(self):
        self.decode()
        if self._type == 'cmd':
            s = '[CMD][' + self._gid.upper() + '][' + self._cid.upper() + ']' + \
                '[' + self._param1.hex().upper() + '][' + self._param2.hex().upper() + ']'
        
        else:
            s = '[' + self._type.upper() + '][' + self._gid.upper() + '][' + self._cid.upper() + ']' + \
                '[' + Command.STATUS(self._status).name + ']'
        
        s += 'Payload(' + str(self._length) + '): '
        if self._length > 0:
            for i in range(self._length):
                if i % 24 == 0:
                    s += '\n\t' + ' '.join('%02X' % b for b in self._payload[i:i + 24])
        return s


class Command:
    """
    NFC Control API
    
    """
    
    TIME_OUT = 20
    _USB_VID = 0x31CB
    _USB_PID = 0x00A1
    
    class STATUS(IntEnum):
        SUCCESS = 0x00  #: Success.
        OK = 0x01  #: Okay!! but it's not complete process.
        FAILURE = 0x11  #: Failure
        SYSTEM_MEMORY = 0x12  #: Out of memory in SMCP
        UNSUPPORTED_FUNCTION = 0x13  #: Command not supported.
        REJECT_COMMAND = 0x14
        """
        Rejected command from SMCP.\n
        ex) Send command the discovery start if already started.
        """
        INVALID_PARAM = 0x15  #: parameter is invalid.
        TIMED_OUT = 0x16  #: Response timed out.
        
        UNSUPPORTED_GROUP = 0x21  #: the GID is not supported.
        UNSUPPORTED_COMMAND = 0x22  #: the Command is not supported.
        UNSUPPORTED_PARAM = 0x23  #: the Parameter is not supported.
        UNSUPPORTED_TYPE = 0x24  #: the Type is not supported.
        
        TRANSFER_BCC = 0x31  #: BCC error.
        TRANSFER_PACKET = 32  #: Packet error.
        
        NOT_AUTH = 0x41  #: Need Authenticate from Remote Device.
        FROM_REMOTE_DEVICE = 0x42  #: Error from Remote Device.
        NDEF_READ_FAIL = 0x43  #: NDEF Read fail.
        NDEF_WRITE_FAIL = 0x44  #: NDEF Write fail.
        
        LOST_REMOTE_DEVICE = 0x51  #: Lost Remote Device.
        
        GOING_TO_RESET = 0x80  #: SMCP reset.
        
        UNKNOWN = 0xFF  #: Unknown Error.
    
    class NfcTech(IntEnum):
        """
        NFC Technology Protocol
        """
        ISO14443A = 0x10  #: ISO14443A (NFC-A)
        ISO14443B = 0x20  #: ISO14443B (NFC-B)
        ISO18092 = 0x40  #: ISO18092 (NFC-F)
        ISO15693 = 0x80  #: ISO15693 (NFC-V)
    
    class NfcTagType(IntEnum):
        """
        NFC Tag Type.
        """
        TYPE1 = 0x01  #: Type1 Tag is compatible Topaz
        TYPE2 = 0x02  #: Type2 Tag is compatible Mifare Family (UL, ULC, Classic)
        TYPE3 = 0x04  #: Type3 Tag is compatible Felica.
        TYPE4 = 0x08  #: Type4 Tag is compatible Application Type Card (VISA, MASTER, T-Money, Cashbee..)
        TYPE5 = 0x10  #: Type5 Tag is compatible ICODE SLI(x), Tag-It HF-I
    
    class NfcTagAppType1(IntEnum):
        """
        NFC Tag Type1 Applications.
        """
        TOPAZ_STATIC = 0x10  #: Topaz static memory structure.
        TOPAZ_DYNAMIC = 0x20  #: Topaz dynamic memory structure.
    
    class NfcTagAppTypeMiFareClassic(IntEnum):
        """
        Mifare Classic Applications.
        """
        MIFARE_MINI = 0x11  #: Mifare Mini.
        MIFARE_1K = 0x12  #: Mifare Classic 1K
        MIFARE_4K = 0x13  #: Mifare Classic 4K
        MIFARE_PLUS_2K = 0x14  #: Mifare Plus 2K
        MIFARE_PLUS_4K = 0x15  #: Mifare Plus 4K
        MIFARE_PLUS_SL2_4K = 0x16  #: Mifare Plus SL2 4K
        MIFARE_PLUS_SL2_2K = 0x17  #: Mifare Plus SL2 2K
    
    class NfcTagAppType2(IntEnum):
        """
        NFC Tag Type2 Applications.
        """
        MIFARE_UL = 0x21  #: Mifare Ultralight
        MIFARE_INFINEON_1K = 0x22  # Mifare Infineon.
        MIFARE_ULC = 0x23  #: Mifare Ultralight C
    
    class NfcDiscovery:
        _d = dict(app_type=None, tech=None, type=None, colbit=False, uid=None)
        _b = None
        
        def __init__(self, b):
            self._b = b
        
        def decode(self):
            self._d['app_type'] = self._b[0]
            self._d['tech'] = self._b[1]
            self._d['type'] = self._b[2]
            self._d['colbit'] = self._b[3]
            self._d['uid'] = self._b[5:(5 + self._b[4])]
            
            return self._d
    
    class Error(Exception):
        pass
    
    def __init__(self) -> None:
        self._s = None
        self.port = None
        self._cid = None
        self._fwdn_callback = None
        self._recv_thread = None
        self._evt_thread = None
        self._terminate = True
        
        self._SMP_TYPE_CMD = b'\x01'
        self._SMP_TYPE_RSP = b'\x02'
        self._SMP_TYPE_EVT = b'\x03'
        
        self._q_rsp = Queue()
        self._q_evt = Queue()
        
        self.mode = 0
        
        self._callbacks = dict(discovery=None, error=None, debug=None)
    
    def _receive_thread(self):
        buf = bytes()
        length = 0
        while not self._terminate:
            try:
                r = self._s.read(64, 10)
                if len(r) > 0:
                    # hex_str = [hex(i) for i in r]
                    # print(hex_str)
                    if r[:4] != self._cid:
                        print('cid invalid')
                        continue
                    if length == 0:
                        if r[4] != 0xD0:
                            print('command invalid')
                            continue
                        length = int.from_bytes(bytes(r[5:7]), 'big')
                        buf = bytes(r[7:])
                    else:
                        buf += bytes(r[5:])
                    if len(buf) < length:
                        continue
                    buf = buf[:length]
                    length = 0
                    smp = Message(buf)
                    try:
                        if smp.check_complete_bytes():
                            msg = smp.decode()
                            if msg['type'] == 'rsp':
                                self._q_rsp.put(smp)
                            elif msg['type'] == 'evt':
                                self._q_evt.put(smp)
                    except ValueError:
                        print("Packet invalid")
            except IOError as e:
                print(e)
                # print('Read Error')
                self._terminate = True
                self.close()
                break
    
    def _event_thread(self):
        while not self._terminate:
            try:
                smp = self._q_evt.get(timeout=0.1)
                msg = smp.decode()
                debug_func = self._callbacks['debug']
                if callable(debug_func):
                    debug_func(smp.pprint())
                if msg['gid'] == 'nfc' and msg['cid'] == 'discovery':
                    discovered_func = self._callbacks['discovery']
                    if callable(discovered_func):
                        if msg['status'] == self.STATUS.SUCCESS:
                            disc = self.NfcDiscovery(msg['payload'])
                            discovered_func(msg['status'], disc.decode())
                        else:
                            discovered_func(msg['status'], dict())
                elif msg['gid'] == 'system' and msg['cid'] == 'debug':
                    debug_func = self._callbacks['debug']
                    if callable(debug_func):
                        debug_func(msg['payload'].decode('utf-8'))
                elif msg['gid'] == 'system' and msg['cid'] == 'error':
                    error_func = self._callbacks['error']
                    if callable(error_func):
                        error_func(msg['status'], msg['payload'])
            except Empty:
                pass
    
    def _send_receive(self, send):
        while not self._q_rsp.empty():  # clear queue.
            self._q_rsp.get()
        
        s = send.decode()
        debug_func = self._callbacks['debug']
        if callable(debug_func):
            debug_func(send.pprint())
        
        try:
            smp_msg = send.encode()
            length = len(smp_msg)
            hid_msg = [0xD0, ] + list(length.to_bytes(2, 'big')) + list(send.encode())
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
                self._s.write(send_msg)
            recv = self._q_rsp.get(timeout=self.TIME_OUT)
            r = recv.decode()
            if callable(debug_func):
                debug_func(recv.pprint())
            
            if s['gid'] != r['gid'] or s['cid'] != r['cid']:
                err_msg = Message('rsp', s['gid'], s['cid'], Command.STATUS.FAILURE)
                if callable(debug_func):
                    debug_func(err_msg.pprint())
                return err_msg
            return recv
        
        except Empty:
            to_msg = Message('rsp', s['gid'], s['cid'], Command.STATUS.TIMED_OUT)
            if callable(debug_func):
                debug_func(to_msg.pprint())
            return to_msg
    
    def get_ports(self, serial=None) -> list:
        """
        Retrieve serial numbers of SMCP-IV
        
        :param serial: specified serial number of SMCP-IV.
            If you specify a serial number, it will find and return the SMCP-IV for that serial number.\n
            Default value is None.
        :type serial: str
        :return: list of serial numbers of SMCP-IV.
        :rtype: list
        
        .. seealso:: :func:`open`
        """
        
        devices = hid.enumerate(self._USB_VID, self._USB_PID)
        found_ports = list()
        for d in devices:
            if serial is not None:
                if d['serial_number'] == serial:
                    found_ports.append(d['serial_number'])
            else:
                found_ports.append(d['serial_number'])
        return found_ports
    
    def is_connected(self) -> bool:
        """
        Check the connection with SMCP-IV.
        
        :return: True or False
        :rtype: bool
        """
        return not self._terminate
    
    def set_callbacks(self, discovery: Callable[[int, dict], None] = None,
                      error: Callable[[int, bytes], None] = None,
                      debug: Callable[[int, str], None] = None) -> None:
        
        """
        Register event callback functions.
        
        :param discovery: Callback function for discovery event.\n
            Called when a card is found or lost.
        :type discovery: Callable
        :param error: Callback function for error event.
        :type error: Callable
        :param debug: Callback function for debug messages sent from SMCP-IV.
        :type debug: Callable
        :return: None
        """
        self._callbacks['discovery'] = discovery
        self._callbacks['error'] = error
        self._callbacks['debug'] = debug
    
    def open(self, port) -> None:
        """
        Connect USB HID Class for SMCP-IV.
        
        :param port: serial number of SMCP-IV.
        :type port: str
        :return: None
        :raise: :class:`IOError`
        
        .. seealso:: :func:`get_ports`
        """
        
        if port is None:
            raise self.Error('Port is None')
        self._s = hid.device()
        self._s.open(self._USB_VID, self._USB_PID, port)
        
        init_cmds = [0xFF, 0xFF, 0xFF, 0xFF, 0x86, 0x00, 0x08]
        for i in range(8):
            init_cmds.append(random.randint(0, 255))
        if sys.platform.startswith('win'):
            init_cmds = [0x00, ] + init_cmds
        self._s.write(init_cmds)
        r = self._s.read(64, 30)
        if len(r) == 0:
            raise IOError('Read Fail')
        
        self._cid = r[15:19]
        
        self._terminate = False
        self.port = port
        self._evt_thread = threading.Thread(target=self._event_thread)
        self._evt_thread.daemon = True
        self._evt_thread.start()
        
        self._recv_thread = threading.Thread(target=self._receive_thread)
        self._recv_thread.daemon = True
        self._recv_thread.start()
    
    def close(self) -> None:
        """
        Disconnect USB HID Class connection for SMCP-IV.
        
        :return: None
        """
        if self._s is not None:
            if self.mode == 1:
                self.discovery(start=False)
            elif self.mode == 2:
                self.emv(2)
            self._terminate = True
            if self._recv_thread is not None:
                self._recv_thread.join()
            if self._evt_thread is not None:
                self._evt_thread.join()
            self._s.close()
            self._s = None
    
    def do_download(self, stream, fwdn_callback):
        data = stream.read()
        page = 0
        while len(data) > 128:
            b_page = page.to_bytes(2, 'little')
            smp = Message('cmd', 'system', 'download', b_page[0:1], b_page[1:2], data[0:128])
            smp = self._send_receive(smp)
            r = smp.decode()
            if r['status'] != self.STATUS.SUCCESS:
                return False
            data = data[128:]
            if fwdn_callback is not None:
                fwdn_callback(128)
            page += 1
        
        b_page = page.to_bytes(2, 'little')
        smp = Message('cmd', 'system', 'download', b_page[0:1], b_page[1:2], data)
        smp = self._send_receive(smp)
        r = smp.decode()
        if r['status'] != self.STATUS.SUCCESS:
            return False
        smp = Message('cmd', 'system', 'download', b'\xFF', b'\xFF')
        smp = self._send_receive(smp)
        r = smp.decode()
        if r['status'] != self.STATUS.GOING_TO_RESET:
            return False
        if fwdn_callback is not None:
            fwdn_callback(len(data))
        
        return True
    
    def firmware_download(self, stream, fwdn_callback) -> bool:
        """
        Download the firmware for SMCP-IV.
        
        :param stream: stream of firmware binary
        :type stream: typing.io
        :param fwdn_callback: callback function. \n
            This function will be called with the length transmitted when one packet is complete.
        :type fwdn_callback: function
        :return: If the firmware was successfully transferred, it will return True. \n
            If it fails, it will return False.
        :rtype: bool
        
        :raise: :class:`IOError`
        """
        smp = Message('cmd', 'system', 'download')
        smp = self._send_receive(smp)
        r = smp.decode()
        if r['status'] == self.STATUS.GOING_TO_RESET:
            self.mode = 0
            self.close()
            sleep(0.5)
            retry = 100
            while retry > 0:
                ports = self.get_ports(self.port)
                if len(ports) > 0:
                    break
                sleep(0.1)
                retry -= 1
            if retry == 0:
                return False
            try:
                self.open(self.port)
            except IOError as e:
                print(e)
                return False
            
            return self.do_download(stream, fwdn_callback)
        return False
    
    def buzzer(self, hz, ms) -> STATUS:
        """
        buzzer control in SMCP-IV.
        
        :param hz: 1: 1khz, 2: 2khz, 3: 2.7khz
        :type hz: int
        :param ms: The time the buzzer rings for milliseconds (100 ~ 65535)
        :type ms: int
        :return: :class:`STATUS`
        """
        if hz < 1 or hz > 4:
            return self.STATUS.INVALID_PARAM
        if ms < 100 or ms > 65535:
            return self.STATUS.INVALID_PARAM
        
        smp = Message('cmd', 'system', 'buzzer', int(0).to_bytes(1, 'little'), hz.to_bytes(1, 'little'),
                      ms.to_bytes(2, 'little'))
        smp = self._send_receive(smp)
        r = smp.decode()
        return r['status']
    
    def led(self, blue, red) -> STATUS:
        """
        led control in SMCP-IV.
        
        :param blue: Blue led control. 1: on, 0: off
        :param red: Red led control. 1: on, 0: off
        :return: :class:`STATUS`
        """
        if blue != 1 or blue != 0:
            return self.STATUS.INVALID_PARAM
        if red != 1 or red != 0:
            return self.STATUS.INVALID_PARAM
        
        smp = Message('cmd', 'system', 'led', blue.to_bytes(1, 'little'), red.to_bytes(1, 'little'))
        smp = self._send_receive(smp)
        r = smp.decode()
        return r['status']
    
    def set_gpio(self, i_num, b_level) -> STATUS:
        smp = Message('cmd', 'system', 'set_gpio', i_num.to_bytes(1, 'little'), b_level.to_bytes(1, 'little'))
        smp = self._send_receive(smp)
        r = smp.decode()
        return r['status']
    
    def get_dev_info(self) -> Dict[str, Union[int, Any]]:
        """
        Get version information of SMCP-IV.
        
        :return: status: :class:`STATUS`\n
            If status is :class:`STATUS.SUCCESS`, it has the values defined below:
            \t name: The name of SMCP-IV. This value is always SMCP-IV.\n
            \t major: It is a major version of the SMCP-IV firmware.\n
            \t minor: It is a minor version of the SMCP-IV firmware.\n
            \t build: It is a build number of the SMCP-IV firmware version.\n
            \t date: This is the date the SMCP-IV firmware was built.\n
            \t time: This is the time the SMCP-IV firmware was built.
        :rtype: dict
        """
        smp = Message('cmd', 'system', 'info')
        smp = self._send_receive(smp)
        r = smp.decode()
        ret = dict(status=r['status'])
        if r['status'] == self.STATUS.SUCCESS:
            ret['name'] = r['payload'][0:9].decode(encoding='ascii')
            ret['major'] = int.from_bytes(r['payload'][9:10], 'little')
            ret['minor'] = int.from_bytes(r['payload'][10:11], 'little')
            ret['build'] = int.from_bytes(r['payload'][11:15], 'little')
            ret['date'] = r['payload'][15:27].decode(encoding='ascii')
            ret['time'] = r['payload'][27:36].decode(encoding='ascii')
        return ret
    
    def set_serial(self, str_serial) -> bool:
        smp = Message('cmd', 'system', 'set_serial', b'\x00', b'\x00', bytes(str_serial.encode('ascii')))
        smp = self._send_receive(smp)
        r = smp.decode()
        if r['status'] != self.STATUS.GOING_TO_RESET:
            self.mode = 0
            return False
        return True
    
    def conf_reactive(self, is_set=True) -> STATUS:
        """
        Set Reactivate.
        
        :param is_set: If True, the SMCP-IV attempts to reactivate the remote device to determine
            if it has been disappeared.\n
            If False, the SMCP-IV does not reactivate after the remote device is first activated.\n
            In this case, you do not know if the remote device has disappeared.
        :type is_set: bool
        :return: :class:`STATUS`
        """
        smp = Message('cmd', 'nfc', 'conf_reactive', is_set.to_bytes(1, 'little'), b'\x00')
        smp = self._send_receive(smp)
        r = smp.decode()
        return r['status']
    
    def discovery(self, tech=(NfcTech.ISO14443A | NfcTech.ISO14443B | NfcTech.ISO18092 | NfcTech.ISO15693),
                  start=True) -> STATUS:
        """
        Starts or ends a remote device search.
        
        :param tech: The NFC technology of the remote device to discover.\n
            Default value is (NfcTech.ISO14443A | NfcTech.ISO14443B | NfcTech.ISO18092 | NfcTech.ISO15693)
        :type tech: NfcTech
        :param start: If True, start the discover. Or False to stop the discover.
        :type start: bool
        :return: :class:`STATUS`
        """
        smp = Message('cmd', 'nfc', 'discovery', tech.to_bytes(1, 'little'), start.to_bytes(1, 'little'))
        smp = self._send_receive(smp)
        r = smp.decode()
        if start and r['status'] == self.STATUS.SUCCESS:
            self.mode = 1
        elif not start and r['status'] == self.STATUS.SUCCESS:
            self.mode = 0
        return r['status']
    
    def read(self, block) -> Dict[str, Optional[Any]]:
        """
        Reads one block of the card.
        
        :param block: The block number of card.
        :type block: int
        :return: status: :class:`STATUS`\n
            If status is :class:`STATUS.SUCCESS`, it has the values defined below:
            \t data(bytes): Data read from the card.
        :rtype: dict
        
        .. seealso:: :func:`write` :func:`ndef_read` :func:`mifare_read`
        .. note:: This command corresponds to Type 1, Type 2 (except Mifare Classic), and Type 3 cards.
        """
        b = block.to_bytes(2, 'little')
        smp = Message('cmd', 'nfc', 'read', b[0:1], b[1:2])
        smp = self._send_receive(smp)
        r = smp.decode()
        ret = dict(status=r['status'])
        if r['status'] == self.STATUS.SUCCESS:
            ret['data'] = r['payload']
        return ret
    
    def write(self, block, data) -> STATUS:
        """
        Writes one block of the card.
        
        :param block: The block number of card.
        :type block: int
        :param data: Data to write the card.
        :type data: bytes
        :return: :class:`STATUS`
        
        .. seealso:: :func:`read` :func:`ndef_write` :func:`mifare_write`
        .. note:: This command corresponds to Type 1, Type 2 (except Mifare Classic), and Type 3 cards.
        """
        b = block.to_bytes(2, 'little')
        smp = Message('cmd', 'nfc', 'write', b[0:1], b[1:2], data)
        smp = self._send_receive(smp)
        r = smp.decode()
        return r['status']
    
    def ndef_read(self) -> Dict[str, Optional[Any]]:
        """
        Reads NDEF data from the card.
        
        :return: status: :class:`STATUS`\n
            If status is :class:`STATUS.SUCCESS`, it has the values defined below:
            \t ndef(bytes): NDEF data read from the card.
        :rtype: dict
        
        .. seealso:: :func:`ndef_write` :func:`read` :func:`mifare_read`
        .. note:: This command only corresponds to the Nfc Forum Tag type.
        """
        smp = Message('cmd', 'nfc', 'ndef_read')
        smp = self._send_receive(smp)
        r = smp.decode()
        ret = dict(status=r['status'])
        if r['status'] == self.STATUS.SUCCESS:
            ret['ndef'] = r['payload']
        return ret
    
    def ndef_write(self, ndef) -> STATUS:
        """
        Writes NDEF data to the card.
        
        :param ndef: NDEF data to write the card
        :type ndef: bytes
        :return: :class:`STATUS`
        
        .. seealso:: :func:`ndef_read` :func:`write` :func:`mifare_write`
        .. note:: This command only corresponds to the Nfc Forum Tag type.
        """
        smp = Message('cmd', 'nfc', 'ndef_write')
        smp.set_payload(ndef)
        smp = self._send_receive(smp)
        r = smp.decode()
        return r['status']
    
    def apdu_tranceive(self, capdu) -> Dict[str, Optional[Any]]:
        """
        Exchange APDUs.
        
        :param capdu: The APDU to transfer to the card.
        :type capdu: bytes
        :return: status: :class:`STATUS`\n
            If status is :class:`STATUS.SUCCESS`, it has the values defined below:
            \t data(bytes): APDU received from card
        
        .. note:: This command only corresponds to the application cards.
        """
        smp = Message('cmd', 'nfc', 'apdu_transfer')
        smp.set_payload(capdu)
        smp = self._send_receive(smp)
        r = smp.decode()
        ret = dict(status=r['status'])
        if r['status'] == self.STATUS.SUCCESS:
            ret['data'] = r['payload']
        return ret
    
    def raw(self, txdata) -> Dict[str, Optional[Any]]:
        smp = Message('cmd', 'nfc', 'raw')
        smp.set_payload(txdata)
        smp = self._send_receive(smp)
        r = smp.decode()
        ret = dict(status=r['status'])
        if r['status'] == self.STATUS.SUCCESS:
            ret['data'] = r['payload']
        return ret
    
    def mifare_auth(self, blk_no, key_type, key) -> STATUS:
        """
        Attempt MiFare card authentication.
        
        :param blk_no: The block number of Mifare card.
        :type blk_no: int
        :param key_type: The key type of the block to be authenticated. If the value is 1, it is Key_A. 2 is Key_B.
        :type key_type: int
        :param key: The key of the block to be authenticated.
        :type key: bytes
        :return: status: :class:`STATUS`
        
        .. seealso:: :func:`mifare_read` :func:`mifare_write` :func:`mifare_increment` :func:`mifare_decrement`
            :func:`mifare_restore` :func:`mifare_transfer`
        .. note:: This command only corresponds to the Mifare Classic.
        """
        
        if key is None or len(key) != 6:
            return self.STATUS.INVALID_PARAM
        if key_type != 1 and key_type != 2:
            return self.STATUS.INVALID_PARAM
        
        b = blk_no.to_bytes(1, 'little')
        key_ab = key_type.to_bytes(1, 'little')
        smp = Message('cmd', 'nfc', 'mfc_auth', b, key_ab, key)
        smp = self._send_receive(smp)
        r = smp.decode()
        return r['status']
    
    def mifare_read(self, blk_no) -> Dict[STATUS, Optional[bytes]]:
        """
        The data read from Mifare card.
        
        :param blk_no: The block number of Mifare card.
        :type blk_no: int
        :return: status: :class:`STATUS`\n
            If status is :class:`STATUS.SUCCESS`, it has the values defined below:
            \t data(bytes): The data read from card
            
        .. seealso:: :func:`mifare_auth` :func:`mifare_write` :func:`mifare_increment` :func:`mifare_decrement`
            :func:`mifare_restore` :func:`mifare_transfer`
        .. note:: This command only corresponds to the Mifare Classic.\n
            :func:`mifare_auth` must precede this command.
        """
        b = blk_no.to_bytes(1, 'little')
        smp = Message('cmd', 'nfc', 'mfc_read', b, b'\x00')
        smp = self._send_receive(smp)
        r = smp.decode()
        ret = dict(status=r['status'])
        if r['status'] == self.STATUS.SUCCESS:
            ret['data'] = r['payload']
        return ret
    
    def mifare_write(self, blk_no, data) -> STATUS:
        """
        The data writes to Mifare card.
        
        :param blk_no: The block number of Mifare card.
        :type blk_no: int
        :param data: Data to write the card.
        :type data: bytes
        :return: status: :class:`STATUS`
        
        .. seealso:: :func:`mifare_auth` :func:`mifare_read` :func:`mifare_increment` :func:`mifare_decrement`
            :func:`mifare_restore` :func:`mifare_transfer`
        .. note:: This command only corresponds to the Mifare Classic.\n
            :func:`mifare_auth` must precede this command.
        """
        b = blk_no.to_bytes(1, 'little')
        smp = Message('cmd', 'nfc', 'mfc_write', b, b'\x00', data)
        smp = self._send_receive(smp)
        r = smp.decode()
        return r['status']
    
    def mifare_increment(self, blk_no, value) -> STATUS:
        """
        Increase the value of the block in Mifare.
        
        :param blk_no: The block number of Mifare card.
        :type blk_no: int
        :param value: The value to be increased
        :type value: int
        :return: status: :class:`STATUS`
        
        .. seealso:: :func:`mifare_auth` :func:`mifare_read` :func:`mifare_write` :func:`mifare_decrement`
            :func:`mifare_restore` :func:`mifare_transfer`
        .. note:: This command only corresponds to the Mifare Classic.\n
            :func:`mifare_auth` must precede this command.
        """
        b = blk_no.to_bytes(1, 'little')
        smp = Message('cmd', 'nfc', 'mfc_inc', b, b'\x00', value.to_bytes(4, 'little', signed=True))
        smp = self._send_receive(smp)
        r = smp.decode()
        return r['status']
    
    def mifare_decrement(self, blk_no, value) -> STATUS:
        """
        Decrease the value of the block in Mifare.

        :param blk_no: The block number of Mifare card.
        :type blk_no: int
        :param value: The value to be decreased
        :type value: int
        :return: status: :class:`STATUS`
        
        .. seealso:: :func:`mifare_auth` :func:`mifare_read` :func:`mifare_write` :func:`mifare_increment`
            :func:`mifare_restore` :func:`mifare_transfer`
        .. note:: This command only corresponds to the Mifare Classic.\n
            :func:`mifare_auth` must precede this command.
        """
        
        b = blk_no.to_bytes(1, 'little')
        smp = Message('cmd', 'nfc', 'mfc_dec', b, b'\x00', value.to_bytes(4, 'little', signed=True))
        smp = self._send_receive(smp)
        r = smp.decode()
        return r['status']
    
    def mifare_restore(self, blk_no) -> STATUS:
        """
        Restore the value of the block in Mifare.

        :param blk_no: The block number of Mifare card.
        :type blk_no: int
        :return: status: :class:`STATUS`

        .. seealso:: :func:`mifare_auth` :func:`mifare_read` :func:`mifare_write` :func:`mifare_increment`
            :func:`mifare_decrement` :func:`mifare_transfer`
        .. note:: This command only corresponds to the Mifare Classic.\n
            :func:`mifare_auth` must precede this command.
        """
        
        b = blk_no.to_bytes(1, 'little')
        smp = Message('cmd', 'nfc', 'mfc_restore', b, b'\x00')
        smp = self._send_receive(smp)
        r = smp.decode()
        return r['status']
    
    def mifare_transfer(self, blk_no) -> STATUS:
        """
        Save the value of the block in Mifare.

        :param blk_no: The block number of Mifare card.
        :type blk_no: int
        :return: status: :class:`STATUS`

        .. seealso:: :func:`mifare_auth` :func:`mifare_read` :func:`mifare_write` :func:`mifare_increment`
            :func:`mifare_decrement` :func:`mifare_restore`
        .. note:: This command only corresponds to the Mifare Classic.\n
            :func:`mifare_auth` must precede this command.
        """
        
        b = blk_no.to_bytes(1, 'little')
        smp = Message('cmd', 'nfc', 'mfc_transfer', b, b'\x00')
        smp = self._send_receive(smp)
        r = smp.decode()
        return r['status']
    
    def emv(self, mode, param=0):
        m = mode.to_bytes(1, 'little')
        p = param.to_bytes(1, 'little')
        smp = Message('cmd', 'nfc', 'emv', m, p)
        smp = self._send_receive(smp)
        r = smp.decode()
        if mode == 1 and r['status'] == self.STATUS.SUCCESS:
            self.mode = 2
        elif mode == 2 and r['status'] == self.STATUS.SUCCESS:
            self.mode = 0
        
        return r['status']
