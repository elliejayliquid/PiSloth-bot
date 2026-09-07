import unittest

from pisloth_brain.intent import Action
from pisloth_brain.planner import LlamaServerPlanner


class Transport:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error
        self.calls = []

    def post(self, url, payload, timeout_s):
        self.calls.append((url, payload, timeout_s))
        if self.error:
            raise self.error
        return {"choices": [{"message": {"content": self.content}}]}


SAFE_WORLD = {
    "battery_status": "ok",
    "battery_v": 7.4,
    "low_battery": False,
    "ultrasonic_status": "ok",
    "distance_cm": 30,
}


class PlannerTests(unittest.TestCase):
    def test_close_obstacle_is_reflex_stop_without_model_call(self):
        transport = Transport(error=AssertionError("must not call model"))
        planner = LlamaServerPlanner(transport=transport)
        intent = planner.plan({**SAFE_WORLD, "distance_cm": 6})
        self.assertEqual(intent.action, Action.STOP)
        self.assertEqual(transport.calls, [])
        self.assertEqual(planner.diagnostics()["status"], "reflex")

    def test_low_or_unknown_battery_is_reflex_stop(self):
        planner = LlamaServerPlanner(transport=Transport())
        self.assertEqual(planner.plan({**SAFE_WORLD, "low_battery": True}).action, Action.STOP)
        self.assertEqual(
            planner.plan({**SAFE_WORLD, "battery_status": "unavailable"}).action,
            Action.STOP,
        )

    def test_valid_schema_content_becomes_intent(self):
        transport = Transport(
            '{"action":"TINY_WIGGLE","duration_s":0.5,"confidence":0.8,'
            '"rationale":"The room is clear."}'
        )
        planner = LlamaServerPlanner(transport=transport, monotonic=lambda: 1.0)
        intent = planner.plan(SAFE_WORLD)
        self.assertEqual(intent.action, Action.TINY_WIGGLE)
        self.assertEqual(planner.diagnostics()["status"], "ok")
        payload = transport.calls[0][1]
        self.assertEqual(payload["response_format"]["type"], "json_object")
        self.assertEqual(
            payload["response_format"]["schema"]["additionalProperties"], False
        )
        self.assertNotIn("thought", str(payload).lower())

    def test_bad_json_fails_closed_without_raw_content_in_diagnostics(self):
        secret_raw = "not json PRIVATE_MODEL_SCRATCHPAD"
        planner = LlamaServerPlanner(transport=Transport(secret_raw), monotonic=lambda: 1.0)
        intent = planner.plan(SAFE_WORLD)
        self.assertEqual(intent.action, Action.STOP)
        diagnostic = planner.diagnostics()
        self.assertEqual(diagnostic["status"], "fallback")
        self.assertNotIn("PRIVATE_MODEL_SCRATCHPAD", str(diagnostic))

    def test_motion_is_removed_from_schema_when_eye_is_unknown(self):
        transport = Transport('{"action":"WAIT","confidence":1,"rationale":"No eye."}')
        planner = LlamaServerPlanner(transport=transport)
        planner.plan({**SAFE_WORLD, "ultrasonic_status": "unavailable"})
        actions = transport.calls[0][1]["response_format"]["schema"]["properties"]["action"]["enum"]
        self.assertNotIn("TINY_WIGGLE", actions)

    def test_disallowed_generated_action_fails_closed(self):
        transport = Transport(
            '{"action":"TINY_WIGGLE","confidence":1,"rationale":"Trying anyway."}'
        )
        planner = LlamaServerPlanner(transport=transport)
        intent = planner.plan({**SAFE_WORLD, "ultrasonic_status": "unavailable"})
        self.assertEqual(intent.action, Action.STOP)
        self.assertEqual(planner.diagnostics()["status"], "fallback")

    def test_world_state_is_sanitized_before_prompting(self):
        transport = Transport('{"action":"WAIT","confidence":1,"rationale":"Safe."}')
        planner = LlamaServerPlanner(transport=transport)
        planner.plan({**SAFE_WORLD, "thought": "private"})
        messages = transport.calls[0][1]["messages"]
        self.assertNotIn("private", messages[1]["content"])

    def test_remote_endpoint_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            LlamaServerPlanner(endpoint="https://example.com")


if __name__ == "__main__":
    unittest.main()
