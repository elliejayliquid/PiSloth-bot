"""Small, strict boundary between planners and physical actions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


class Action(StrEnum):
    STOP = "STOP"
    STAND = "STAND"
    TINY_WIGGLE = "TINY_WIGGLE"
    WAIT = "WAIT"
    SPEAK = "SPEAK"


@dataclass(frozen=True, slots=True)
class Intent:
    action: Action
    duration_s: float = 0.0
    confidence: float = 1.0
    rationale: str = ""
    utterance: str = ""
    voice: str = "en"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Intent":
        allowed = {
            "action", "duration_s", "confidence", "rationale", "utterance", "voice"
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown intent fields: {', '.join(sorted(unknown))}")
        try:
            action = Action(str(value["action"]).upper())
        except (KeyError, ValueError) as exc:
            raise ValueError("intent action is missing or unsupported") from exc
        duration = float(value.get("duration_s", 0.0))
        confidence = float(value.get("confidence", 1.0))
        rationale = str(value.get("rationale", "")).strip()
        utterance = str(value.get("utterance", "")).strip()
        voice = str(value.get("voice", "en")).strip()
        if not 0.0 <= duration <= 15.0:
            raise ValueError("duration_s must be between 0 and 15")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if len(rationale) > 240:
            raise ValueError("rationale must be at most 240 characters")
        if len(utterance) > 240:
            raise ValueError("utterance must be at most 240 characters")
        if action is Action.SPEAK and not utterance:
            raise ValueError("SPEAK requires a non-empty utterance")
        if not voice or len(voice) > 32 or not all(c.isalnum() or c in "-_+" for c in voice):
            raise ValueError("voice must be a short espeak voice code")
        return cls(action, duration, confidence, rationale, utterance, voice)

    def public_record(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "duration_s": self.duration_s,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "utterance": self.utterance,
            "voice": self.voice,
        }
