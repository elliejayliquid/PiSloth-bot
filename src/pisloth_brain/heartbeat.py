"""One observable, testable heartbeat turn."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .controller import ActionController
from .intent import Action, Intent
from .memory import MemoryStore


class Observer(Protocol):
    def observe(self) -> Mapping[str, Any]: ...


class Planner(Protocol):
    def plan(self, world: Mapping[str, Any]) -> Intent: ...


@dataclass(slots=True)
class StaticObserver:
    values: Mapping[str, Any]

    def observe(self) -> Mapping[str, Any]:
        return dict(self.values)


class ReflexPlanner:
    """Safe placeholder until a local model is measured and integrated."""

    def plan(self, world: Mapping[str, Any]) -> Intent:
        if bool(world.get("low_battery")):
            return Intent(Action.STOP, rationale="Low battery reported")
        distance = world.get("distance_cm")
        if isinstance(distance, (int, float)) and distance < 12:
            return Intent(Action.STOP, rationale="Obstacle too close")
        return Intent(Action.WAIT, duration_s=0.0, rationale="No actionable novelty")


class Heartbeat:
    def __init__(
        self,
        observer: Observer,
        planner: Planner,
        controller: ActionController,
        memory: MemoryStore,
    ) -> None:
        self._observer = observer
        self._planner = planner
        self._controller = controller
        self._memory = memory

    def tick(self, *, trigger_source: str = "manual_once") -> str:
        observation = dict(self._observer.observe())
        for key, value in observation.items():
            self._memory.set_state(key, value)
        self._memory.append_event("observation", trigger_source, observation)

        intent = self._planner.plan(self._memory.get_state())
        result = self._controller.execute(intent, source=trigger_source)
        self._memory.append_event(
            "heartbeat_episode",
            trigger_source,
            {
                "action": intent.action.value,
                "result": result,
                "rationale": intent.rationale,
            },
        )
        return result
