

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
