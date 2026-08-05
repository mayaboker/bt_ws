# gst_detector Requirements

## Goal

Provide a standalone GStreamer C++ plugin project containing the
`controlledreddetect` element from the tutorial project.

## Element Behavior

- Accept `video/x-raw,format=RGB` on the sink pad.
- Output `video/x-raw,format=RGB` on the source pad.
- Run in-place as a `GstBaseTransform`.
- Use OpenCV to convert RGB frames to HSV.
- Threshold the HSV frame using configurable low/high HSV values.
- Find red pixels and attach `GstRedDetectionMeta` custom metadata to each
  buffer.
- Attach metadata with `found=false` when detection is disabled or no red pixels
  are found.

## Properties

- `detection-enabled`: boolean, default `true`.
- `low-h`: unsigned integer, range `0..179`, default `0`.
- `low-s`: unsigned integer, range `0..255`, default `100`.
- `low-v`: unsigned integer, range `0..255`, default `100`.
- `high-h`: unsigned integer, range `0..179`, default `10`.
- `high-s`: unsigned integer, range `0..255`, default `255`.
- `high-v`: unsigned integer, range `0..255`, default `255`.

## Acceptance Criteria

- The project builds with CMake.
- `gst-inspect-1.0 controlledreddetect` loads the plugin from the local build
  directory.
- The element exposes all HSV and enable/disable properties.
- A simple RGB `videotestsrc` pipeline can negotiate through the element.
