"""Conservative CLI: simulated by default; hardware needs explicit flags."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .audio import AUDIO_OVERLAY, Speaker, apply_audio_overlay, configured_text
from .controller import ActionController, RecordingActuator
from .evaluation import evaluate_cases, load_cases
from .hardware import RobotHat, reset_hat_mcu
from .heartbeat import Heartbeat, ReflexPlanner, StaticObserver
from .intent import Action, Intent
from .memory import MemoryStore
from .planner import LlamaServerPlanner
from .sensors import (
    BatterySensor,
    KNOWN_ULTRASONIC_PAIRS,
    RobotObserver,
    auto_detect_ultrasonic,
    open_ultrasonic,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pisloth-brain")
    sub = parser.add_subparsers(dest="command", required=True)

    heartbeat = sub.add_parser("heartbeat", help="run one simulated heartbeat")
    heartbeat.add_argument("--once", action="store_true", required=True)
    heartbeat.add_argument("--live-sensors", action="store_true")
    heartbeat.add_argument("--db", type=Path, default=Path("data/squirrel.db"))

    status = sub.add_parser("status", help="show durable local state")
    status.add_argument("--db", type=Path, default=Path("data/squirrel.db"))

    sub.add_parser("hardware-check", help="probe I2C without moving")

    sensors = sub.add_parser("sensors", help="read battery and ultrasonic eye")
    sensors.add_argument("--auto", action="store_true", required=True)

    audio = sub.add_parser("configure-audio", help="prepare old Robot HAT I2S audio")
    audio_mode = audio.add_mutually_exclusive_group(required=True)
    audio_mode.add_argument("--print-only", action="store_true")
    audio_mode.add_argument("--apply", action="store_true")
    audio.add_argument("--config", type=Path)

    speak = sub.add_parser("speak", help="synthesize and play bounded speech")
    speak.add_argument("text")
    speak.add_argument("--voice", default="en")
    speak.add_argument("--confirm-audio", action="store_true")
    speak.add_argument("--db", type=Path, default=Path("data/squirrel.db"))

    planner = sub.add_parser("planner-smoke", help="query a loopback llama.cpp planner")
    planner.add_argument("--endpoint", default="http://127.0.0.1:8080")
    planner.add_argument("--model", default="ggml-org/gemma-3-270m-it-GGUF:Q8_0")
    planner.add_argument(
        "--state",
        default='{"battery_status":"ok","battery_v":7.4,"low_battery":false,"ultrasonic_status":"ok","distance_cm":30,"boredom":0.7}',
        help="public world-state JSON object",
    )

    planner_eval = sub.add_parser(
        "planner-eval", help="run bounded cases against a loopback llama.cpp planner"
    )
    planner_eval.add_argument("--endpoint", default="http://127.0.0.1:8080")
    planner_eval.add_argument("--model", default="ggml-org/gemma-3-270m-it-GGUF:Q8_0")
    planner_eval.add_argument(
        "--cases", type=Path, default=Path("benchmarks/planner_cases.json")
    )

    move = sub.add_parser("move", help="run one bounded physical action")
    move.add_argument("action", choices=["stand", "tiny-wiggle", "stop"])
    move.add_argument("--confirm-motion", action="store_true")
    move.add_argument("--db", type=Path, default=Path("data/squirrel.db"))
    return parser


def _boot_config(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    modern = Path("/boot/firmware/config.txt")
    return modern if modern.exists() else Path("/boot/config.txt")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.command == "heartbeat":
        memory = MemoryStore(args.db)
        actuator = RecordingActuator()
        hat = None
        ultrasonic = None
        try:
            if args.live_sensors:
                hat = RobotHat.open()
                if not hat.probe():
                    reset_hat_mcu()
                if not hat.probe():
                    print("Robot HAT not detected after MCU reset")
                    return 1
                ultrasonic = open_ultrasonic(KNOWN_ULTRASONIC_PAIRS[1])
                observer = RobotObserver(BatterySensor(hat.bus), ultrasonic)
            else:
                observer = StaticObserver({"sensor_status": "not_configured"})
            heartbeat = Heartbeat(
                observer,
                ReflexPlanner(),
                ActionController(actuator, memory),
                memory,
            )
            result = heartbeat.tick()
            print(json.dumps({"result": result, "operations": actuator.operations}, default=str))
        finally:
            if ultrasonic is not None:
                ultrasonic.close()
            if hat is not None:
                hat.close()
            memory.close()
        return 0

    if args.command == "status":
        memory = MemoryStore(args.db)
        try:
            print(
                json.dumps(
                    {
                        "state": memory.get_state(),
                        "recent_actions": memory.recent_actions(5),
                        "recent_events": memory.recent_events(5),
                    },
                    indent=2,
                )
            )
        finally:
            memory.close()
        return 0

    if args.command == "hardware-check":
        hat = RobotHat.open()
        try:
            detected = hat.probe()
            if not detected:
                reset_hat_mcu()
                detected = hat.probe()
            print("Robot HAT detected at 0x14" if detected else "Robot HAT not detected")
            return 0 if detected else 1
        finally:
            hat.close()

    if args.command == "sensors":
        hat = RobotHat.open()
        try:
            if not hat.probe():
                reset_hat_mcu()
            if not hat.probe():
                print("Robot HAT not detected after MCU reset")
                return 1
            battery = BatterySensor(hat.bus).read_voltage()
        finally:
            hat.close()
        result = {
            "battery_v": battery,
            "low_battery": battery <= 6.8,
            "ultrasonic": auto_detect_ultrasonic(),
        }
        print(json.dumps(result, indent=2))
        return 0 if any(x["status"] == "ok" for x in result["ultrasonic"]) else 1

    if args.command == "configure-audio":
        path = _boot_config(args.config)
        if args.print_only:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            changed = configured_text(current) != current
            print(json.dumps({"config": str(path), "overlay": AUDIO_OVERLAY, "change_needed": changed}))
            return 0
        backup = apply_audio_overlay(path)
        if backup is None:
            print(f"Audio overlay already active in {path}; no file changed.")
        else:
            print(f"Added audio overlay to {path}; backup: {backup}. Reboot required.")
        return 0

    if args.command == "speak":
        if not args.confirm_audio:
            print("Refusing audio: add --confirm-audio after the HAT audio card is configured.")
            return 2
        memory = MemoryStore(args.db)
        try:
            controller = ActionController(
                RecordingActuator(), memory, speaker=Speaker()
            )
            intent = Intent.from_mapping(
                {
                    "action": "SPEAK",
                    "utterance": args.text,
                    "voice": args.voice,
                    "rationale": "Explicit local CLI request",
                }
            )
            result = controller.execute(intent, source="manual_cli")
            print(result)
            return 0 if result == "succeeded" else 1
        finally:
            memory.close()

    if args.command == "planner-smoke":
        try:
            state = json.loads(args.state)
        except json.JSONDecodeError as exc:
            print(json.dumps({"error": f"invalid --state JSON: {exc}"}))
            return 2
        if not isinstance(state, dict):
            print(json.dumps({"error": "--state must be a JSON object"}))
            return 2
        planner = LlamaServerPlanner(endpoint=args.endpoint, model=args.model)
        intent = planner.plan(state)
        print(
            json.dumps(
                {"intent": intent.public_record(), "planner": planner.diagnostics()},
                indent=2,
            )
        )
        return 0 if planner.diagnostics()["status"] in {"ok", "reflex"} else 1

    if args.command == "planner-eval":
        try:
            cases = load_cases(args.cases)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(json.dumps({"error": f"invalid planner cases: {exc}"}))
            return 2
        planner = LlamaServerPlanner(endpoint=args.endpoint, model=args.model)
        report = evaluate_cases(planner, cases)
        print(json.dumps(report, indent=2))
        return 0 if report["passed"] else 1

    if args.command == "move":
        if not args.confirm_motion:
            print("Refusing motion: add --confirm-motion while holding the robot safely.")
            return 2
        action = {
            "stand": Action.STAND,
            "tiny-wiggle": Action.TINY_WIGGLE,
            "stop": Action.STOP,
        }[args.action]
        memory = MemoryStore(args.db)
        hat = RobotHat.open()
        try:
            result = ActionController(hat, memory).execute(
                Intent(action, rationale="Explicit local CLI request"),
                source="manual_cli",
            )
            print(result)
            return 0 if result == "succeeded" else 1
        finally:
            hat.close()
            memory.close()

    return 2
