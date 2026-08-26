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
- Find separate external red contours and attach `GstRedDetectionMeta` custom
  metadata containing candidates, selector state, and the selected target.
- In selecting state, report only a qualifying contour whose center is inside
  the selector.
- In locked state, associate the previously selected contour without switching
  automatically to another target.
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
- `selector-state`: unsigned integer, `0` disabled, `1` selecting, `2` locked.
- `selector-center-x`, `selector-center-y`: normalized doubles, default `0.5`.
- `selector-width`, `selector-height`: pixel dimensions, default `80`.
- `minimum-area`: candidate contour area, default `150` pixels.
- `minimum-coverage`: candidate red fill ratio, default `0.30`.

## Acceptance Criteria

- The project builds with CMake.
- `gst-inspect-1.0 controlledreddetect` loads the plugin from the local build
  directory.
- The element exposes all HSV and enable/disable properties.
- The element exposes selector and candidate qualification properties.
- A simple RGB `videotestsrc` pipeline can negotiate through the element.
