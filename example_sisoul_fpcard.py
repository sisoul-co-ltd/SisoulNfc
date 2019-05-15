import time

from pysisoulnfc.nfc import Command

discovery_msg = None


def discovered(status, msg):
    global discovery_msg
    if status == Command.STATUS.SUCCESS:
        if status == Command.STATUS.SUCCESS:
            if msg['colbit'] == 1:
                print('Collision!!!')
                return
            discovery_msg = msg
            
    elif status == Command.STATUS.LOST_REMOTE_DEVICE:
        print('Lost Remote Device')
    else:
        print(status)


def error(status, msg):
    print(status)
    print(msg)


class SisoulFpcard:
    APDU_SELECT_MF = b'\x00\xA4\x04\x00\x07\xF0\xAA\x55\x00\x01\x00\x02'
    APDU_ENROLL = b'\x00\xA0\x00\x00\x00'
    APDU_IDENTIFY = b'\x00\xA1\x00\x00\x00'
    APDU_DELETE = b'\x00\xAD\x00\x00\x00'
    APDU_STATUS = b'\x00\xB0\x00\x00\x03'
    
    class Status(enumerate):
        OK = 0
        FAIL = -1
        BUSY = -2
        FULL = -3
        EMPTY = -4
    
    class State(enumerate):
        NONE = 0
        IDLE = 1
        ENROLLMENT = 2
        IDENTIFY = 3
        DELETE_ALL = 4
    
    class StateDetail(enumerate):
        NONE = 0
        ON = 1
        NEED_FINGER = 2
        CLEAR_FINGER = 3
        PROCESSING = 4
        ERROR = 5
        
    def __init__(self, cmd:Command):
        self._cmd = cmd
    
    def _processing(self):
        prev_detail = self.StateDetail.NONE
        while True:
            rapdu = self._cmd.apdu_tranceive(self.APDU_STATUS)
            if rapdu['status'] == self._cmd.STATUS.SUCCESS and rapdu['data'][-2:] == b'\x90\x00':
                fp_status = int.from_bytes(rapdu['data'][0:1], 'little', signed=True)
                fp_state = int.from_bytes(rapdu['data'][1:2], 'little')
                fp_detail = int.from_bytes(rapdu['data'][2:3], 'little')
                
                if fp_status == self.Status.FAIL:
                    return False
                elif fp_status == self.Status.BUSY:
                    if prev_detail == fp_detail:
                        continue
                    prev_detail = fp_detail
                    if fp_detail == self.StateDetail.NEED_FINGER:
                        print('please PRESS your finger')
                    elif fp_detail == self.StateDetail.CLEAR_FINGER:
                        print('please RELEASE your finger')
                elif fp_status == self.Status.OK:
                    return True
                elif fp_status == self.Status.EMPTY:
                    print('The fingerprint is not enrolled.')
                    return False
                time.sleep(0.1)
            else:
                return False
                
    def select(self):
        rapdu = self._cmd.apdu_tranceive(self.APDU_SELECT_MF)
        if rapdu['status'] == self._cmd.STATUS.SUCCESS and rapdu['data'][-2:] == b'\x90\x00':
            return True
        return False
    
    def enroll(self):
        rapdu = self._cmd.apdu_tranceive(self.APDU_ENROLL)
        if rapdu['status'] == self._cmd.STATUS.SUCCESS and rapdu['data'][-2:] == b'\x90\x00':
            return self._processing()

    def identify(self):
        rapdu = self._cmd.apdu_tranceive(self.APDU_IDENTIFY)
        if rapdu['status'] == self._cmd.STATUS.SUCCESS and rapdu['data'][-2:] == b'\x90\x00':
            return self._processing()
        
    def delete(self):
        rapdu = self._cmd.apdu_tranceive(self.APDU_DELETE)
        if rapdu['status'] == self._cmd.STATUS.SUCCESS and rapdu['data'][-2:] == b'\x90\x00':
            return self._processing()

    
def sisoul_fpcard():
    global discovery_msg

    fpcard = SisoulFpcard(cmd)
    
    while True:
        if discovery_msg is None:
            continue
        
        for t in Command.NfcTagType:
            if t == discovery_msg['type']:
                print(Command.NfcTagType(t).name)
                print('UID: ' + ' '.join('{:02X}'.format(x) for x in discovery_msg['uid']))
                if t == Command.NfcTagType.TYPE4:
                    
                    if fpcard.select():
                        print('Enrollment')
                        if fpcard.enroll():
                            print('\t Success')
                        else:
                            print('\t Failed')
                            
                        time.sleep(1)  # Just wait for User
                        
                        print('Identifying')
                        if fpcard.identify():
                            print('\t Success')
                        else:
                            print('\t Failed')
                            
                        time.sleep(1)  # Just wait for User
                        
                        print('Delete')
                        if fpcard.delete():
                            print('\t Success')
                        else:
                            print('\t Failed')
                    
        discovery_msg = None
        time.sleep(1)


if __name__ == "__main__":
    cmd = Command()
    serials = cmd.get_ports()
    
    print(serials)
    cmd.open(serials[0])
    cmd.set_callbacks(discovered, error)
    cmd.discovery()
    try:
        sisoul_fpcard()
    except KeyboardInterrupt:
        cmd.discovery(start=False)
        cmd.close()
        print('End')
