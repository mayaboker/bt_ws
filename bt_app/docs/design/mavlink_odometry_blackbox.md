# MAVLink Odometry Blackbox Logging

## Summary

bt-app listens for MAVLink 2 traffic on UDP 14551, validates `ODOMETRY`, and
records every accepted sample received during an armed blackbox session. The
external bridge must be configured to send its traffic to that port. Odometry
is diagnostic-only and never changes flight state or controller output.

## Input and validation

`ODOMETRY` is accepted from any sender. Samples must use `LOCAL_NED` as the
parent frame and `BODY_FRD` as the child frame, and must contain a positive
source timestamp, finite velocity and quaternion values, and a nonzero
quaternion norm. The body-FRD velocity is rotated by the normalized quaternion
to derive local-NED north, east, and down velocity.

Malformed and rejected samples are counted by the MAVLink service and do not
reach the blackbox. Samples received outside an active armed session are
ignored. Source system, component, address, and port are neither validated nor
stored.

## Storage

Schema-version-2 sessions add `odometry-NNNNNN.parquet` files alongside frame
and event chunks. Each odometry row contains its source epoch and receive
monotonic timestamps, flight elapsed time, sample index, MAVLink sequence,
reset counter, body-FRD velocity, and derived local-NED velocity. A chunk with
no odometry has a null `odometry` inventory entry and no odometry file.

The recorder uses a bounded FIFO telemetry buffer. Lifecycle controls do not
consume telemetry capacity. Under pressure, new odometry is dropped, and a new
control frame evicts the oldest queued odometry before the frame itself can be
dropped. Session metadata records written and dropped counts independently for
frames and odometry.

Writes remain atomic and Zstandard-compressed. Existing schema-version-1
sessions remain unchanged and recoverable.

## Verification

Automated coverage includes frame and quaternion validation, cardinal and
tilted body-to-NED rotations, shared parameter/odometry reception, armed-only
recording, Parquet schemas and chunk inventories, empty-stream behavior,
interrupted recovery, writer failure, and queue priority. Deployment validation
should graph body velocity against derived north/east/down velocity during a
live takeoff and landing.
