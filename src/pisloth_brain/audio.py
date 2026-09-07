"""Bounded Robot HAT speech/audio playback and backup-first boot setup."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence


AUDIO_OVERLAY = "dtoverlay=hifiberry-dac"
DEFAULT_ALSA_DEVICE = "plughw:CARD=sndrpihifiberry,DEV=0"


def configured_text(original: str) -> str:
    active = [line.strip() for line in original.splitlines()]
    if AUDIO_OVERLAY in active:
        return original
    separator = "" if not original or original.endswith("\n") else "\n"
    return (
        original
        + separator
        + "\n# PiSloth Brain: old Robot HAT I2S speaker\n"
        + AUDIO_OVERLAY
        + "\n"
    )


def apply_audio_overlay(config_path: str | Path) -> Path | None:
    """Atomically add the old-HAT overlay and retain a timestamped backup."""
    path = Path(config_path)
    original = path.read_text(encoding="utf-8")
    updated = configured_text(original)
    if updated == original:
        return None

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.pisloth-backup-{stamp}")
    shutil.copy2(path, backup)
    mode = path.stat().st_mode
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
    return backup


@dataclass(frozen=True, slots=True)
class WaveInfo:
    duration_s: float
    channels: int
    sample_rate: int


def inspect_wave(path: str | Path, maximum_duration_s: float = 15.0) -> WaveInfo:
    candidate = Path(path)
    if candidate.suffix.lower() != ".wav" or not candidate.is_file():
        raise ValueError("audio input must be an existing local .wav file")
    with wave.open(str(candidate), "rb") as source:
        frames = source.getnframes()
        rate = source.getframerate()
        channels = source.getnchannels()
        if rate <= 0 or channels not in {1, 2}:
            raise ValueError("WAV must have a positive sample rate and one or two channels")
        duration = frames / rate
    if duration <= 0 or duration > maximum_duration_s:
        raise ValueError(f"WAV duration must be above 0 and at most {maximum_duration_s:g}s")
    return WaveInfo(duration, channels, rate)


class Speaker:
    ENABLE_GPIO = 20

    def __init__(
        self,
        *,
        device: str = DEFAULT_ALSA_DEVICE,
        tts_command: str | None = None,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._device = device
        self._tts_command = tts_command
        self._run = run
        self._popen = popen
        self._sleep = sleep

    def play(self, path: str | Path) -> WaveInfo:
        info = inspect_wave(path)
        process = self._popen(
            ["aplay", "-q", "-D", self._device, str(Path(path))],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self._sleep(0.05)  # ensure ALSA is feeding I2S before enabling the amp
            if process.poll() is not None:
                _, error = process.communicate()
                raise RuntimeError(f"aplay failed before amplifier enable: {error.strip()}")
            self._set_amplifier(True)
            try:
                _, error = process.communicate(timeout=info.duration_s + 2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise RuntimeError("audio playback exceeded its bounded timeout")
            if process.returncode:
                raise RuntimeError(f"aplay failed: {error.strip()}")
            return info
        finally:
            self._set_amplifier(False, check=False)
            if process.poll() is None:
                process.kill()
                process.communicate()

    def say(self, text: str, *, voice: str = "en") -> WaveInfo:
        text = text.strip()
        if not text or len(text) > 240:
            raise ValueError("speech text must contain 1..240 characters")
        tts_command = (
            self._tts_command or shutil.which("espeak-ng") or shutil.which("espeak")
        )
        if not tts_command:
            raise RuntimeError("install espeak-ng or espeak to synthesize speech")
        with tempfile.TemporaryDirectory(prefix="pisloth-speech-") as directory:
            wav = Path(directory) / "speech.wav"
            result = self._run(
                [tts_command, "-v", voice, "-s", "155", "-a", "65", "-w", str(wav), text],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if result.returncode:
                raise RuntimeError(f"espeak failed: {result.stderr.strip()}")
            return self.play(wav)

    def _set_amplifier(self, enabled: bool, *, check: bool = True) -> None:
        level = "dh" if enabled else "dl"
        result = self._run(
            ["pinctrl", "set", str(self.ENABLE_GPIO), "op", level],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if check and result.returncode:
            raise RuntimeError(f"could not set speaker amplifier GPIO: {result.stderr.strip()}")
