import unittest

from pisloth_brain.sensors import BatterySensor, RobotObserver, UltrasonicSensor, UltrasonicTimeout


class Output:
    def __init__(self): self.values = []
    def on(self): self.values.append(1)
    def off(self): self.values.append(0)
    def close(self): pass


class Input:
    def __init__(self, values): self.values = iter(values)
    @property
    def value(self): return next(self.values)
    def close(self): pass


class Clock:
    def __init__(self): self.now = 0
    def __call__(self):
        self.now += 1_000_000
        return self.now


class Bus:
    def __init__(self):
        self.reads = iter([0x0C, 0x1D])
        self.writes = []
    def write_word_data(self, address, register, value):
        self.writes.append((address, register, value))
    def read_byte(self, address): return next(self.reads)


class SensorTests(unittest.TestCase):
    def test_robot_observer_fails_safe_when_battery_is_unknown(self):
        class BadBattery:
            def read_voltage(self): raise OSError("offline")
        class Eye:
            def read_cm(self): return 25.0

        state = RobotObserver(BadBattery(), Eye()).observe()
        self.assertTrue(state["low_battery"])
        self.assertEqual(state["battery_status"], "unavailable")

    def test_robot_observer_preserves_unknown_eye_state(self):
        class Battery:
            def read_voltage(self): return 7.45
        class BadEye:
            def read_cm(self): raise UltrasonicTimeout("no echo")

        state = RobotObserver(Battery(), BadEye()).observe()
        self.assertFalse(state["low_battery"])
        self.assertNotIn("distance_cm", state)
        self.assertEqual(state["ultrasonic_status"], "unavailable")

    def test_ultrasonic_pulse_is_bounded_and_converted(self):
        trigger = Output()
        sensor = UltrasonicSensor(
            trigger, Input([0, 0, 1, 1, 0]), monotonic_ns=Clock(), sleep=lambda _: None
        )
        self.assertEqual(sensor.read_once_cm(), 34.3)
        self.assertEqual(trigger.values, [0, 1, 0])

    def test_recovered_a4_protocol_and_voltage(self):
        bus = Bus()
        sensor = BatterySensor(bus, sleep=lambda _: None)
        self.assertEqual(sensor.read_voltage(), 7.5)
        self.assertEqual(bus.writes, [(0x14, 0x13, 0)])


if __name__ == "__main__":
    unittest.main()
