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
    
    
def mifare_read():
    global discovery_msg
    
    while True:
        if discovery_msg is None:
            continue
        
        for t in Command.NfcTagType:
            if t == discovery_msg['type']:
                print(Command.NfcTagType(t).name)
                print('UID: ' + ' '.join('{:02X}'.format(x) for x in discovery_msg['uid']))
                if t == Command.NfcTagType.TYPE2:
                    for e in Command.NfcTagAppTypeMiFareClassic:
                        if discovery_msg['app_type'] == e:
                            print(Command.NfcTagAppTypeMiFareClassic(e).name)
                            for b in range(12):
                                if b % 4 == 0 and cmd.mifare_auth(b, 1, b'\xFF\xFF\xFF\xFF\xFF\xFF') \
                                        != Command.STATUS.SUCCESS:
                                    print('Authenticate fail - blk: ' + str(b))
                                    continue
                                
                                r = cmd.mifare_read(b)
                                if r['status'] == Command.STATUS.SUCCESS:
                                    print('{:02d}: '.format(b) + ' '.join('{:02X}'.format(x) for x in r['data']))
                            break
                    break
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
        mifare_read()
    except KeyboardInterrupt:
        cmd.discovery(start=False)
        cmd.close()
        print('End')
