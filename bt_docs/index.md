# BT Application Review And Architecture Notes

## Findings

High: `bt_app/bt_app/app.py:142` can crash when entering `FAILSAFE`.
`FailSafeController.update()` calls `self.alt_pid.update(...)`, but `alt_pid` is
never initialized because `_setup()` is not called in
`FailSafeController.__init__`. First `MANUAL -> FAILSAFE` transition will likely
raise `AttributeError`. Fix by initializing the PID in the constructor or making
failsafe return a known safe RC command until altitude control is configured.

High: `bt_app/bt_app/app.py:137` can crash in `MANUAL` before joystick data
arrives. `JoyZmqAdapter.update()` returns `last_rc_channels`, initially `[]`.
Then `app.py:139` may write `channels[4]`, and `matching()` may index
throttle/AUX channels. Validate joystick RC length before mutation, and fall back
to neutral/disarmed channels or remain in `IDLE` until a valid RC frame exists.

Medium: `bt_app/bt_app/app.py:171` only checks truthiness, not RC shape or range.
A short list, wrong channel count, `None` values, or out-of-range values can
still reach `set_rc(rc_channels[:8])`. Add a validator requiring at least 8
numeric channels clamped or rejected within expected RC bounds.

Medium: `bt_app/bt_app/app.py:163` starts MSP and joystick threads, but
`app.py:176` only handles `KeyboardInterrupt` and does no cleanup. On exceptions,
the process can leave sockets, threads, or transport state dirty. Add `finally`
cleanup: stop joystick adapter, stop dispatcher, close MSP transport.
`MSPAdapter` should expose a `stop()` method.

Medium: `bt_app/bt_app/app.py:168` delegates failsafe entirely to the state
machine, but the current transition only covers `MANUAL -> FAILSAFE`. If joystick
failsafe occurs during `ARM`, `TAKEOFF`, or another future autonomous state, this
app will keep running that state's controller. For a flight app, failsafe should
usually be a global or high-priority transition, or checked before normal state
resolution.

## Main Loop

`App.run()` is the central control loop:

1. `__load_drone_interface()` creates `MSPAdapter`, opens Betaflight MSP,
   schedules state/altitude/RC polling, and starts the dispatcher.
2. `__load_controllers()` starts the joystick ZMQ adapter and registers
   controllers for `MANUAL`, `FAILSAFE`, `TAKEOFF`, and `ARM`.
3. Every tick:
   - `__update_state()` reads Betaflight state, altitude, and RC into `Context`.
   - `robot_sm.resolve()` evaluates transition conditions.
   - `__resolve_rc()` selects the controller for the current state.
   - `matching()` enforces manual/external-pilot RC rules.
   - `dispatcher.set_rc()` sends the final 8 RC channels to Betaflight.
   - The loop sleeps at `1 / FREQ_HZ`.

## Diagram Mapping

- `BF`: Betaflight flight controller or SITL target.
- `MSP Driver`: `MSPAdapter` plus dispatcher. It reads telemetry, state, and RC
  from BF and sends RC commands back.
- `Application / State machine`: `App`, `Context`, and `Robot_StateMachine`.
  This decides mode: `IDLE`, `ARM`, `TAKEOFF`, `MANUAL`, `FAILSAFE`.
- `2d controller`: flight-control logic that converts target error into control
  commands. In this codebase, `TakeoffController`, `FailSafeController`, and
  future visual controllers fit this role.
- `tracker`: vision tracker that produces target offsets such as `dx/dy`.
- `image source`: camera or video input feeding the tracker.
- `telemetry`: vehicle status, altitude, RC, arming flags, and related status
  coming from MSP.
- `OSD`: overlay/display layer that can consume telemetry, tracker output, and
  app state.

The intended flow is: image source feeds tracker, tracker outputs `dx/dy` to a
controller, the controller/app produces RC, MSP sends RC to BF, and BF telemetry
returns through MSP into the app and OSD.
