# Red Detection to ZMQ Publication Flow

`bt_gst` publishes a `bt_msgs.TrackerResultMessage` whenever frames pass through
the red detector. The design keeps all serialization and network work away from
the GStreamer streaming thread so a slow or disconnected subscriber cannot
stall video processing.

## Data flow

```mermaid
flowchart LR
    Source[Camera, file, or Gazebo source]
    Convert[RGB conversion]
    Detector[controlledreddetect<br/>name=red_detector]
    Probe[Detector source-pad probe]
    Signal[Single latest-message slot]
    Worker[ZMQ publisher thread<br/>maximum 30 Hz]
    Socket[ZMQ PUB socket<br/>tcp://127.0.0.1:5556]
    Subscriber[Subscriber]
    Overlay[Cairo overlay]
    Stream[H.264 RTP stream]

    Source --> Convert --> Detector --> Probe
    Probe --> Overlay --> Stream
    Probe -. frame_id and PTS .-> Signal
    Signal --> Worker --> Socket --> Subscriber
```

The detector attaches `GstRedDetectionMeta` to each buffer. The probe is placed
on the detector's source pad, where the metadata is available before later
video conversion, overlay, encoding, or streaming stages.

The probe reads the buffer PTS and assigns a sequential frame ID. It does not
copy frame pixels or serialize the message. If the overlay is enabled, the same
probe also reads the custom metadata for drawing the bounding box.

## Thread boundary

The pad probe runs synchronously on a GStreamer streaming thread. Anything slow
inside this callback would directly increase frame-processing latency.

```mermaid
sequenceDiagram
    participant GST as GStreamer streaming thread
    participant P as Source-pad probe
    participant W as ZMQ publisher thread
    participant Z as ZMQ subscriber

    GST->>P: Buffer reaches red_detector src pad
    opt Overlay enabled
        P->>P: Read metadata and update overlay state
    end
    P->>P: Create TrackerResultMessage(frame_id, PTS)
    P->>W: Replace latest message and notify
    P-->>GST: PadProbeReturn.OK
    Note over GST,P: No encoding, socket operation, or frame copy

    W->>W: Coalesce pending notifications
    W->>W: Apply maximum publication rate
    W->>W: Encode latest TrackerResultMessage
    W->>Z: Nonblocking MessagePack send
```

Only a small immutable message crosses the thread boundary. Repeated frames
replace the single pending message instead of building an unbounded queue.
Consequently, the publisher sends the newest available result and does not
attempt to catch up by sending stale results.

## Publisher behavior

`ZmqFramePublisher` owns its ZMQ context and PUB socket entirely within its
worker thread. The socket is configured with:

- `SNDHWM=1` to keep at most one queued outbound message.
- `LINGER=0` so shutdown does not wait for queued packets.
- `NOBLOCK` for sends, dropping a packet when the socket cannot accept it.
- A configurable maximum rate, set to 30 Hz by the bringup configuration.

MessagePack encoding happens in the publisher thread after rate limiting.
Socket bind failures are returned during startup before the GStreamer pipeline
enters `PLAYING`.

```mermaid
stateDiagram-v2
    [*] --> Starting
    Starting --> Ready: socket bind/connect succeeds
    Starting --> Failed: socket setup fails
    Ready --> Pending: detector frame message
    Pending --> Pending: newer message replaces pending message
    Pending --> Ready: rate limit allows nonblocking send
    Ready --> Stopping: pipeline shutdown
    Pending --> Stopping: pipeline shutdown
    Stopping --> [*]: socket closes with linger 0
```

## Configuration

The publisher is disabled by default in the Python configuration and enabled
by `bt_bringup/launch/gst.yaml`:

```yaml
zmq:
  enabled: true
  endpoint: tcp://127.0.0.1:5556
  bind: true
  max_rate_hz: 30
```

ZMQ publication requires `detector.enabled: true`. The endpoint must be a
non-empty string and `max_rate_hz` must be a positive integer.

## Current payload

`TrackerResultMessage` owns the MessagePack representation:

```python
{
    "frame_id": 42,
    "timestamp": 123456789,
}
```

`frame_id` starts at 1 and increments for every detector buffer. Publication
rate limiting may therefore create gaps between received IDs. `timestamp` is
the buffer's GStreamer PTS in nanoseconds, or `None` when no valid PTS exists.

The existing `bt_app` subscriber ignores this basic message because it has no
`type: "red-detection"` field.

## Future detector fields

When the detector message becomes available from `bt_msgs`, the integration
should preserve the same performance boundary:

1. Read `GstRedDetectionMeta` while the buffer is valid in the pad probe.
2. Copy only scalar values such as `found` and bounding-box coordinates into
   the `bt_msgs` value object.
3. Replace the pending value in a single-slot handoff; never pass a
   `Gst.Buffer` or metadata object to the worker.
4. Serialize the `bt_msgs` value and send it only from the publisher thread.

```mermaid
flowchart LR
    Meta[GstRedDetectionMeta<br/>valid with current buffer]
    Copy[Copy scalar fields]
    Message[Extended TrackerResultMessage]
    Latest[Single latest-value slot]
    Encode[Encode in publisher thread]
    Publish[Nonblocking ZMQ publish]

    Meta --> Copy --> Message --> Latest --> Encode --> Publish
```

This future change adds result data without introducing frame copies, an
appsink branch, network I/O on the streaming thread, or an accumulating message
queue.
