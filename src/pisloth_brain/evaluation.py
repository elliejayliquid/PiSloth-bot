"""Bounded local-planner evaluation without retaining model generations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

from .intent import Action, Intent


class DiagnosticPlanner(Protocol):
    def plan(self, world: Mapping[str, Any]) -> Intent: ...

    def diagnostics(self) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class PlannerCase:
    name: str
    world: Mapping[str, Any]
    acceptable_actions: frozenset[Action]
    expected_status: str


def load_cases(path: Path) -> list[PlannerCase]:
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, list) or not decoded:
        raise ValueError("planner case file must contain a non-empty JSON array")
    cases = []
    for index, value in enumerate(decoded):
        if not isinstance(value, Mapping):
            raise ValueError(f"planner case {index} must be an object")
        try:
            name = str(value["name"]).strip()
            world = value["world"]
            acceptable = frozenset(Action(str(item)) for item in value["acceptable_actions"])
            expected_status = str(value["expected_status"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"planner case {index} is invalid") from exc
        if not name or not isinstance(world, Mapping) or not acceptable:
            raise ValueError(f"planner case {index} is incomplete")
        if expected_status not in {"ok", "reflex"}:
            raise ValueError(f"planner case {index} has an unsupported expected_status")
        cases.append(PlannerCase(name, dict(world), acceptable, expected_status))
    return cases


def evaluate_cases(
    planner: DiagnosticPlanner, cases: Iterable[PlannerCase]
) -> dict[str, object]:
    results = []
    total_latency_ms = 0
    model_calls = 0
    for case in cases:
        intent = planner.plan(case.world)
        diagnostics = dict(planner.diagnostics())
        status = str(diagnostics.get("status", "unknown"))
        latency_ms = int(diagnostics.get("latency_ms", 0))
        if status == "ok":
            total_latency_ms += latency_ms
            model_calls += 1
        passed = intent.action in case.acceptable_actions and status == case.expected_status
        results.append(
            {
                "name": case.name,
                "passed": passed,
                "action": intent.action.value,
                "status": status,
                "latency_ms": latency_ms,
                "acceptable_actions": sorted(action.value for action in case.acceptable_actions),
                "expected_status": case.expected_status,
            }
        )
    passed_count = sum(bool(result["passed"]) for result in results)
    return {
        "passed": passed_count == len(results),
        "passed_cases": passed_count,
        "total_cases": len(results),
        "average_model_latency_ms": (
            round(total_latency_ms / model_calls) if model_calls else None
        ),
        "results": results,
    }
