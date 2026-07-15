
## Drone side

```
uv run bt-app run -c bat_config/vehicle_config.yaml
```

```
uv run bt-joy-server run -c bat_config/joy_server.yaml
```

## Client

### joy

```
uv run bt-joy run -c output/boxer.yaml
```

### QopenHD

```
./QOpenHD
```

### Record

- drone side

```bash 
uv run bt-gst-record
```

- Home
```bash
<drone ip>:8001
```