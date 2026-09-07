# How to use

```bash title="run the application"
cd bt_app
uv run bt-app run
```

```bash title="move the drone and box to request position"
/home/user/projects/gz_betaflight_bridge/scripts/worlds/set_sensor_world_poses.sh

/home/user/projects/gz_betaflight_bridge/scripts/worlds/set_sensor_world_poses.sh \
    --drone-x -15 --drone-y 0 --drone-z 0.5 \
    --box-x 40 --box-y 15 --box-z 0.5
```

```bash title="visual"
./bt_bringup/launch/run_gst.sh
```

```bash title="joy"
cd bt_app
uv run python -m joy_scenarios.04_tracker_glide
```