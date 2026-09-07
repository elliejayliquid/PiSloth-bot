import unittest
from types import SimpleNamespace

from pisloth_brain.hardware import Joint, RobotHat, RobotHatError, reset_hat_mcu


class FakeBus:
    def __init__(self, detected=True):
        self.detected = detected
        self.writes = []
        self.closed = False

    def read_byte(self, address):
        if not self.detected:
            raise OSError("no ack")
        return 0

    def write_word_data(self, address, register, value):
        self.writes.append((address, register, value))

    def close(self):
        self.closed = True


class RobotHatTests(unittest.TestCase):
    def test_mcu_reset_toggles_gpio5_without_servo_io(self):
        calls = []
        sleeps = []

        def run(command, **kwargs):
            calls.append(command)
            return SimpleNamespace(returncode=0, stderr="")

        reset_hat_mcu(run=run, sleep=sleeps.append)
        self.assertEqual(calls[0][-1], "dl")
        self.assertEqual(calls[1][-1], "dh")
        self.assertEqual(sleeps, [0.01, 1.0])

    def test_construction_and_probe_do_not_write(self):
        bus = FakeBus()
        hat = RobotHat(bus)
        self.assertTrue(hat.probe())
        hat.close()
        self.assertEqual(bus.writes, [])

    def test_requires_arm_before_servo_output(self):
        hat = RobotHat(FakeBus())
        with self.assertRaises(RobotHatError):
            hat.set_joint(Joint.RIGHT_HIP, 1)

    def test_angle_conversion_matches_validated_timer(self):
        self.assertEqual(RobotHat.angle_to_count(-90), 102)
        self.assertEqual(RobotHat.angle_to_count(0), 307)
        self.assertEqual(RobotHat.angle_to_count(90), 512)

    def test_arm_and_release_use_byte_swapped_words(self):
        bus = FakeBus()
        hat = RobotHat(bus)
        hat.arm()
        hat.set_joint(Joint.RIGHT_HIP, 0)
        hat.release_all()
        self.assertIn((0x14, 0x40, 0x5E01), bus.writes)
        self.assertIn((0x14, 0x20, 0x3301), bus.writes)
        self.assertEqual(bus.writes[-4:], [(0x14, reg, 0) for reg in range(0x20, 0x24)])

    def test_joint_limit_is_enforced_before_write(self):
        bus = FakeBus()
        hat = RobotHat(bus)
        hat.arm()
        before = len(bus.writes)
        with self.assertRaises(ValueError):
            hat.set_joint(Joint.RIGHT_ANKLE, 26)
        self.assertEqual(len(bus.writes), before)


if __name__ == "__main__":
    unittest.main()
