 # MAVLink Odometry Blackbox Logging

  ## Documentation Artifact

  Save this approved design as:

  bt_app/docs/design/mavlink_odometry_blackbox.md

  The document will record the architecture, schema, failure behavior, tests, and assumptions below for future implementation.

  ## Summary

  Route bridge MAVLink traffic to bt-app on UDP 14551, decode ODOMETRY, and record every accepted armed-flight sample in separate
  Parquet chunks. Logging remains diagnostic-only.

  ## Key Changes

  - Change the bridge MAVLink destination from 14550 to 14551.
  - Extend bt-app’s existing MAVLink parser to accept ODOMETRY from any sender.
  - Require LOCAL_NED and BODY_FRD frames with valid finite velocity, timestamp, and quaternion data.
  - Derive local-NED velocity from the body-FRD velocity and quaternion.
  - Add a nonblocking record_odometry(sample) blackbox interface.
  - Write odometry-NNNNNN.parquet files alongside frame and event chunks.
  - Record:
      - Source epoch and receive-monotonic timestamps
      - Flight elapsed time and sample index
      - MAVLink sequence and reset counter

  - Bump the blackbox schema to version 3 and add odometry files and counters to session metadata.
  - Drop odometry before core flight frames under queue pressure and count all dropped samples.

  - Missing, stale, malformed, or rejected odometry never affects startup or flight state.
  - No odometry file is created when a chunk contains no samples.
  - Existing schema-version-2 sessions remain unchanged and readable.
  - Source identity is neither validated nor stored.

  ## Test Plan

  - Test valid decoding, frame validation, timestamps, sequence, and reset counters.
  - Test body-to-NED conversion at cardinal headings and tilted attitudes.
  - Reject invalid frames, timestamps, quaternions, and non-finite values.
  - Confirm parameter and odometry traffic coexist on UDP 14551.
  - Confirm only armed-flight samples are written.
  - Verify Parquet chunking, metadata, schema version 3, and interrupted-session recovery.
  - Saturate the queue and verify odometry drops without losing flight-control operation.
  - Run a live takeoff/landing and graph body vx/vy and NED north/east velocity.

  ## Assumptions

  - The bridge publishes MAVLink 2 ODOMETRY at approximately 50 Hz.
  - The quaternion rotates body FRD into local NED.
  - Odometry is used exclusively for offline diagnostics.
  - Port and source identity are not added to vehicle configuration.