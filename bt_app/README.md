

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
