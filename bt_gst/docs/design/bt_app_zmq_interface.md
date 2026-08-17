# `bt_app` and `bt_gst` ZMQ interface

`bt_gst` receives tracking-control requests and publishes red-object detection
snapshots as single-frame MessagePack maps. Delivery is intentionally lossy:
current state matters more than processing every frame.

## Channels

| Channel | Default endpoint | `bt_gst` | `bt_app` |
|---|---|---|---|
| Control requests | `tcp://127.0.0.1:5555` | SUB, binds | PUB, connects |
| Detection telemetry | `tcp://127.0.0.1:5556` | PUB, binds | SUB, connects |

There is no separate ZMQ topic frame. Subscribers must use `SUBSCRIBE=b""`
and inspect the MessagePack `type` field. Messages sent before PUB/SUB setup
completes can be lost.

## Control requests

The detector service retains the existing request shapes used by `bt_app`:

```json
{"type": "start", "x": 320, "y": 240}
{"type": "adjustment", "delta_x": -5, "delta_y": 3}
{"type": "resize", "width": 120, "height": 80}
{"type": "stop"}
```

`start` activates and resets detector lock acquisition; `stop` clears it.
The position, adjustment, and resize fields also control the optional cyan
cursor drawn by the video overlay. Pending valid requests are applied in
receive order.

## Red-detection telemetry

```json
{
  "type": "red-detection",
  "frame_id": 42,
  "timestamp_ns": 1366666653,
  "found": true,
  "x": 210,
  "y": 130,
  "width": 80,
  "height": 60,
  "locked": true,
  "lock_found_frames": 10,
  "lock_missing_frames": 0
}
```

`x` and `y` are the top-left corner of the detected box. When `found` is
false, all box fields are zero. `timestamp_ns` is the GStreamer presentation
timestamp or `null` when unavailable.

After `start`, lock becomes true after ten consecutive detections and false
after five consecutive misses. Older red-detection messages without lock
fields decode as unlocked.

## Configuration

```yaml
detector:
  enabled: true
  overlay_enabled: true
zmq:
  enabled: true
  request_endpoint: tcp://127.0.0.1:5555
  telemetry_endpoint: tcp://127.0.0.1:5556
  bind: true
```

ZMQ may only be enabled with the detector. Consumers should treat telemetry
as snapshots, clear target state after `found=false` or a timeout, and never
assume consecutive frame IDs.
