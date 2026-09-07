"""Minimal driver for Lena's older Robot HAT.

Construction and probing never move a servo. PWM is configured only by
``arm()``, and pulse outputs are explicitly released by ``release_all()``.
"""

from __future__ import annotations

import time
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Mapping, Protocol


class I2CBus(Protocol):
    def read_byte(self, address: int) -> int: ...
    def write_byte(self, address: int, value: int) -> None: ...
    def write_i2c_block_data(self, address: int, register: int, data: list[int]) -> None: ...
    def write_word_data(self, address: int, register: int, value: int) -> None: ...
    def close(self) -> None: ...


class Joint(StrEnum):
    RIGHT_HIP = "right_hip"
    RIGHT_ANKLE = "right_ankle"
    LEFT_HIP = "left_hip"
    LEFT_ANKLE = "left_ankle"


@dataclass(frozen=True, slots=True)
class JointSpec:
    channel: int
    minimum: float
    maximum: float
    offset: float = 0.0


DEFAULT_JOINTS: Mapping[Joint, JointSpec] = {
    Joint.RIGHT_HIP: JointSpec(0, -30.0, 30.0),
    Joint.RIGHT_ANKLE: JointSpec(1, -25.0, 25.0),
    Joint.LEFT_HIP: JointSpec(2, -30.0, 30.0),
    Joint.LEFT_ANKLE: JointSpec(3, -25.0, 25.0),
}


class RobotHatError(RuntimeError):
    pass


def reset_hat_mcu(
    *,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Reset only the old HAT MCU on GPIO5; this does not arm servo PWM."""
    for level in ("dl", "dh"):
        result = run(
            ["pinctrl", "set", "5", "op", level],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode:
            raise RobotHatError(f"could not reset Robot HAT MCU: {result.stderr.strip()}")
        sleep(0.01 if level == "dl" else 1.0)


class RobotHat:
    ADDRESS = 0x14
    SERVO_BASE_REGISTER = 0x20
    TIMER_PRESCALER_REGISTER = 0x40
    TIMER_PERIOD_REGISTER = 0x44
    PRESCALER = 350
    PERIOD = 4094

    def __init__(
        self,
        bus: I2CBus,
        *,
        joints: Mapping[Joint, JointSpec] = DEFAULT_JOINTS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._bus = bus
        self._joints = dict(joints)
        self._sleep = sleep
        self._armed = False
        self._current_pose = {joint: 0.0 for joint in self._joints}

    @classmethod
    def open(cls, bus_number: int = 1) -> "RobotHat":
        try:
            from smbus2 import SMBus
        except ImportError as exc:
            raise RobotHatError("smbus2 is required on the Raspberry Pi") from exc
        return cls(SMBus(bus_number))

    @property
    def bus(self) -> I2CBus:
        return self._bus

    def probe(self) -> bool:
        try:
            self._bus.read_byte(self.ADDRESS)
        except OSError:
            return False
        return True

    def arm(self) -> None:
        if not self.probe():
            raise RobotHatError("Robot HAT did not acknowledge at I2C address 0x14")
        self._write_word(self.TIMER_PRESCALER_REGISTER, self.PRESCALER)
        self._write_word(self.TIMER_PERIOD_REGISTER, self.PERIOD)
        self._armed = True

    def set_joint(self, joint: Joint, angle: float) -> None:
        if not self._armed:
            raise RobotHatError("servo output is not armed")
        spec = self._joints[joint]
        angle = float(angle)
        if not spec.minimum <= angle <= spec.maximum:
            raise ValueError(
                f"{joint.value} angle {angle:g} outside "
                f"{spec.minimum:g}..{spec.maximum:g}"
            )
        pulse_count = self.angle_to_count(angle + spec.offset)
        self._write_word(self.SERVO_BASE_REGISTER + spec.channel, pulse_count)
        self._current_pose[joint] = angle

    def move_pose(
        self,
        target: Mapping[Joint, float],
        *,
        duration_s: float = 0.3,
        step_s: float = 0.04,
    ) -> None:
        if not 0.0 <= duration_s <= 5.0:
            raise ValueError("pose duration must be between 0 and 5 seconds")
        for joint, angle in target.items():
            spec = self._joints[joint]
            if not spec.minimum <= float(angle) <= spec.maximum:
                raise ValueError(f"unsafe target for {joint.value}: {angle}")

        start = dict(self._current_pose)
        steps = max(1, round(duration_s / step_s))
        for index in range(1, steps + 1):
            fraction = index / steps
            for joint, end in target.items():
                angle = start[joint] + (float(end) - start[joint]) * fraction
                self.set_joint(joint, angle)
            if index < steps and duration_s:
                self._sleep(duration_s / steps)

    def release_all(self) -> None:
        if not self._armed:
            return
        try:
            for spec in self._joints.values():
                self._write_word(self.SERVO_BASE_REGISTER + spec.channel, 0)
        finally:
            self._armed = False

    def close(self) -> None:
        try:
            self.release_all()
        finally:
            self._bus.close()

    @staticmethod
    def angle_to_count(angle: float) -> int:
        if not -90.0 <= angle <= 90.0:
            raise ValueError("servo angle must be between -90 and 90 degrees")
        pulse_us = 1500.0 + (angle / 90.0) * 1000.0
        return round(pulse_us * 4095.0 / 20_000.0)

    def _write_word(self, register: int, value: int) -> None:
        value = int(value) & 0xFFFF
        wire_value = ((value & 0xFF) << 8) | (value >> 8)
        self._bus.write_word_data(self.ADDRESS, register, wire_value)
