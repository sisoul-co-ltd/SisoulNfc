import unittest
import os

from pysisoulnfc.nfc import Command


class CustomTests(unittest.TestCase):
    
    def setUp(self):
        pass
    
    def tearDown(self):
        pass
    
    def test_getPorts(self):
        cmd = Command()
        ports = cmd.get_ports()
        for p in ports:
            print(p.serial)
        
    def test_runs(self):
        cmd = Command()
        self.assertIsInstance(cmd, Command)


# unittest를 실행
if __name__ == '__main__':
    unittest.main()
