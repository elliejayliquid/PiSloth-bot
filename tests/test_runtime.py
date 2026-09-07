import tempfile
import unittest
from pathlib import Path

from pisloth_brain.controller import ActionController, RecordingActuator, RecordingSpeaker
from pisloth_brain.heartbeat import Heartbeat, ReflexPlanner, StaticObserver
from pisloth_brain.intent import Action, Intent
from pisloth_brain.memory import MemoryStore


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.memory = MemoryStore(Path(self.temp.name) / "squirrel.db")

    def tearDown(self):
        self.memory.close()
        self.temp.cleanup()

    def test_private_reasoning_is_removed_recursively(self):
        self.memory.append_event(
            "test", "unit",
            {"fact": 1, "thought": "no", "nested": {"reasoning": "no", "fact": 2}},
        )
        payload = self.memory.recent_events(1)[0]["payload"]
        self.assertEqual(payload, {"fact": 1, "nested": {"fact": 2}})

    def test_tiny_wiggle_always_releases_outputs(self):
        actuator = RecordingActuator()
        controller = ActionController(actuator, self.memory, sleep=lambda _: None)
        result = controller.execute(Intent(Action.TINY_WIGGLE), source="test")
        self.assertEqual(result, "succeeded")
        self.assertEqual(actuator.operations[-1], ("release_all", None))
        self.assertEqual(self.memory.recent_actions(1)[0]["status"], "succeeded")

    def test_low_battery_rejects_motion_and_releases(self):
        self.memory.set_state("low_battery", True)
        actuator = RecordingActuator()
        result = ActionController(actuator, self.memory).execute(Intent(Action.STAND))
        self.assertEqual(result, "rejected")
        self.assertEqual(actuator.operations, [("release_all", None)])

    def test_speech_uses_same_serialized_action_path(self):
        actuator = RecordingActuator()
        speaker = RecordingSpeaker()
        intent = Intent.from_mapping(
            {"action": "SPEAK", "utterance": "Hello", "voice": "en-gb"}
        )
        result = ActionController(actuator, self.memory, speaker=speaker).execute(intent)
        self.assertEqual(result, "succeeded")
        self.assertEqual(speaker.utterances, [("Hello", "en-gb")])
        self.assertEqual(actuator.operations[-1], ("release_all", None))

    def test_heartbeat_persists_observation_and_episode(self):
        actuator = RecordingActuator()
        heartbeat = Heartbeat(
            StaticObserver({"distance_cm": 8}), ReflexPlanner(),
            ActionController(actuator, self.memory), self.memory,
        )
        self.assertEqual(heartbeat.tick(trigger_source="unit_tick"), "succeeded")
        events = self.memory.recent_events(2)
        self.assertEqual(events[0]["kind"], "heartbeat_episode")
        self.assertEqual(events[0]["source"], "unit_tick")
        self.assertEqual(events[0]["payload"]["action"], "STOP")


if __name__ == "__main__":
    unittest.main()
