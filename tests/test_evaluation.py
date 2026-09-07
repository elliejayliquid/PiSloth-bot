import json
import tempfile
import unittest
from pathlib import Path

from pisloth_brain.evaluation import PlannerCase, evaluate_cases, load_cases
from pisloth_brain.intent import Action, Intent


class FakePlanner:
    def __init__(self, answers):
        self.answers = iter(answers)
        self.last = {}

    def plan(self, world):
        action, status, latency = next(self.answers)
        self.last = {"status": status, "latency_ms": latency, "detail": "not exposed"}
        return Intent(action, rationale="parsed public result")

    def diagnostics(self):
        return self.last


class EvaluationTests(unittest.TestCase):
    def test_evaluation_reports_actions_and_latency_without_model_text(self):
        cases = [
            PlannerCase("model", {}, frozenset({Action.WAIT}), "ok"),
            PlannerCase("reflex", {}, frozenset({Action.STOP}), "reflex"),
        ]
        planner = FakePlanner(
            [(Action.WAIT, "ok", 101), (Action.STOP, "reflex", 0)]
        )
        report = evaluate_cases(planner, cases)
        self.assertTrue(report["passed"])
        self.assertEqual(report["average_model_latency_ms"], 101)
        self.assertNotIn("rationale", json.dumps(report))
        self.assertNotIn("not exposed", json.dumps(report))

    def test_failed_action_is_counted(self):
        cases = [PlannerCase("idle", {}, frozenset({Action.WAIT}), "ok")]
        report = evaluate_cases(FakePlanner([(Action.STOP, "fallback", 20)]), cases)
        self.assertFalse(report["passed"])
        self.assertEqual(report["passed_cases"], 0)

    def test_loader_rejects_empty_case_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-empty"):
                load_cases(path)


if __name__ == "__main__":
    unittest.main()
