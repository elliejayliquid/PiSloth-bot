import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace

from pisloth_brain.audio import AUDIO_OVERLAY, Speaker, apply_audio_overlay, inspect_wave


def make_wave(path: Path, frames: int = 800):
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(8000)
        target.writeframes(b"\0\0" * frames)


class FakeProcess:
    returncode = 0

    def poll(self):
        return None

    def communicate(self, timeout=None):
        return "", ""

    def kill(self):
        self.returncode = -9


class AudioTests(unittest.TestCase):
    def test_overlay_edit_is_backup_first_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.txt"
            config.write_text("dtparam=i2c_arm=on\n", encoding="utf-8")
            backup = apply_audio_overlay(config)
            self.assertIsNotNone(backup)
            self.assertEqual(backup.read_text(encoding="utf-8"), "dtparam=i2c_arm=on\n")
            self.assertIn(AUDIO_OVERLAY, config.read_text(encoding="utf-8"))
            self.assertIsNone(apply_audio_overlay(config))

    def test_wave_duration_is_inspected_before_playback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "short.wav"
            make_wave(path)
            info = inspect_wave(path)
            self.assertAlmostEqual(info.duration_s, 0.1)

    def test_speaker_enables_amp_only_around_live_playback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "short.wav"
            make_wave(path)
            pin_calls = []

            def run(command, **kwargs):
                pin_calls.append(command)
                return SimpleNamespace(returncode=0, stderr="")

            speaker = Speaker(run=run, popen=lambda *args, **kwargs: FakeProcess(), sleep=lambda _: None)
            speaker.play(path)
            self.assertEqual(pin_calls[0][-1], "dh")
            self.assertEqual(pin_calls[-1][-1], "dl")


if __name__ == "__main__":
    unittest.main()
