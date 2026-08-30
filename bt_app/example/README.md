# Flight Scenario Examples

This directory contains 12 flight scenarios and two supporting utilities for
exercising `bt-app` through MAVLink RC overrides and visual tracking.

## Scenario menu

| Scenario | Flight flow | Purpose |
|---|---|---|
| [`send_rc.py`](send_rc.py) | `IDLE -> MANUAL -> TAKEOFF -> ALT_HOLD -> MANUAL -> IDLE` | Baseline automatic takeoff, altitude hold, manual descent, touchdown, and disarm. |
| [`send_rc_manual_alt_hold.py`](send_rc_manual_alt_hold.py) | Manual climb -> ALT_HOLD -> manual landing | Gradually climbs to a target altitude, holds it, and lands using fixed manual throttle. |
| [`send_rc_manual_alt_hold_100.py`](send_rc_manual_alt_hold_100.py) | Manual climb -> ALT_HOLD -> selector scan -> TRACK -> ALT_HOLD -> landing | Performs a high-altitude climb and vertical image-selector scan before tracking a target. The current default target altitude is 50 m despite the `_100` filename. |
| [`send_rc_manual_reentry.py`](send_rc_manual_reentry.py) | Manual climb -> ALT_HOLD -> MANUAL hover -> ALT_HOLD -> landing | Tests two ALT_HOLD entries separated by a manual-hover attempt, followed by feedback-controlled descent. |
| [`send_rc_auto_yaw.py`](send_rc_auto_yaw.py) | Auto takeoff -> ALT_HOLD yaw turns -> landing | Executes measured clockwise and counter-clockwise yaw rotations before controlled descent. |
| [`send_rc_auto_roll.py`](send_rc_auto_roll.py) | Auto takeoff -> ALT_HOLD roll pattern -> landing | Applies balanced left/right roll commands while checking attitude and altitude drift. |
| [`send_rc_auto_pitch.py`](send_rc_auto_pitch.py) | Auto takeoff -> ALT_HOLD pitch pattern -> landing | Applies a smooth forward/backward pitch pattern while monitoring pitch, pitch rate, and altitude drift. |
| [`send_rc_auto_pitch_hold.py`](send_rc_auto_pitch_hold.py) | Auto takeoff -> forward-pitch hold -> recovery -> landing | Uses attitude feedback to hold a forward pitch, normally -10 degrees, and records diagnostic CSV data. |
| [`send_rc_takeoff_diagnostic.py`](send_rc_takeoff_diagnostic.py) | Auto takeoff -> TAKEOFF/ALT_HOLD recording -> landing | Records takeoff parameters, altitude, attitude, vertical speed, requested RC, and controller output. |
| [`send_rc_takeoff_tracker.py`](send_rc_takeoff_tracker.py) | Auto takeoff -> ALT_HOLD -> TRACK -> ALT_HOLD -> landing | Pulses tracker enable until tracking starts, waits for its automatic exit, and lands. |
| [`send_rc_takeoff_yaw_tracker.py`](send_rc_takeoff_yaw_tracker.py) | Auto takeoff -> yaw search -> TRACK -> ALT_HOLD -> landing | Yaws clockwise until a visual target is acquired, tracks it, and lands after tracking exits. |
| [`send_rc_takeoff_target_selector.py`](send_rc_takeoff_target_selector.py) | Auto takeoff -> image selection -> TRACK -> ALT_HOLD -> landing | Moves an image-space selector to a named left, center, or right target without moving the aircraft in roll or pitch. |

## Supporting utilities

| Utility | Purpose |
|---|---|
| [`mavlink_mock.py`](mavlink_mock.py) | Provides a mock MAVLink flight-controller peer and reports RC override ignore/release behavior. |
| [`yolo_one_frame.py`](yolo_one_frame.py) | Runs YOLO inference on one image and displays the annotated detections. It currently uses workspace-specific model and image paths. |

## Common lifecycle

Most scenarios follow this state sequence:

```text
telemetry -> arm in MANUAL -> climb/takeoff -> ALT_HOLD
          -> optional maneuver or tracking
          -> MANUAL landing -> touchdown confirmation -> disarm/IDLE
```

## Safety behavior

- Failures before takeoff send a ground-safe disarm command.
- Most airborne failures stop RC traffic so the `bt-app` failsafe can recover.
- Maneuver scenarios enforce mode, telemetry, attitude, altitude-drift, and/or timeout limits.
- Touchdown normally requires three consecutive altitude samples below the configured threshold.

## Verification notes

- All example Python files compile successfully.
- The associated scenario tests require `pymavlink`; without it, the tests fail during collection.
- The red-target scenarios require the detector, `bt-gst`, and `bt-app` to already be running.
