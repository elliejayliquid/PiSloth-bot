import unittest

from pisloth_brain.intent import Action, Intent


class IntentTests(unittest.TestCase):
    def test_parses_strict_public_intent(self):
        intent = Intent.from_mapping(
            {"action": "wait", "duration_s": 1.5, "confidence": 0.7}
        )
        self.assertEqual(intent.action, Action.WAIT)
        self.assertEqual(intent.duration_s, 1.5)

    def test_rejects_raw_thought_field(self):
        with self.assertRaisesRegex(ValueError, "unknown intent fields"):
            Intent.from_mapping({"action": "STOP", "thought": "private"})

    def test_speak_requires_public_utterance(self):
        with self.assertRaisesRegex(ValueError, "utterance"):
            Intent.from_mapping({"action": "SPEAK"})

    def test_rejects_unbounded_duration(self):
        with self.assertRaisesRegex(ValueError, "duration_s"):
            Intent.from_mapping({"action": "WAIT", "duration_s": 60})


if __name__ == "__main__":
    unittest.main()
