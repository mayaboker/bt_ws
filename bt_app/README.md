

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
touchdown. State transitions are printed in bold cyan.

## Usage

Radiomaster BOXER config

|     |   |   |
|---  |---|---|
| SA  | idle / manual  |   |
| SB  | alt hold/ courser / tracking  |   |
| SC  | enabler  | to enable move from low to high  |
| SD  | auto takeoff  |   |


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

### ALT_HOLD -> tracking(hover) before auto enable
- SB > 1000
