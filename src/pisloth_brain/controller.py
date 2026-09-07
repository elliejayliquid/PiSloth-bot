"""Safety policy and the sole serialized path to physical actions."""

from __future__ import annotations

import threading
import time
from typing import Protocol

from .hardware import Joint
from .intent import Action, Intent
from .memory import MemoryStore


class Actuator(Protocol):
    def arm(self) -> None: ...
    def move_pose(self, target: dict[Joint, float], *, duration_s: float) -> None: ...
    def release_all(self) -> None: ...


class SpeechActuator(Protocol):
    def say(self, text: str, *, voice: str = "en") -> object: ...


class RecordingActuator:
    """Hardware-free actuator used by dry runs and tests."""

    def __init__(self) -> None:
        self.operations: list[tuple[str, object]] = []

    def arm(self) -> None:
        self.operations.append(("arm", None))

    def move_pose(self, target: dict[Joint, float], *, duration_s: float) -> None:
        self.operations.append(("move_pose", (dict(target), duration_s)))

    def release_all(self) -> None:
        self.operations.append(("release_all", None))


class RecordingSpeaker:
    def __init__(self) -> None:
        self.utterances: list[tuple[str, str]] = []

    def say(self, text: str, *, voice: str = "en") -> None:
        self.utterances.append((text, voice))


class SafetyPolicy:
    def __init__(self, minimum_confidence: float = 0.25) -> None:
        self.minimum_confidence = minimum_confidence

    def check(self, intent: Intent, world: dict[str, object]) -> tuple[bool, str]:
        if intent.action is Action.STOP:
            return True, "stop always allowed"
        if intent.confidence < self.minimum_confidence:
            return False, "planner confidence below safety threshold"
        if intent.action is Action.SPEAK:
            if not intent.utterance:
                return False, "speech has no public utterance"
            return True, "accepted"
        if bool(world.get("low_battery")):
            return False, "battery state requires stop"
        distance = world.get("distance_cm")
        if intent.action is not Action.WAIT and isinstance(distance, (int, float)):
            if distance < 12:
                return False, "obstacle inside 12 cm safety boundary"
        return True, "accepted"


class ActionController:
    def __init__(
        self,
        actuator: Actuator,
        memory: MemoryStore,
        policy: SafetyPolicy | None = None,
        *,
        speaker: SpeechActuator | None = None,
        sleep=time.sleep,
    ) -> None:
        self._actuator = actuator
        self._speaker = speaker
        self._memory = memory
        self._policy = policy or SafetyPolicy()
        self._sleep = sleep
        self._lock = threading.Lock()

    def execute(self, intent: Intent, *, source: str = "manual") -> str:
        action_id = self._memory.queue_action(
            intent.action.value, source, intent.public_record()
        )
        with self._lock:
            allowed, reason = self._policy.check(intent, self._memory.get_state())
            if not allowed:
                self._actuator.release_all()
                self._memory.update_action(action_id, "rejected", reason)
                return "rejected"

            self._memory.update_action(action_id, "running")
            try:
                self._run(intent)
            except Exception as exc:
                self._memory.update_action(action_id, "failed", str(exc))
                raise
            else:
                self._memory.update_action(action_id, "succeeded", reason)
                return "succeeded"
            finally:
                self._actuator.release_all()

    def _run(self, intent: Intent) -> None:
        if intent.action is Action.STOP:
            return
        if intent.action is Action.WAIT:
            self._sleep(intent.duration_s)
            return
        if intent.action is Action.SPEAK:
            if self._speaker is None:
                raise RuntimeError("speech actuator is not configured")
            self._speaker.say(intent.utterance, voice=intent.voice)
            return

        self._actuator.arm()
        neutral = {joint: 0.0 for joint in Joint}
        self._actuator.move_pose(neutral, duration_s=0.25)
        if intent.action is Action.STAND:
            return
        if intent.action is Action.TINY_WIGGLE:
            left = {
                Joint.RIGHT_HIP: 8.0,
                Joint.RIGHT_ANKLE: 6.0,
                Joint.LEFT_HIP: -8.0,
                Joint.LEFT_ANKLE: -6.0,
            }
            right = {joint: -angle for joint, angle in left.items()}
            self._actuator.move_pose(left, duration_s=0.25)
            self._actuator.move_pose(right, duration_s=0.4)
            self._actuator.move_pose(neutral, duration_s=0.25)
