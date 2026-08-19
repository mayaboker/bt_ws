

## `bt_gst` ZMQ interface

The MessagePack/ZMQ interface between `bt_app` and `bt_gst` is documented in
[`bt_gst/docs/design/bt_app_zmq_interface.md`](../bt_gst/docs/design/bt_app_zmq_interface.md).

## Run in simulation

```bash title="sim"
./bt_bringup/launch/launch.sh
# select sim
```

```bash title="joy"
./bt_bringup/launch/launch.sh
# select joy
```

```bash
#from bt_app folder
uv run bt-app run -c config/vehicle_config.yaml
```

### MAVLink RC takeoff and landing scenario

With Gazebo, SITL, and `bt-app` already running, execute the self-checking RC
override scenario from the `bt_app` directory:

```bash
uv run python example/send_rc.py
```

The script waits for live MAVLink state and altitude telemetry while it arms,
requests automatic takeoff, confirms `ALT_HOLD`, switches to `MANUAL`, descends,
lands, and disarms. It is intended for SITL only. Run `--help` to override the
UDP endpoints, timeouts, RC rate, five-second ALT_HOLD dwell, slow-descent
throttle, or touchdown altitude.

To continue from automatic takeoff into red-target tracking, start `bt-gst` and
`bt-app` with the detector visible, then run:

```bash
uv run python example/send_rc_takeoff_tracker.py
```

The script selects tracker1 and retries momentary SF pulses until `TRACK` is
observed. It waits for the tracker to return automatically to `ALT_HOLD`, then
lands and disarms through MANUAL mode. Tracker entry and tracking timeouts first
disable tracking and attempt the same controlled landing before reporting
failure. Run `--help` to configure the pulse duration and both timeouts.

To test a purely manual climb to 3 m before entering ALT_HOLD for 10 seconds,
then return to MANUAL for landing and disarm, run:

```bash
uv run python example/send_rc_manual_alt_hold.py
```

The MANUAL throttle starts at 1500 and ramps at 10 PWM per second, capped at
1680 (just above the configured 1660 hover baseline), until altitude reaches
3 m. The low cap limits upward momentum before ALT_HOLD. Use `--help` to adjust
the target, throttle ramp, maximum throttle, hold duration, descent throttle,
and safety timeouts.

To test returning to MANUAL between two ALT_HOLD periods, run:

```bash
uv run python example/send_rc_manual_reentry.py
```

This scenario climbs slowly to 3 m, holds ALT_HOLD for 10 seconds, attempts a
10-second MANUAL hover at throttle 1660, re-enters ALT_HOLD for 30 seconds,
then returns to MANUAL and controls vertical speed to a 1 m/s descent before
touchdown and disarm. The descent controller may command above the 1660 hover
throttle, up to 1800, to brake excessive downward speed.

To test automatic takeoff followed by clockwise and counter-clockwise yaw turns
in ALT_HOLD, run:

```bash
uv run python example/send_rc_auto_yaw.py
```

The script uses a conservative yaw input of 1650 (approximately 10 degrees per
second), publishes MSP attitude through MAVLink, and accumulates wrapped heading
changes until each measured turn reaches 360 degrees. It centers yaw between
turns, then performs the controlled 1 m/s MANUAL descent and disarms after
touchdown. State transitions are printed in bold cyan. `--cw-yaw-rc` controls
the simulated joystick input; `--yaw-rate` is an expected-rate value used for
timing and diagnostics, while the application controller still enforces its
configured `HY_MAX_RATE`, deadband, and expo.

To test a conservative balanced roll maneuver after automatic takeoff, run:

```bash
uv run python example/send_rc_auto_roll.py
```

The default ALT_HOLD pattern commands roll RC 1300 left for two seconds, 1700
right for four seconds, then 1300 left for two seconds before centering. This
L-R-L impulse approximately cancels lateral velocity and displacement. The
script logs commanded roll, measured attitude, derived roll rate, peak roll,
and altitude span. It enforces roll and altitude safety limits, waits for
centered recovery, then descends at 1 m/s and disarms.

To run the same balanced maneuver on the pitch axis, run:

```bash
uv run python example/send_rc_auto_pitch.py
```

The pitch joystick command is restricted to RC 1400–1600. The default uses a
16-second raised-cosine profile through center → forward → center → backward →
center → forward → center. This removes abrupt reversals while preserving the
balanced negative/positive/negative command areas. Larger pitch amplitudes are
rejected before flight rather than relying only on the measured-angle cutoff.
It logs pitch angle, derived pitch rate, roll, yaw, altitude, peak pitch, and
altitude span while enforcing 25-degree pitch and 1 m altitude-drift limits.

## Usage

Radiomaster BOXER config

| Switch | Function | Values |
|---|---|---|
| SA | manual / altitude hold | low / high |
| SB | tracker mode | `1000` disabled, `1500` tracker1, `2000` tracker2 |
| SD | auto takeoff | low / high |
| SE | arm | low / high |
| SF | tracking entry | momentary `1000` to `2000` |


### Idle -> Manual

- SA to manual (switch down)
- throttle down + yaw right for arming
- open throttle after ARM

### Manual -> ALT_hole
- SA switch up 
- keep alt
- allow roll, pitch, yaw

### Idle -> takeoff
- SD switch down
- throttle down + yaw right for arming

### Manual -> Idle (disarmed)
- land
- throttle low
- SA switch up (idle)
- throttle down + yaw left for disarmed

### ALT_HOLD -> tracking

- Select tracker1 or tracker2 with SB.
- Wait for a valid tracker lock.
- Press SF once. A press before lock is ignored.
- Move SB to disabled to return immediately to `ALT_HOLD`.
