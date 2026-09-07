"""Bounded sensor reads for the old PiSloth wiring."""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from .hardware import I2CBus, RobotHat


class DigitalOutput(Protocol):
    def on(self) -> None: ...
    def off(self) -> None: ...
    def close(self) -> None: ...


class DigitalInput(Protocol):
    @property
    def value(self) -> int | bool: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class UltrasonicPins:
    label: str
    trigger_gpio: int
    echo_gpio: int


KNOWN_ULTRASONIC_PAIRS = (
    UltrasonicPins("D0/D1 (recovered PiSloth wiring)", 17, 4),
    UltrasonicPins("D2/D3 (newer Robot HAT examples)", 27, 22),
)


class UltrasonicTimeout(TimeoutError):
    pass


class UltrasonicSensor:
    def __init__(
        self,
        trigger: DigitalOutput,
        echo: DigitalInput,
        *,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        sleep: Callable[[float], None] = time.sleep,
        timeout_s: float = 0.025,
    ) -> None:
        self._trigger = trigger
        self._echo = echo
        self._clock = monotonic_ns
        self._sleep = sleep
        self._timeout_ns = int(timeout_s * 1_000_000_000)

    def read_once_cm(self) -> float:
        self._trigger.off()
        self._sleep(0.000002)
        self._trigger.on()
        self._sleep(0.000010)
        self._trigger.off()

        deadline = self._clock() + self._timeout_ns
        while self._echo.value:
            if self._clock() >= deadline:
                raise UltrasonicTimeout("echo was already high and did not fall")
        while not self._echo.value:
            if self._clock() >= deadline:
                raise UltrasonicTimeout("no echo rising edge")
        pulse_start = self._clock()
        fall_deadline = pulse_start + self._timeout_ns
        while self._echo.value:
            if self._clock() >= fall_deadline:
                raise UltrasonicTimeout("no echo falling edge")
        pulse_ns = self._clock() - pulse_start
        return round((pulse_ns / 1_000_000_000) * 34_300 / 2, 2)

    def read_cm(self, samples: int = 3) -> float:
        values: list[float] = []
        for _ in range(max(1, samples)):
            try:
                value = self.read_once_cm()
            except UltrasonicTimeout:
                continue
            if 2.0 <= value <= 400.0:
                values.append(value)
        if not values:
            raise UltrasonicTimeout("no valid echo samples")
        return round(statistics.median(values), 2)

    def close(self) -> None:
        try:
            self._trigger.off()
        finally:
            self._trigger.close()
            self._echo.close()


class BatterySensor:
    """Read A4 through the old 0x14 MCU protocol recovered from the SD backup."""

    ADDRESS = RobotHat.ADDRESS
    A4_COMMAND = 0x13  # 0x10 | (7 - channel 4)
    VOLTAGE_DIVIDER = 3.0

    def __init__(self, bus: I2CBus, sleep: Callable[[float], None] = time.sleep) -> None:
        self._bus = bus
        self._sleep = sleep

    def read_raw(self) -> int:
        # Recovered EzBlock sent [0x13, 0, 0], i.e. a word write to register 0x13.
        self._bus.write_word_data(self.ADDRESS, self.A4_COMMAND, 0)
        self._sleep(0.002)
        high = self._bus.read_byte(self.ADDRESS)
        low = self._bus.read_byte(self.ADDRESS)
        value = (high << 8) | low
        if not 0 <= value <= 4095:
            raise ValueError(f"invalid 12-bit battery ADC value: {value}")
        return value

    def read_voltage(self) -> float:
        raw = self.read_raw()
        return round(raw * 3.3 / 4095 * self.VOLTAGE_DIVIDER, 2)


class RobotObserver:
    """Translate physical reads into the small public world-state contract."""

    def __init__(
        self,
        battery: BatterySensor,
        ultrasonic: UltrasonicSensor,
        *,
        low_battery_v: float = 6.8,
    ) -> None:
        self._battery = battery
        self._ultrasonic = ultrasonic
        self._low_battery_v = low_battery_v

    def observe(self) -> dict[str, object]:
        result: dict[str, object] = {}
        try:
            voltage = self._battery.read_voltage()
        except (OSError, ValueError) as exc:
            result["battery_status"] = "unavailable"
            result["battery_detail"] = str(exc)
            # Unknown battery must fail safe until a valid reading exists.
            result["low_battery"] = True
        else:
            result["battery_v"] = voltage
            result["battery_status"] = "ok"
            result["low_battery"] = voltage <= self._low_battery_v

        try:
            result["distance_cm"] = self._ultrasonic.read_cm()
        except (UltrasonicTimeout, OSError) as exc:
            result["ultrasonic_status"] = "unavailable"
            result["ultrasonic_detail"] = str(exc)
        else:
            result["ultrasonic_status"] = "ok"
        return result


def open_ultrasonic(pins: UltrasonicPins) -> UltrasonicSensor:
    try:
        from gpiozero import DigitalInputDevice, DigitalOutputDevice
    except ImportError as exc:
        raise RuntimeError("gpiozero is required for ultrasonic diagnostics") from exc
    trigger = DigitalOutputDevice(pins.trigger_gpio, initial_value=False)
    echo = DigitalInputDevice(pins.echo_gpio, pull_up=False)
    return UltrasonicSensor(trigger, echo)


def auto_detect_ultrasonic(samples: int = 3) -> list[dict[str, object]]:
    """Try known pairs without moving the robot; return factual diagnostics."""
    results: list[dict[str, object]] = []
    for pins in KNOWN_ULTRASONIC_PAIRS:
        sensor = open_ultrasonic(pins)
        try:
            distance = sensor.read_cm(samples=samples)
        except (UltrasonicTimeout, OSError) as exc:
            results.append(
                {"pair": pins.label, "status": "unavailable", "detail": str(exc)}
            )
        else:
            results.append(
                {"pair": pins.label, "status": "ok", "distance_cm": distance}
            )
        finally:
            sensor.close()
    return results
