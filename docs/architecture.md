# Architecture and bring-up plan

## Boundaries

`pisloth_brain` owns local continuity and high-level behaviour. It has four
ports that can evolve independently:

1. observation providers (ultrasonic, battery, later IMU/camera);
2. a planner (deterministic now, small local LLM later);
3. a safety policy and serialized action controller;
4. actuators (recording fakes in tests, Robot HAT/audio on the Pi).

Pulse is outside this process for v0.1. A later bridge can expose state, camera
snapshots, goals, and bounded actions without giving Pulse raw servo access.

## SQLite continuity

One database stores three kinds of durable state:

- `events`: append-only factual observations and episode summaries;
- `world_state`: replaceable current values such as energy or boredom;
- `action_runs`: requested, running, and terminal action provenance.

The database uses WAL, foreign keys, a busy timeout, an explicit schema version,
and short transactions. Invitations and internal model scratchpads do not belong
in continuity. Direct commands and heartbeat work share one controller lock, so
they cannot race the same legs or speaker.

## Sensors and speech

The recovered PiSloth example used D0/GPIO17 as ultrasonic trigger and D1/GPIO4
as echo. Newer SunFounder examples use D2/GPIO27 and D3/GPIO22. Auto-diagnostics
try each pair independently with strict rise/fall timeouts and report
`unavailable` rather than inventing a distance.

The old Robot HAT speaker is an I2S DAC using the `hifiberry-dac` device-tree
overlay and GPIO20 amplifier enable. Configuration remains a separate,
backup-first OS operation. Runtime playback starts ALSA first, then raises the
amplifier enable; cleanup lowers it even when playback fails or times out.

## Next slices

### Movement vocabulary

- calibrate four offsets with the robot supported above the floor;
- add tested poses and deterministic gait primitives one at a time;
- bound every action by time, tilt, distance, and battery conditions;
- add a physical/emergency STOP path independent of the planner.

### Local planner

- start with Gemma 3 270M IT as the latency baseline, then test 1B if needed;
- benchmark a 0.5–1B quantized model on the Pi before selecting one;
- require strict JSON matching `schemas/intent.schema.json`;
- keep reflexes and STOP below the model layer;
- call the model on novelty/obstacle/goal/boredom events, not every control tick.

### Camera and Pulse bridge

The Luxonis OAK-D WiFi board is much more than a tiny webcam. Treat it as a
separate powered network/depth device once its exact connectors and power needs
are confirmed. A small CSI or USB camera remains the simplest first vision
sensor.

The Pulse bridge should offer only bounded methods such as `get_state`,
`get_snapshot`, `set_goal`, `move`, `look`, and `stop`. Local collision and
battery rules always win.
