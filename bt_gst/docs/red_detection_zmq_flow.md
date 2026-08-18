# Red Detection to ZMQ Publication Flow

This document describes the current `bt_gst` implementation. The red detector
adds bounding-box metadata to every video buffer, while the ZMQ publisher
currently sends only the buffer's frame ID and presentation timestamp. Red
detection fields are not on the ZMQ wire yet.

The design keeps MessagePack encoding and all socket operations away from the
GStreamer streaming thread so a slow or disconnected subscriber cannot stall
the video pipeline.

## End-to-end flow

```mermaid
flowchart LR
    Source[Camera, file, or<br/>Gazebo source]
    RGB[Convert to RGB]
    Detector[controlledreddetect<br/>name=red_detector]
    Probe[Source-pad probe]
    OptionalOverlay{Overlay enabled?}
    Overlay[Convert to BGRx<br/>and draw bounding box]
    Tee[video_tee]
    RTP[H.264 RTP/UDP branch]
    Preview[Optional local preview]

    Message[TrackerResultMessage<br/>frame_id + timestamp]
    Latest[Single latest-message slot]
    Worker[ZMQ publisher thread<br/>rate limited]
    Pub[ZMQ PUB socket]
    Sub[Subscriber]

    Source --> RGB --> Detector --> Probe --> OptionalOverlay
    OptionalOverlay -->|yes| Overlay --> Tee
    OptionalOverlay -->|no| Tee
    Tee --> RTP
    Tee -. optional .-> Preview

    Probe -. small value handoff .-> Message --> Latest
    Latest --> Worker --> Pub --> Sub
```

`controlledreddetect` processes the RGB pixels in place and attaches
`GstRedDetectionMeta` with these fields:

- `found`
- `x` and `y`
- `width` and `height`

The probe is installed on the detector's `src` pad, so both the custom metadata
and buffer PTS are still available before later conversion, overlay, encoding,
or streaming stages.

## Work performed by the pad probe

The pad probe runs synchronously on a GStreamer streaming thread. Its execution
time directly contributes to frame-processing latency.

```mermaid
sequenceDiagram
    participant GST as GStreamer streaming thread
    participant Probe as red_detector src-pad probe
    participant Slot as Latest-message slot
    participant Worker as ZMQ publisher thread
    participant SUB as ZMQ subscriber

    GST->>Probe: Buffer reaches detector src pad
    Probe->>Probe: Read buffer PTS
    Probe->>Probe: Allocate next frame_id
    opt Overlay enabled
        Probe->>Probe: Read GstRedDetectionMeta
        Probe->>Probe: Update thread-safe overlay state
    end
    Probe->>Slot: Replace pending TrackerResultMessage
    Probe-->>GST: PadProbeReturn.OK

    Note over Probe,Slot: No pixel copy, MessagePack encoding, or socket call

    Worker->>Slot: Wait for and take latest message
    Worker->>Worker: Enforce maximum rate
    Worker->>Worker: message.encode()
    Worker->>SUB: Nonblocking ZMQ send
```

For every non-null buffer, the publication side of the probe performs only:

1. `int(buffer.pts)` and normalization of `GST_CLOCK_TIME_NONE` to `None`.
2. `next(frame_ids)`, where IDs start at 1 for each pipeline run.
3. Construction of an immutable `TrackerResultMessage`.
4. Replacement of `_pending_message` while holding a short-lived condition
   lock, followed by a worker notification.

The probe never passes a `Gst.Buffer` or `GstCustomMeta` to another thread. If
GStreamer provides no buffer, no frame ID is consumed and no message is
published.

## Latest-value and rate-limit behavior

The publisher uses one pending-message slot rather than a queue. A new detector
frame replaces an older pending message. The first message can be sent
immediately; later sends are separated by at least `1 / max_rate_hz` seconds
using `time.monotonic()`.

```mermaid
stateDiagram-v2
    [*] --> Empty
    Empty --> Pending: publish(message)
    Pending --> Pending: replace with newer message
    Pending --> Sending: rate deadline reached
    Sending --> Empty: encode and send
    Sending --> Pending: newer frame arrives
    Empty --> Stopping: stop()
    Pending --> Stopping: stop()
    Stopping --> [*]
```

At the default 30 Hz limit, a source running faster than 30 FPS will have
intermediate messages coalesced. Frame IDs are assigned before coalescing, so
gaps in received IDs are expected and show that newer frames replaced older
pending frames.

## Message and wire format

`bt_msgs.TrackerResultMessage` owns the MessagePack representation:

```python
TrackerResultMessage(
    frame_id=42,
    timestamp=123456789,
)
```

Wire mapping:

```python
{
    "frame_id": 42,
    "timestamp": 123456789,
}
```

`timestamp` is the buffer's GStreamer PTS in nanoseconds, or `None` when the
buffer has no valid PTS. It is media time, not Unix wall-clock time, and may
restart when a pipeline restarts or a file is seeked.

The existing `bt_app` red-detection subscriber ignores this basic message
because it has no `type: "red-detection"` field.

## ZMQ ownership and lifecycle

`ZmqFramePublisher` creates and uses its ZMQ context and PUB socket only inside
its daemon worker thread. ZMQ sockets are not shared across threads.

```mermaid
sequenceDiagram
    participant Runner as run_pipeline
    participant Worker as Publisher worker
    participant ZMQ as ZMQ context/socket

    Runner->>Worker: start()
    Worker->>ZMQ: Create PUB socket
    Worker->>ZMQ: Set LINGER=0 and SNDHWM=1
    alt bind is true
        Worker->>ZMQ: bind(endpoint)
    else bind is false
        Worker->>ZMQ: connect(endpoint)
    end
    Worker-->>Runner: Ready or startup error
    Runner->>Runner: Set pipeline PLAYING

    Note over Runner,Worker: Pipeline playback starts only after socket setup

    Runner->>Runner: Set pipeline NULL
    Runner->>Worker: stop()
    Worker->>ZMQ: Close socket with linger 0
    Worker->>ZMQ: Terminate context
    Worker-->>Runner: Thread joined
```

Socket behavior:

- `SNDHWM=1` limits ZeroMQ's outbound queue.
- `LINGER=0` prevents queued packets from delaying shutdown.
- `NOBLOCK` prevents a send from waiting for socket capacity.
- `zmq.Again` drops that message and is logged at debug level.
- Other `zmq.ZMQError` send failures are logged and the worker continues.
- There is no replay, acknowledgement, or delivery guarantee. Messages sent
  before a subscriber finishes connecting, or while it is unavailable, are
  lost by normal PUB/SUB semantics.

During startup, socket creation and bind/connect failures are returned to
`run_pipeline()` as `PipelineRunError`; the pipeline does not enter `PLAYING`.
During shutdown, the pipeline enters `NULL` before the publisher is stopped,
preventing new probe submissions while the worker closes.

## Configuration

The publisher is disabled by the Python defaults and enabled by
`bt_bringup/launch/gst.yaml`:

```yaml
detector:
  enabled: true

zmq:
  enabled: true
  endpoint: tcp://127.0.0.1:5556
  bind: true
  max_rate_hz: 30
```

Validation requires:

- ZMQ publication can be enabled only when the detector is enabled.
- `endpoint` is a non-empty string.
- `bind` and `enabled` are booleans.
- `max_rate_hz` is a positive integer.

With the checked-in configuration, `bt_gst` binds the PUB socket and
subscribers connect to it.

## Observe the stream

Start `bt_gst`:

```bash
./bt_bringup/launch/run_gst.sh
```

Run the diagnostic subscriber from another terminal:

```bash
bt_gst/.venv/bin/python bt_gst/scripts/listen_zmq.py
```

Example output:

```text
frame_id=42 timestamp=123456789
frame_id=43 timestamp=156790122
```

## Known limitations from the code review

- The ZMQ message does not contain `found` or bounding-box fields yet. Those
  values are used only by the optional Cairo overlay.
- An unexpected exception outside the handled ZMQ send errors—for example, an
  unexpected encoding failure—terminates the daemon publisher thread. The
  pipeline currently has no worker-health signal and would continue running
  without publishing further messages.
- `publish()` silently accepts and replaces messages even if the worker has
  already terminated unexpectedly; only normal startup and shutdown failures
  are surfaced to the pipeline runner.
- PUB/SUB intentionally favors freshness over reliability. There is no
  backpressure, retry, history, or subscriber-presence detection.

## Adding red-detection fields later

When `TrackerResultMessage` is extended, preserve the current performance
boundary:

1. Read `GstRedDetectionMeta` while the current buffer is valid in the probe.
2. Copy only its scalar values into the shared `bt_msgs` value object.
3. Replace the single pending message; never pass a GStreamer object to the
   worker.
4. Encode and send the extended message only from the publisher thread.

```mermaid
flowchart LR
    Meta[GstRedDetectionMeta<br/>current buffer lifetime]
    Copy[Copy found and bbox scalars]
    Message[Extended TrackerResultMessage]
    Slot[Single latest-message slot]
    Encode[Encode in worker thread]
    Send[Nonblocking ZMQ send]

    Meta --> Copy --> Message --> Slot --> Encode --> Send
```

This keeps the pipeline free of frame copies, an appsink branch, network I/O on
the streaming thread, and an accumulating message queue.
