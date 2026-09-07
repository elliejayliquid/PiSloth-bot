"""Strict local-LLM planner with deterministic reflexes and fail-safe output."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlparse

from .intent import Action, Intent
from .memory import sanitize_public


class JsonTransport(Protocol):
    def post(
        self, url: str, payload: Mapping[str, Any], timeout_s: float
    ) -> Mapping[str, Any]: ...


class UrllibJsonTransport:
    MAX_RESPONSE_BYTES = 65_536

    def post(
        self, url: str, payload: Mapping[str, Any], timeout_s: float
    ) -> Mapping[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                body = response.read(self.MAX_RESPONSE_BYTES + 1)
        except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
            raise RuntimeError(f"local planner request failed: {exc}") from exc
        if len(body) > self.MAX_RESPONSE_BYTES:
            raise RuntimeError("local planner response exceeded 64 KiB")
        try:
            decoded = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("local planner returned invalid response JSON") from exc
        if not isinstance(decoded, Mapping):
            raise RuntimeError("local planner response must be a JSON object")
        return decoded


@dataclass(frozen=True, slots=True)
class PlannerDiagnostics:
    status: str
    model: str
    latency_ms: int
    detail: str = ""

    def public_record(self) -> dict[str, object]:
        return {
            "status": self.status,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "detail": self.detail[:240],
        }


class LlamaServerPlanner:
    """Choose a high-level intent through a loopback llama.cpp server.

    Raw generations and model reasoning are intentionally never retained.
    ``diagnostics()`` exposes only bounded operational metadata.
    """

    DEFAULT_ACTIONS = (Action.STOP, Action.WAIT, Action.TINY_WIGGLE, Action.SPEAK)

    def __init__(
        self,
        *,
        endpoint: str = "http://127.0.0.1:8080",
        model: str = "ggml-org/gemma-3-270m-it-GGUF:Q8_0",
        timeout_s: float = 20.0,
        allowed_actions: tuple[Action, ...] = DEFAULT_ACTIONS,
        transport: JsonTransport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("local planner endpoint must be loopback HTTP")
        if not 0.1 <= timeout_s <= 60.0:
            raise ValueError("planner timeout must be between 0.1 and 60 seconds")
        if not allowed_actions or Action.STOP not in allowed_actions:
            raise ValueError("planner action set must include STOP")
        self._url = endpoint.rstrip("/") + "/v1/chat/completions"
        self._model = model
        self._timeout_s = timeout_s
        self._configured_actions = tuple(dict.fromkeys(allowed_actions))
        self._transport = transport or UrllibJsonTransport()
        self._clock = monotonic
        self._last = PlannerDiagnostics("not_run", model, 0)

    def plan(self, world: Mapping[str, Any]) -> Intent:
        reflex = self._reflex(world)
        if reflex is not None:
            self._last = PlannerDiagnostics("reflex", self._model, 0, reflex.rationale)
            return reflex

        allowed = self._available_actions(world)
        payload = self._request_payload(world, allowed)
        started = self._clock()
        try:
            response = self._transport.post(self._url, payload, self._timeout_s)
            content = self._extract_content(response)
            decoded = json.loads(content)
            if not isinstance(decoded, Mapping):
                raise ValueError("intent content is not an object")
            intent = Intent.from_mapping(decoded)
            if intent.action not in allowed:
                raise ValueError(f"action {intent.action.value} is unavailable for current sensors")
        except Exception as exc:
            latency = round((self._clock() - started) * 1000)
            detail = self._safe_error(exc)
            self._last = PlannerDiagnostics("fallback", self._model, latency, detail)
            return Intent(Action.STOP, rationale="Local planner unavailable or invalid")

        latency = round((self._clock() - started) * 1000)
        self._last = PlannerDiagnostics("ok", self._model, latency)
        return intent

    def diagnostics(self) -> dict[str, object]:
        return self._last.public_record()

    def _reflex(self, world: Mapping[str, Any]) -> Intent | None:
        if world.get("battery_status") == "unavailable" or bool(world.get("low_battery")):
            return Intent(Action.STOP, rationale="Battery state requires stop")
        distance = world.get("distance_cm")
        if isinstance(distance, (int, float)) and distance < 12:
            return Intent(Action.STOP, rationale="Obstacle too close")
        return None

    def _available_actions(self, world: Mapping[str, Any]) -> tuple[Action, ...]:
        distance = world.get("distance_cm")
        eye_ok = world.get("ultrasonic_status") == "ok" and isinstance(distance, (int, float))
        if eye_ok:
            return self._configured_actions
        return tuple(
            action
            for action in self._configured_actions
            if action in {Action.STOP, Action.WAIT, Action.SPEAK}
        )

    def _request_payload(
        self, world: Mapping[str, Any], allowed: tuple[Action, ...]
    ) -> dict[str, object]:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["action", "confidence", "rationale"],
            "properties": {
                "action": {"enum": [action.value for action in allowed]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "rationale": {"type": "string", "maxLength": 80},
                "utterance": {"type": "string", "maxLength": 60},
            },
        }
        public_world = sanitize_public(dict(world))
        return {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are the tiny local planner inside a four-servo PiSloth robot. "
                        "Choose exactly one available high-level action. Prefer WAIT when "
                        "nothing useful changed. TINY_WIGGLE is a harmless curious gesture, "
                        "not navigation. Apply these behavior rules in order after safety: "
                        "when human_presence is true, use SPEAK with a brief friendly public "
                        "utterance; when boredom is at least 0.8 and the eye reports clear "
                        "space, use TINY_WIGGLE; otherwise use WAIT. Never provide hidden "
                        "reasoning; rationale is one short factual sentence."
                    ),
                },
                {
                    "role": "user",
                    "content": "Current public world state:\n" + json.dumps(public_world, sort_keys=True),
                },
            ],
            "temperature": 0.1,
            "max_tokens": 96,
            "seed": 42,
            "stream": False,
            "reasoning_effort": "none",
            "chat_template_kwargs": {"enable_thinking": False},
            # llama.cpp accepts both json_schema and json_object here. The latter
            # consistently applies the supplied schema with Gemma 3 270M on ARM64.
            "response_format": {"type": "json_object", "schema": schema},
        }

    @staticmethod
    def _extract_content(response: Mapping[str, Any]) -> str:
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("missing chat completion content") from exc
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty chat completion content")
        return content

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        # Operational detail only. Never include a raw model response here.
        text = str(exc).replace("\r", " ").replace("\n", " ").strip()
        return f"{type(exc).__name__}: {text}"[:240]
