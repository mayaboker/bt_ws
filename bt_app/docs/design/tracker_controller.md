# Red-target tracker controller

## Objective

The tracker controller guides the drone toward a red target while keeping the
target near the center of a forward-facing camera. The first version commands:

- fixed forward pitch;
- yaw from horizontal image error;
- throttle from vertical image error;
- centered roll.

Measured-velocity feedback is deliberately deferred. When the drone reaches a
configured forward depth, the controller freezes its complete last valid RC
command for a short commit interval so loss of useful vision near the target
does not change the trajectory.

This document describes the implemented POC and its deferred production work.

## System boundary and data flow

The GStreamer process publishes `TrackerResultMessage`. The existing visual
bridge and distance-estimator service convert it into a controller-facing
observation. The application state machine decides whether the tracker
controller owns RC output.

```mermaid
flowchart LR
    GST["GStreamer red tracker"] -->|TrackerResultMessage over ZMQ| BRIDGE["VisualBridgeManager"]
    BRIDGE --> EST["DistanceEstimatorService"]
    EST -->|TargetEstimate| APP["App control loop"]
    APP --> SM["Robot state machine"]
    SM -->|TRACK active| CTRL["TrackerController"]
    CTRL -->|TrackerControlResult| SAN["RC validation"]
    SAN --> MSP["MSP / flight controller"]

    PARAMS["Runtime parameters"] --> CTRL
    TELEMETRY["Altitude telemetry"] --> ALT["ALT_HOLD controller"]
    ALT -->|safe handoff| APP
```

The tracker controller runs synchronously in the existing 50 Hz application
loop. ZMQ reception continues on its existing receiver thread; it only replaces
the immutable latest estimate. No additional controller thread is needed.

## Proposed interfaces

`TargetEstimate` needs the normalized target-center errors in addition to its
existing distance fields:

```python
@dataclass(frozen=True, slots=True)
class TargetEstimate:
    frame_id: int
    timestamp_ns: int | None
    received_at_s: float
    depth_m: float | None
    slant_range_m: float | None
    error_x: float | None
    error_y: float | None
    vx_m_s: float
    vy_m_s: float
    valid: bool
    reason: str | None = None
```

The errors are computed from the bounding-box center and configured camera
geometry:

```text
u = bbox_x + bbox_width / 2
v = bbox_y + bbox_height / 2

error_x = (u - cx) / (image_width / 2)
error_y = (cy - v) / (image_height / 2)
```

Positive `error_x` means the target is to the camera's right. Positive
`error_y` means the target is above the camera center. Both are clamped to
`[-1, 1]`.

The implemented controller API separates acquisition from active command output:

```text
TrackerController.observe(estimate, now_s, mode_selected) -> bool
TrackerController.update(now_s) -> TrackerControlResult
```

`TrackerControlResult` contains the complete eight-channel RC command, current
phase (`TRACKING` or `COMMIT`), image errors, requested pitch, yaw rate, throttle
correction, validity, and an optional reason. `reset()` clears acquisition,
commit timing, the frozen command, and completion state.

Only distinct frame IDs advance acquisition or update the tracking command.
Repeated application-loop reads hold the previous output.

## Joystick activation

Tracking selection is independent of auto takeoff. The immutable joystick
snapshot exposes two dedicated inputs:

| Channel | Boxer switch | Values |
| ------- | ------------ | ------ |
| 8 | SB | `1000` disabled, `1500` tracker1, `2000` tracker2 |
| 9 | SF | `1000` released, `2000` pressed |

Tracker1 and tracker2 intentionally use the same controller in this POC. While
either is selected, observations build the required fresh-frame lock. A single
SF `1000` to `2000` edge requests entry only when the application is already
armed in `ALT_HOLD` and the tracker is ready. Startup-high, held-high, and early
presses do not request a later entry. SB disabled immediately cancels acquisition
or exits `TRACK` to `ALT_HOLD`.

```mermaid
stateDiagram-v2
    [*] --> Disabled: SB = 1000
    Disabled --> Acquiring: SB = 1500 or 2000
    Acquiring --> Ready: fresh distinct frames
    Acquiring --> Disabled: SB = 1000
    Ready --> TRACK: SF 1000 -> 2000\narmed ALT_HOLD
    Ready --> Disabled: SB = 1000
    TRACK --> ALT_HOLD: SB = 1000\nstale target / commit complete
```

## Controller logic

### Deadband

A continuous deadband removes small detector noise without creating an output
jump:

```text
deadband(e, d) = 0                         when abs(e) <= d
                 sign(e) * (abs(e) - d)   otherwise
```

The initial deadband is `0.03` normalized image units.

### Pitch

Before measured-velocity control is introduced, pitch slews from level flight
toward a fixed physical angle:

```text
pitch_command = -10 degrees
```

Negative pitch means nose-down/forward. `BetaflightRcMapper.angle_to_rc()` uses
the configured Betaflight angle limit. The tracker applies its vehicle-specific
inverted pitch mapping, so forward pitch maps above RC midpoint (`-10 degrees`
at a `60 degree` limit maps to approximately `1583`). Other angle-mapper users
retain the default direction. The command is always bounded to `[1000, 2000]`.
TRACK starts at `0 degrees` and advances toward the target at
`TRK_PITCH_RATE`. With the initial `5 degrees/s` rate, the transition to
`-10 degrees` takes two seconds. Runtime target changes use the same slew rate.
Tilt-compensated throttle is calculated from the current ramped pitch.

### Yaw

Horizontal image error commands a proportional yaw rate:

```text
yaw_rate = clamp(
    TRK_YAW_KP * deadband(error_x, TRK_DEADBAND),
    -TRK_YAW_MAX,
    +TRK_YAW_MAX,
)
```

A target to the right produces a right-turn request. The existing
`BetaflightRcMapper.yaw_rate_to_rc()` converts the rate to RC.

### Throttle

Vertical image error adds a bounded correction around hover throttle. First,
compensate for the fixed pitch so the vertical thrust component remains near
hover:

```text
hover_fraction = (HOV_BASELINE - 1000) / 1000
throttle_ff = 1000 + 1000 * hover_fraction / cos(pitch_command)

throttle_correction = clamp(
    TRK_THR_KP * deadband(error_y, TRK_DEADBAND),
    -TRK_THR_MAX,
    +TRK_THR_MAX,
)

throttle = clamp(throttle_ff + throttle_correction, 1000, 2000)
```

A target above center increases throttle; a target below center decreases it.
Roll stays at `1500`. ARM and ANGLE remain high while TRACK owns the command.

```mermaid
flowchart TB
    OBS["TargetEstimate"] --> EX["error_x"]
    OBS --> EY["error_y"]
    OBS --> DEPTH["filtered optical depth"]

    FIXED["fixed -10 deg"] --> PMAP["angle-to-RC mapping"]
    PMAP --> PITCH["PITCH RC"]

    EX --> YDB["deadband"]
    YDB --> YKP["P gain + rate limit"]
    YKP --> YMAP["yaw-rate-to-RC"]
    YMAP --> YAW["YAW RC"]

    EY --> TDB["deadband"]
    TDB --> TKP["P gain + correction limit"]
    HOVER["hover baseline / cos(pitch)"] --> TSUM["sum + RC clamp"]
    TKP --> TSUM
    TSUM --> THROTTLE["THROTTLE RC"]

    DEPTH --> COMMIT{"depth <= 1.0 m?"}
    PITCH --> COMMAND["complete RC command"]
    YAW --> COMMAND
    THROTTLE --> COMMAND
    COMMIT -->|no| COMMAND
    COMMIT -->|yes| FREEZE["freeze complete command"]
```

## Acquisition, tracking, and commit

Add a dedicated `RobotState.TRACK`. `TRACKING` and `COMMIT` are internal
controller phases rather than additional application states.

### Entry

`ALT_HOLD` enters `TRACK` only when all of these are true:

- the vehicle is armed;
- SB selects tracker1 or tracker2;
- SF has produced a new low-to-high edge;
- three consecutive distinct estimates are valid and no older than `0.25 s`.

The state-machine guard reads observation status prepared by the App loop. It
does not read the ZMQ receiver thread directly.

### TRACKING

Each new valid frame updates the visual yaw and throttle corrections. The
time-based pitch slew advances on application updates while the latest target
remains valid; once it reaches its target, duplicate frames return the previous
complete command. Velocity fields in `TargetEstimate` are ignored in this
milestone.

An invalid estimate freezes the last valid command, including the pitch ramp,
until the last valid estimate becomes older than `0.25 s`. A valid estimate
within that grace period resumes tracking from the frozen pitch. At timeout,
`observe()` requests an exit before state resolution. The state machine enters
`ALT_HOLD` in the same loop; its altitude setpoint is initialized from the
current altitude for a bumpless handoff. A timeout still returns neutral
pitch/yaw and hover throttle rather than raising.

### COMMIT

When valid filtered `depth_m <= 1.0`, copy the complete current RC command and
enter `COMMIT`. During COMMIT:

- return the exact frozen command on every application tick;
- ignore new visual estimates and controller parameter changes;
- allow manual and failsafe overrides;
- stop at a deadline frozen on COMMIT entry using the monotonic clock.

At timeout, emit the safe altitude-hold handoff command and exit to `ALT_HOLD`.
Set a completion flag for diagnostics. The one-shot joystick request prevents
the still-visible target from immediately starting a second approach; a new SF
low-to-high edge is required after acquisition becomes ready again.

```mermaid
stateDiagram-v2
    [*] --> ALT_HOLD

    ALT_HOLD --> TRACKING: tracker selected\n3 fresh valid frames\nSF rising edge
    TRACKING --> COMMIT: depth <= 1.0 m
    TRACKING --> ALT_HOLD: target invalid/stale\nor tracker disabled
    TRACKING --> MANUAL: manual override
    TRACKING --> FAILSAFE: joystick failsafe

    COMMIT --> ALT_HOLD: 1.0 s timeout
    COMMIT --> MANUAL: manual override
    COMMIT --> FAILSAFE: joystick failsafe

    ALT_HOLD --> ALT_HOLD: acquire again\nwait for new SF edge
```

Failsafe has the highest transition priority, followed by manual override,
tracking exits, and normal tracking updates.

## Parameters

The first simulator values are intentionally conservative. Controller
parameters subscribe to the existing parameter-change event and update through
one validated immutable configuration snapshot, so an App-loop update never
observes a partially changed configuration. Invalid cross-field updates retain
the last valid snapshot. COMMIT retains both its frozen RC tuple and its
original deadline despite parameter updates.

| Parameter | Default | Meaning |
| --- | ---: | --- |
| `TRK_PITCH_DEG` | `-10.0` | Fixed forward pitch angle |
| `TRK_PITCH_RATE` | `5.0` | Pitch slew rate in degrees per second |
| `TRK_YAW_KP` | `15.0` | Yaw-rate gain in deg/s per normalized error |
| `TRK_YAW_MAX` | `20.0` | Absolute yaw-rate limit in deg/s |
| `TRK_THR_KP` | `100.0` | Throttle gain in RC units per normalized error |
| `TRK_THR_MAX` | `100.0` | Absolute throttle correction limit in RC units |
| `TRK_DEADBAND` | `0.03` | Image-error deadband |
| `TRK_TIMEOUT_S` | `0.25` | Maximum time since the last valid estimate |
| `TRK_LOCK_FRAMES` | `3` | Consecutive frames required for entry |
| `TRK_COMMIT_M` | `1.0` | Forward depth that enters COMMIT |
| `TRK_COMMIT_S` | `1.0` | Maximum frozen-command duration |
| `BF_ANGLE_LIMIT` | `60.0` | Betaflight angle represented by full RC stick |

`HOV_BASELINE` and `BF_YAW_RATE` remain the shared hover and yaw-mapping
parameters. All generated MAVLink parameter names remain within 16 characters.

## Implementation milestones

1. Extend `TargetEstimate` with normalized image errors while retaining the
   existing velocity fields.
2. Add the isolated `TrackerController`, immutable output, parameter bindings,
   RC mapping, and deterministic tests.
3. Add `RobotState.TRACK`, guards, App routing, altitude-hold handoff,
   completion latching, and integration tests.
4. Tune in simulation at low pitch before adding measured-velocity feedback.

## Test and acceptance matrix

Future implementation tests must cover:

- centered target: fixed forward pitch, neutral yaw, tilt-compensated throttle;
- target right/left: correctly signed and bounded yaw;
- target above/below: correctly signed and bounded throttle correction;
- deadband behavior and RC bounds;
- duplicate frames holding the previous command;
- entry only after three fresh distinct frames;
- brief invalid target holding the last command and resuming without a pitch jump;
- invalid or stale target exceeding the grace period exiting TRACK safely;
- commit at `depth_m <= 1.0` and exact preservation of every RC channel;
- visual and parameter updates being ignored during COMMIT;
- one-second commit timeout and SF edge re-entry gate;
- failsafe and manual overrides taking priority in both phases;
- live parameter updates outside COMMIT;
- state entry/exit resetting acquisition, timers, and frozen commands.

The first flight acceptance test succeeds when the simulator enters TRACK,
keeps the red target near camera center during a low-speed approach, freezes the
last command at one metre, returns to ALT_HOLD after one second, and cannot
re-enter TRACK until SF is released and pressed again after target lock.

## Deferred work

- measured forward/vertical velocity feedback;
- collision or impact confirmation;
- roll/lateral control;
- adaptive pitch or distance-based deceleration;
- wind, camera distortion, target motion, and production recovery behavior.
