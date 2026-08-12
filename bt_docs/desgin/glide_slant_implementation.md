# Glide intercept implementation plan

## Purpose

This document turns the [visual slant intercept design](glide_slant.md) into
independently reviewable implementation milestones. The milestones deliberately
separate observation validity, control-law behavior, flight-state integration,
and high-speed tuning so that each layer can be verified before it can command
the drone.

The phase-one target is a stationary, solid red cube measuring **1 × 1 × 1 m**.
The drone must strike the center of its front face in simulation, without wind
or camera distortion. Collision sensing and automatic impact scoring remain
deferred.

## Component ownership

| Component | Responsibility |
| --- | --- |
| Tracker callback and `TrackerManager` | Retain the newest immutable detection together with its local receipt time |
| `App` | Read one snapshot per cycle, validate freshness, build one immutable observation, and route state and RC results |
| `VisualRangeEstimator` | Convert a valid 1 m target bounding box into filtered forward camera depth |
| `GlideVelocityEstimator` | Convert target-relative geometry into a direction-preserving `vx`/`vy` request |
| `GlideController` | Own ACQUIRE, TRACK, COMMIT, and abort behavior plus the velocity and centering loops |
| Betaflight mapper | Convert physical pitch and yaw-rate requests into bounded RC channels |
| State machine | Keep acquisition in `ALT_HOLD`, enter `GLIDE` when ready, and return to `ALT_HOLD` on abort |

The controller receives data through typed immutable values. It does not read
the tracker, range estimator, application context, or bridge directly.

## Milestones

### 1. Trusted observation and velocity-vector estimation

Define the final tracker snapshot and glide observation contracts. Add local
freshness, deterministic rejection behavior, corrected forward-depth geometry,
image errors, centering quality, and the desired glide vector. Do not change RC
selection or active flight behavior.

Design: [milestone 1 — observation pipeline](glide_slant_milestone_1_observation.md)

Completion gate: recorded or synthetic detections deterministically produce a
fresh valid observation or an invalid observation with a specific reason.

### 2. TRACK control loops

Replace the landing/descent implementation of `GlideController` with typed
TRACK control. Implement depth-derived forward-speed filtering, pitch
feedforward plus PI feedback, vertical-speed PI, proportional yaw-rate
centering, output limits, and anti-windup. Extend the Betaflight mapping layer
to accept physical pitch degrees and yaw rate. Exercise the controller without
making it reachable from the flight state machine.

Completion gate: deterministic controller tests demonstrate bounded RC output,
timestamp-gated filter and PI updates, centering-dependent forward speed, and
safe handling of invalid observations.

Design: [milestone 2 — isolated TRACK controller](glide_slant_milestone_2_track_controller.md)

### 3. Flight phases and application integration

Add controller-owned ACQUIRE, TRACK, COMMIT, COMMIT_TIMEOUT, and ABORTED phases.
Run ACQUIRE while the top-level state remains `ALT_HOLD`; enter `GLIDE` only
after the lock gate passes. Freeze the entire last valid RC command in COMMIT.
Make stale tracking or commit timeout request an explicit transition back to
`ALT_HOLD`. Remove the old GLIDE landing events, state transitions, parameters,
and diagnostics.

Completion gate: end-to-end application tests cover acquisition, engagement,
tracking loss, command freeze, timeout, abort, and failsafe precedence.

### 4. Simulation commissioning

Run no-wind, no-distortion intercepts with the maximum forward speed staged at
2, 5, 10, then 15 m/s. Record phase, observation age, depth, image errors,
centering quality, desired and measured velocities, saturation flags, complete
RC output, and abort reason. Review simulator video and telemetry manually at
each speed before raising the limit.

Completion gate: the target stays within the configured centering bound until
COMMIT, no command exceeds its configured limit, and the drone reaches the
cube's front face without a pre-commit abort. Automated collision scoring is
not required.

## Initial configuration defaults

| Parameter | Initial value |
| --- | ---: |
| Forward speed for first commissioning run | 2 m/s |
| Final forward-speed limit | 15 m/s |
| Vertical-speed limit | 3 m/s |
| Center deadband | 0.05 normalized radius |
| Maximum centering error | 0.40 normalized radius |
| Consecutive lock frames | 5 |
| Tracker timeout | 0.25 s |
| Commit depth | 1.0 m |
| Commit timeout | 1.0 s |
| Forward-depth velocity EMA coefficient | 0.35 |

Control gains and attitude calibration remain provisional until milestone 2,
where their units, validation rules, and safe initial values are documented
with the RC mapping they drive.
