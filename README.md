# PiSloth Brain v0.1

The first nervous system for Lena's long-sleeping PiSloth: small, local,
inspectable, and deliberately difficult for an LLM to hurt.

This slice contains:

- a fresh driver for the older Robot HAT MCU at I2C address `0x14`;
- named joints and conservative angle limits;
- high-level actions (`STOP`, `STAND`, `TINY_WIGGLE`, `WAIT`, `SPEAK`);
- one serialized action controller with unconditional PWM/speaker cleanup;
- ultrasonic auto-diagnostics for the known D0/D1 and D2/D3 pin pairs;
- old-protocol battery ADC sampling;
- a bounded WAV speech path that enables the amplifier only around playback;
- a SQLite event/state/action store inspired by Pulse;
- a heartbeat pipeline with a deterministic planner and an LLM-shaped seam;
- a loopback-only llama.cpp planner with schema-constrained, fail-safe intents;
- a dry-run CLI and hardware-independent tests.

It does **not** yet move automatically at boot, install a model, or enable an
autonomous service. Physical tests stay explicit so a software mistake cannot
unexpectedly move or heat the robot.

The pinned, resumable local-model benchmark procedure is in
[`docs/local-model.md`](docs/local-model.md). It is intentionally a manual gate.

## Safety model

```text
observe -> planner intent -> safety policy -> serialized controller -> hardware
                                  |                                  |
                                  +-- reject unknown/unsafe input     +-- cleanup
```

The planner never receives raw servo or amplifier access. Private model
reasoning is not a database field; the store also removes common
hidden-reasoning keys from nested event payloads. Only a short factual rationale
may be retained.

## Try it on this PC

No third-party dependency is required for the simulated path:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m pisloth_brain heartbeat --once --db data/squirrel.db
python -m pisloth_brain status --db data/squirrel.db
python -m pisloth_brain planner-smoke
python -m pisloth_brain planner-eval
```

`planner-smoke` expects a llama.cpp server on `127.0.0.1:8080`. If the server is
absent, slow, malformed, or returns an unavailable action, the result is a
factual fallback `STOP`; raw model output is never persisted or echoed.
`planner-eval` applies the same boundary to the cases in
`benchmarks/planner_cases.json` and reports only actions, pass/fail status, and
latency. Reflex cases do not call the model.

## Raspberry Pi bring-up

After copying the reviewed code to the Pi and installing the small `pi` extra:

```bash
python -m pip install -e '.[pi]'
sudo apt-get install -y espeak-ng
pisloth-brain hardware-check
pisloth-brain sensors --auto
pisloth-brain configure-audio --print-only
```

`hardware-check` only probes I2C. `sensors --auto` emits ten-microsecond trigger
pulses but never moves. `configure-audio --print-only` explains the one boot
overlay needed for this old HAT without changing the OS.

If the old MCU does not ACK immediately after boot, diagnostics reset only that
MCU through GPIO5 for 10 ms and retry. This does not arm servo output.

`heartbeat --once --live-sensors` reads the confirmed D2/D3 eye and A4 battery,
persists the public world state, and runs the reflex planner against a recording
actuator. It therefore proves the living loop without moving a leg.

After the audio overlay has been reviewed, applied, and the Pi rebooted:

```bash
pisloth-brain speak test.wav --confirm-audio
pisloth-brain move tiny-wiggle --confirm-motion
```

Motion and audio require explicit flags. Speech accepts only a local WAV, caps
playback at 15 seconds, starts a silent stream before enabling GPIO20, and lowers
GPIO20 in `finally`.

## Known physical map

Labels are from the robot's perspective:

| Joint | HAT channel | v0.1 safe range |
|---|---:|---:|
| right hip | P0 | -30..30 degrees |
| right ankle | P1 | -25..25 degrees |
| left hip | P2 | -30..30 degrees |
| left ankle | P3 | -25..25 degrees |

The old HAT answers at `0x14`. Servo timer values validated on this board are a
72 MHz clock, prescaler `350`, period `4094`, and 500–2500 microseconds for
-90..90 degrees. Mechanical neutral is currently `[0, 0, 0, 0]`.

See [docs/architecture.md](docs/architecture.md) for the design and next slices.
The first physical verification is recorded in
[docs/bringup-2026-09-06.md](docs/bringup-2026-09-06.md).
