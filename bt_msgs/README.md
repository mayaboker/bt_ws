# bt-msgs

Shared MessagePack message types for BT workspace processes.

`TrackerResultMessage` is the immutable generic tracker-result protocol used
between `bt_gst` and `bt_app`. It carries the source frame and nanosecond media
timestamp, lock state, bounding box, normalized score, tracker state, and
center-relative deltas.

The Python model is a frozen slots dataclass. Its wire representation is an
explicit string-keyed MessagePack map: all known keys are required during
decoding, while unknown keys are ignored for future additive evolution.
Malformed MessagePack and validation failures are reported as `ValueError`.

State value `TRACKER_STATE_UNKNOWN` (`0`) is the only state currently defined.
The red detector publishes zero placeholders for tracker ID, score, state, and
deltas until those values have authoritative producers.
