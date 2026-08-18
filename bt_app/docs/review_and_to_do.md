# `bt_app/app.py` Diagnostics Review and To-Do List

This document records the diagnostics review of `bt_app/bt_app/app.py`. The
items are ordered by severity and are intended to be planned, implemented, and
verified one at a time.

The main diagnostic weakness is not simply too few log calls. The application
currently lacks telemetry freshness, state-transition context, and controller
input/output context at the points where a flight problem must be reconstructed.

## Work-item status

Use these markers while resolving the review:

- `[ ]` Not started
- `[~]` In progress
- `[x]` Completed and verified
- `[-]` Intentionally deferred, with the reason documented

## High severity

### [ ] APP-DIAG-001: Detect stale or absent MSP telemetry

Location: `bt_app/bt_app/app.py`, `App.__update_state()`.

The application reads cached MSP state and altitude without timestamps.
`MSPAdapter.get_altitude()` returns `0` before the first sample, and an old
sample remains valid indefinitely. Takeoff or altitude-hold control can
therefore act on fake or stale altitude.

Required changes:

- Record monotonic update timestamps in the MSP dispatcher or adapter, such as
  `last_altitude_at`, `last_state_at`, and `last_rc_at`.
- Expose data values together with their freshness or age.
- Do not treat an unavailable altitude sample as zero.
- Define warning and failsafe age thresholds for each telemetry stream.
- Log `WARNING` once when a stream becomes stale.
- Log `ERROR` when it remains stale beyond its failsafe threshold.
- Log `INFO` once when the stream recovers.
- Log a rate-limited `DEBUG` telemetry snapshot, no faster than 1 Hz.
- Do not emit stale warnings on every control-loop iteration.

Example:

```text
MSP altitude stale age_s=0.84 state=TAKEOFF last_altitude_m=0.00
```

Verification:

- Test startup before the first altitude response.
- Test a stream becoming stale while idle and while airborne.
- Test recovery and ensure only one recovery message is emitted.
- Confirm a failed read does not update the last-success timestamp.

### [ ] APP-DIAG-002: Log unexpected control-loop exceptions and define recovery

Location: `bt_app/bt_app/app.py`, `App.run()`.

The main loop catches only `KeyboardInterrupt`. An exception from state
resolution, a controller, the recorder, or MSP scheduling exits through
`finally` without a top-level traceback or a flight-state snapshot. The MSP
dispatcher may also continue transmitting its previously scheduled command.

Progress (2026-08-02): `KeyboardInterrupt` control flow was removed. `SIGINT`
and `SIGTERM` now set an application stop event, the loop exits normally, and
MSP output is stopped first so the FC's configured RX-loss failsafe takes over.
Unexpected-exception snapshot logging remains open under this item.

Required changes:

- Add a real process/control-loop exception boundary.
- Use `log.exception()` at `ERROR` or `CRITICAL` for unexpected termination.
- Include the current robot state, armed state, requested RC, last-sent RC,
  altitude, vertical speed, joystick/MSP ages, and arming-disable flags.
- Define an explicit safe-output or failsafe action before services stop.
- Stop the MSP dispatcher and close its transport during cleanup.
- Make cleanup safe after partial startup and safe to call more than once.
- Do not add broad exception handling inside controller business logic; keep it
  at the actual loop and I/O boundaries.

Verification:

- Inject an exception from state resolution, a controller, the recorder, and
  MSP submission.
- Verify that the traceback and state snapshot are present.
- Verify that stale RC transmission does not continue after loop failure.
- Verify cleanup after partial initialization.

### [ ] APP-DIAG-003: Replace invalid or missing RC output safely

Locations: `bt_app/bt_app/app.py`, `App.run()` and `App._manual_handler()`.

A falsey RC result produces an error and immediately continues without the loop
delay. This can create a busy log loop while the dispatcher keeps sending the
previous RC command. `_manual_handler()` can also return `None` before the first
joystick packet.

Required changes:

- Log `ERROR` on the first invalid output, including state and controller name.
- Replace invalid output with an explicit safe or failsafe RC command.
- Preserve the configured loop period on the failure path.
- Rate-limit identical repeated reports.
- Log `INFO` when valid controller output resumes.
- Avoid mutating the joystick adapter's original channel list in the manual
  handler; work on a validated copy.

Verification:

- Test manual mode before the first joystick packet.
- Test `None`, an empty list, too few channels, and non-numeric values.
- Confirm a safe command replaces the old dispatcher command.
- Confirm the failure path does not spin faster than `FREQ_HZ`.

### [ ] APP-DIAG-004: Record takeoff controller inputs and outputs

Location: `bt_app/bt_app/app.py`, `App._takeoff_handler()`.

The takeoff path records neither the PID input nor the RC output. The existing
logs cannot show whether a ground flip followed a large throttle step, a
roll/pitch command, a bad altitude sample, or a flight-controller/motor issue.

Required changes:

- Emit a rate-limited `DEBUG` record containing state, altitude, altitude
  setpoint, vertical speed, PID correction, throttle PWM, roll, pitch, yaw,
  ARM, and ANGLE values.
- Record the same fields at 5-10 Hz in the flight recorder while limiting
  console output to approximately 1 Hz.
- Include a monotonic timestamp and controller phase in recorded samples.
- Add MSP attitude and motor-output telemetry to the diagnostic recording path.
  Altitude and RC alone cannot distinguish control output from motor order,
  gyro orientation, or unequal thrust.
- Keep raw per-loop data at `TRACE`, not `INFO`.

Example:

```text
state=TAKEOFF alt_m=0.00 alt_sp_m=4.00 vs_m_s=0.00 pid_output=240 \
throttle_pwm=1740 roll=1500 pitch=1500 yaw=1500 arm=2000 angle=2000
```

Verification:

- Test that a takeoff sample contains every required field.
- Confirm console rate limiting and higher-rate recorder output.
- Correlate RC, attitude, and motor samples using monotonic timestamps.

## Medium severity

### [ ] APP-DIAG-005: Log arming-disable flags only on meaningful changes

Location: `bt_app/bt_app/app.py`, `App.__update_state()`.

The application currently logs two warnings repeatedly whenever arming-disable
flags are present, even though the underlying state telemetry updates much more
slowly than the control loop.

Required changes:

- Track the previously observed flag set.
- Log `WARNING` when flags change from empty to non-empty.
- Log `DEBUG` when one non-empty flag set changes to another.
- Log `INFO` when the vehicle becomes armable.
- Combine the condition into one structured message with state and flags.

Example:

```text
Arming blocked state=IDLE flags=['THROTTLE', 'ANGLE']
```

Verification:

- Confirm unchanged flags produce no repeated warnings.
- Confirm changed flags and recovery each produce one correctly leveled record.

### [ ] APP-DIAG-006: Separate requested arm from confirmed FC arm state

Locations: `bt_app/bt_app/app.py`, `App._arm_handler()` and MSP state handling.

`ctx.armed` is set from `ARMController.is_arm_done`. This proves that the local
command sequence completed, not that Betaflight actually armed.

Required changes:

- Model and log `arm_requested`, `arm_sequence_complete`, and `fc_armed` as
  separate facts.
- Obtain reliable FC arm confirmation through MSP status/mode information.
- Include actual AUX1 readback and arming-disable flags in arm diagnostics.
- Log requested and confirmed edges at `INFO`.
- Log `ERROR` if FC confirmation does not arrive within a defined timeout.
- Do not use local sequence completion as the sole airborne/armed decision.

Verification:

- Test successful arm confirmation.
- Test command completion while Betaflight refuses to arm.
- Test delayed confirmation and confirmation timeout.
- Test disarm confirmation.

### [ ] APP-DIAG-007: Promote RC sanitization corrections from DEBUG

Location: `bt_app/bt_app/app.py`, `App._sanitize_rc_channels()`.

The sanitizer silently substitutes defaults for invalid channels at normal
`INFO` operation because corrections are logged only at `DEBUG`. A substituted
flight-control value is safety-relevant.

Required changes:

- Log the first invalid or changed invalid condition at `WARNING`.
- Include state, channel name/index, raw value, substituted value, raw output,
  and complete sanitized output.
- Rate-limit identical warnings.
- Log `INFO` once valid output resumes.
- Retain detailed per-channel output at `DEBUG` or `TRACE` if needed.

Verification:

- Test low, high, non-numeric, missing, and extra channel values.
- Verify logging is edge-based rather than emitted every loop.

### [ ] APP-DIAG-008: Add edge-triggered joystick diagnostics

Locations: `bt_app/bt_app/app.py`, `App.__handle_joy_rc()`,
`App._joystick_fs_enter()`, and `App.__joystick_fs_exit()`.

Joystick input changes the immutable `Context.request_rc` snapshot without
recording meaningful control edges, making it difficult to determine why the
state machine moved or refused to move.

Required changes:

- Log manual, takeoff, and mode-request changes at `INFO`.
- Log arm-switch changes at `INFO`.
- Log low-throttle arming eligibility changes at `DEBUG`.
- Log raw joystick channels at rate-limited `TRACE`.
- Keep failsafe entry at `WARNING`.
- Change successful communication recovery from `WARNING` to `INFO`.
- Include the timeout stage/duration from callback events where available.

Verification:

- Test each input edge and ensure steady input is silent.
- Test communication loss and recovery levels and context.

### [ ] APP-DIAG-009: Add decision context to state transitions

Locations: `bt_app/bt_app/app.py`, `App._handle_before_state_changed()` and
`App._state_changed_handler()`.

The state machine logs source and destination, but not the inputs that permitted
the transition. Controller reset messages are currently warnings even though
they describe expected behavior.

Required changes:

- Emit one structured `INFO` record per completed transition.
- Include previous/next state, altitude, altitude setpoint, armed/armable state,
  joystick requests, failsafe state, and relevant RC switch values.
- Log normal controller resets at `DEBUG`, not `WARNING`.
- Use `WARNING` only for transitions into degraded or failsafe operation.
- Avoid duplicate transition records between `sm.py` and `app.py`; select one
  authoritative structured log and let the other remain `DEBUG` if useful.

Verification:

- Exercise every state transition and confirm one authoritative record.
- Confirm failsafe transitions are prominent without duplicating messages.

## Low severity and cleanup

### [ ] APP-DIAG-010: Improve startup and shutdown lifecycle logs

Locations: `bt_app/bt_app/app.py`, initialization helpers and `App.run()`.

Required changes:

- Log successful MSP connection with transport type and endpoint at `INFO`.
- Log joystick listener endpoint and configured timeout values at `INFO` without
  decorative separators.
- Log controller and recorder startup completion at `DEBUG` or concise `INFO`.
- Log the effective log level rather than the hard-coded text
  `Application log level : DEBUG`.
- Log orderly shutdown start and completion at `INFO`.
- Log individual cleanup failures with `log.exception()` at `ERROR` while still
  attempting the remaining cleanup operations.

Progress (2026-08-02): signal handlers are temporary and restored after the run;
shutdown now attempts MSP, joystick, MAVLink, recorder, and parameter cleanup in
order, and one cleanup failure no longer prevents the remaining stops. The
application now also retries FCU connection three times, reports expected
connection failures without a traceback using exit code `4`, and cleans up
partially initialized resources. The remaining general startup and lifecycle
logging improvements are still open.

Verification:

- Test normal startup/shutdown and failures at each partial-startup stage.

### [ ] APP-DIAG-011: Remove misleading or noisy telemetry logging

Location: `bt_app/bt_app/app.py`, `App.__update_state()`.

Required changes:

- Do not log the same cached `vehicle_state` every control-loop iteration.
- Log state telemetry only when changed or at a fixed diagnostic interval.
- Remove the unexplained `battery_voltage + 20.0` diagnostic distortion or
  clearly mark raw and adjusted values separately and emit a one-time warning.
- Prefer structured Loguru arguments over f-strings for consistent formatting.

Verification:

- Confirm log volume remains bounded at `DEBUG` during a long steady flight.
- Confirm reported battery values identify their source and units accurately.

### [ ] APP-DIAG-012: Add a control-loop timing watchdog

Location: `bt_app/bt_app/app.py`, `App.run()`.

Required changes:

- Measure loop duration with `time.monotonic()`.
- Record rate-limited `DEBUG` timing statistics.
- Log `WARNING` when a loop exceeds its timing budget, including the current
  state and which stage consumed the time when measurable.
- Sleep against a monotonic deadline rather than sleeping a fixed duration
  after work, so execution time does not silently lower the loop frequency.

Verification:

- Inject a slow controller and slow recorder operation.
- Verify deadline overruns are visible and warnings are rate-limited.

## Logging-level policy

Use the following policy consistently:

| Level | Intended use |
|---|---|
| `TRACE` | Raw RC, raw MSP payloads, and per-loop PID details. |
| `DEBUG` | Rate-limited controller input/output, telemetry snapshots, and normal controller resets. |
| `INFO` | Startup completion, state transitions, mode/arm request edges, recovery, and orderly shutdown. |
| `WARNING` | Degraded or stale input, arming blocked, RC sanitization, and failsafe entry. |
| `ERROR` | Invalid controller output, failed MSP command, failed required service, or failed arm confirmation. |
| `CRITICAL` | Control-loop termination or inability to produce safe RC while armed. |

## General implementation rules

- Prefer state-change logs over messages repeated in every loop.
- Rate-limit periodic diagnostics and include monotonic timestamps for
  cross-stream correlation.
- Use structured Loguru arguments rather than f-strings where practical.
- Include units in field names, for example `altitude_m`, `age_s`, and
  `throttle_pwm`.
- Never log an error without state and operation context.
- Do not let logging itself block or materially slow the control loop.
- Preserve detailed high-rate data in the recorder; keep console output concise.
- For control-loop failures, explicitly replace stale RC output or enter a
  defined failsafe. Continuing the last command can be more dangerous than
  exiting the process.

## Suggested resolution order

1. APP-DIAG-001: telemetry freshness.
2. APP-DIAG-003: safe handling of invalid RC output.
3. APP-DIAG-002: loop exception boundary and cleanup.
4. APP-DIAG-004: takeoff, attitude, motor, and PID recording.
5. APP-DIAG-006: confirmed FC arm state.
6. APP-DIAG-005: arming-disable edge logs.
7. APP-DIAG-007: sanitizer diagnostics.
8. APP-DIAG-008: joystick input edges.
9. APP-DIAG-009: structured transition context.
10. APP-DIAG-012: timing watchdog.
11. APP-DIAG-010: lifecycle log cleanup.
12. APP-DIAG-011: general noise and misleading telemetry cleanup.
