# Optical Flow Tracker Milestones

## M1: Plugin Skeleton and Interface Contract
- Add `plugins/python/gstbt_optical_flow.py`.
- Add `bt_gst/optical_flow_tracker.py` for shared constants and defaults.
- Register `bt_optical_flow` as an in-place `GstBase.BaseTransform`.
- Expose the documented properties from `optical_tracker_requirement.md`.
- Emit `bt-tracker-meta` on every output buffer.
- Use `bt_optical_flow` in the app pipeline.
- Do not implement real optical flow yet.

## M2: Add user track request
- Send a `bt-track-request` point event from video-widget mouse clicks.
- Force the plugin input/output to `video/x-raw,format=RGBA`.
- Store a click-centered ROI in `bt_optical_flow` using `request-search-size`.
- Clamp the ROI to frame bounds.
- Draw the ROI into the outgoing RGBA video buffer.
- Keep metadata as `STATUS_BREAK` while no real tracking exists.

## M3: Stop Request and ROI Resize Controls
- Implement user stop request with keyboard `Esc`.
- Implement square ROI resize with regular/keypad `+` and `-`.
- Preserve ROI center while resizing.
- Clamp resized ROI to frame bounds.
- Keep real feature detection deferred to a later milestone.

## M4: User ROI Adjustment Controls
- Implement ROI movement with regular/keypad arrow keys.
- Send `adjust-roi` requests with `delta-x` and `delta-y`.
- Preserve ROI size while moving.
- Clamp adjusted ROI to frame bounds.
- Keep real feature detection deferred to a later milestone.

## M5: Feature Detection and Lucas-Kanade Tracking
- Detect initial features inside the selected ROI with `cv2.goodFeaturesToTrack`.
- Track features frame to frame with Lucas-Kanade optical flow.
- Move the active ROI by the measured mean feature motion.
- Compute `dx`, `dy`, `score`, and `STATUS_TRACK` metadata for valid tracking.
- Emit `STATUS_BREAK` when there are not enough features, OpenCV is unavailable, or LK tracking fails.
- Keep click, stop, resize, and adjust controls working with the real tracker state.
## M6: Debug mode
- Implement `debug=true` behavior on `bt_optical_flow`.
- Post one `bt-tracker-debug` element bus message per processed frame.
- Include frame number, status, active feature count, and feature locations JSON.
- Draw active tracked feature points as green marks only when debug is enabled.
- Keep debug disabled by default and controlled only by the existing plugin property.
<!-- ## Future: Upstream Requests and Debug
- Read upstream `bt-track-request` metadata.
- Post `bt-tracker-debug` bus messages when `debug=true`.
- Include frame number, status, active feature count, and feature locations. -->
