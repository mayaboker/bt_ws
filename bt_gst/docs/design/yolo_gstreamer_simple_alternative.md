# Simple YOLO GStreamer alternative

> **Superseded metadata decision:** the implementation now targets GStreamer
> 1.18 and emits the common `GstVideoRegionOfInterestMeta` contract documented
> in [common_roi_metadata_gstreamer_1_18.md](common_roi_metadata_gstreamer_1_18.md).
> The analytics and `objectdetectionoverlay` sections below describe the older
> GStreamer 1.24 design and are retained only as design history.

## Recommendation

Keep the installed GStreamer 1.24.2 stack and implement one project-owned
element, `cpuyolodetect`, that produces standard GStreamer object-detection
metadata directly:

```text
camera / decoded video
    |
    v
videoconvert ! video/x-raw,format=RGB
    |
    v
cpuyolodetect
    | GstAnalyticsODMtd on the original video buffer
    v
objectdetectionoverlay
    |
    v
video sink
```

This is the recommended first implementation when a small, working pipeline is
more important than keeping preprocessing, inference, and decoding as separate
plugins. It keeps `objectdetectionoverlay` as the visualization component and
uses the public GStreamer 1.24 analytics interface.

## Why this is simpler

The split-element design in `yolo_gstreamer_pipeline.md` is architecturally
clean, but its current upstream components do not match the installed runtime.
It requires:

- a second GStreamer build and activation environment;
- a separate Rust `gst-plugins-rs` build;
- an intermediate tensor metadata contract;
- a modelinfo sidecar that must match ONNX tensor names and shapes;
- version pinning across GStreamer, its Rust bindings, and the decoder plugin.

The alternative removes the intermediate tensor API. Preprocessing, ONNX
Runtime, YOLO decoding, and NMS are private implementation stages inside one
element. The only external result contract is `GstAnalyticsODMtd`, which is
already available locally and already understood by `objectdetectionoverlay`.

The tradeoff is that the inference and YOLO decoder cannot initially be reused
as independent pipeline elements. They should still be separate C++ classes so
they can be extracted later without rewriting the algorithms.

## Element contract

`cpuyolodetect` is a synchronous, in-place `GstBaseTransform` element.

### Pads

Both pads use the same caps:

```text
video/x-raw,format=RGB
```

The element never replaces or resizes the outgoing video buffer. It attaches
metadata to the original-resolution frame and passes that frame downstream.

### Properties

| Property | Type | Default | Mutability | Meaning |
|---|---:|---:|---|---|
| `model-file` | string | none | READY | Ultralytics detection ONNX model |
| `labels-file` | string | none | READY | Optional class names, one per line; decimal class IDs when omitted |
| `intra-op-threads` | integer | `0` | READY | ONNX Runtime worker threads; zero uses its default |
| `confidence-threshold` | float | `0.4` | PLAYING | Minimum best-class confidence |
| `iou-threshold` | float | `0.7` | PLAYING | Per-class NMS threshold |
| `max-detections` | unsigned | `100` | PLAYING | Maximum retained detections per frame |
| `enabled` | boolean | `true` | PLAYING | Run inference or pass frames without detection metadata |

Changing the model or labels while PLAYING is rejected. Thresholds and
`enabled` are protected by the element lock and may be changed while running.

### Model contract

Version 1 supports exactly:

- one float32 NCHW input with shape `[1,3,H,W]` and fixed `H` and `W`;
- RGB normalization `value / 255.0`;
- one float32 raw output with shape `[1,4+classes,N]`;
- Ultralytics boxes encoded as center-x, center-y, width, and height;
- a one-to-many output without embedded NMS.

The implementation reads `H`, `W`, the class count, tensor names, and candidate
count from the ONNX session. It validates all types and dimensions when moving
from READY to PAUSED. A modelinfo file is not required.

The labels file is optional. When omitted, object types are decimal class IDs
(`"0"`, `"1"`, and so on). When supplied, it must contain exactly `classes`
non-empty lines; startup fails on a mismatch so class IDs cannot silently
acquire incorrect names.

## Internal implementation

Keep the element source small by splitting implementation-only classes inside
`bt_gst/src/cpuyolodetect/`:

```text
GstCpuYoloDetect       GStreamer lifecycle, properties, caps, metadata
YoloPreprocessor       RGB frame to normalized letterboxed NCHW tensor
YoloOnnxSession        ONNX Runtime session and validated input/output
YoloDecoder            thresholding, per-class NMS, coordinate mapping
```

These are not separate GStreamer plugins and expose no tensor metadata.

Follow normal `GstBaseTransform` lifecycle boundaries:

- `start()` validates the model path, optionally loads labels, creates the ONNX Runtime
  environment/session, reads tensor names and shapes, and allocates reusable
  input/output working storage;
- `set_caps()` stores `GstVideoInfo` and rejects anything except packed RGB;
- `transform_ip()` maps one frame, runs the three internal stages, adds
  analytics metadata, logs stage timings, and returns the original buffer;
- `stop()` releases the session and working storage and leaves the object ready
  to start again with a different READY-state configuration;
- `finalize()` safely releases any remaining C++ objects and GLib strings.

Element startup must require exactly one model input and one model output. Read
their names through ONNX Runtime rather than assuming `images` or `output0`.

### Preprocessing

Map the input with `gst_video_frame_map()` and honor the negotiated row stride.
Do not assume tightly packed rows. Implement bilinear RGB resize directly over
the mapped bytes, preserving aspect ratio and filling unused tensor pixels with
the Ultralytics letterbox value `114`.

For source dimensions `(source_width, source_height)` and model dimensions
`(model_width, model_height)`, retain the scale and padding used for that frame:

```text
scale = min(model_width / source_width, model_height / source_height)
resized_width  = round(source_width  * scale)
resized_height = round(source_height * scale)
pad_x = (model_width  - resized_width)  / 2
pad_y = (model_height - resized_height) / 2
```

Write the tensor in planar channel order and normalize each byte to `[0,1]`.
This implementation uses GStreamer video mapping and standard C++ only; OpenCV
is not a dependency.

### Inference and decoding

Create one ONNX Runtime environment and session when the element starts. Use
the bundled CPU runtime at
`bt_gst/third_party/onnxruntime-linux-x64-1.29.0`, enable extended graph
optimization, apply `intra-op-threads`, and reuse input/output allocations
across frames. Create reusable `Ort::MemoryInfo`, tensor-shape arrays, input and
output name arrays, the normalized input vector, and candidate/result vectors
outside the per-frame hot path. Grow capacity when needed but do not recreate
the session or deliberately allocate full-frame storage on every buffer.

For each candidate:

1. Select the highest class confidence.
2. Reject values below `confidence-threshold` and all non-finite coordinates or
   scores.
3. Convert center-size boxes to model-space corners.
4. Run NMS independently per class.
5. Keep the globally highest-confidence results up to `max-detections`.
6. Remove letterbox padding, divide by `scale`, and clamp the box to the source
   frame.
7. Reject boxes that become empty after clamping.

### Analytics metadata

Require the in-place transform buffer to be writable before attaching metadata;
fail the frame if that invariant is unexpectedly false. Retrieve an existing
`GstAnalyticsRelationMeta` with `gst_buffer_get_analytics_relation_meta()` and
reuse it when present; otherwise add one with
`gst_buffer_add_analytics_relation_meta()`. Add one `GstAnalyticsODMtd` per
retained detection using:

```cpp
gst_analytics_relation_meta_add_od_mtd(
    relation_meta,
    g_quark_from_string(label),
    x, y, width, height,
    confidence,
    &od_mtd);
```

Coordinates are integer pixels in the original outgoing frame, not the model
tensor. This is the complete compatibility boundary with
`objectdetectionoverlay`; no `GstVideoRegionOfInterestMeta` or custom result
structure is needed.

If no objects are detected, retain/create an empty relation meta and pass the
frame. If `enabled=false`, do not run inference and do not add or modify
analytics metadata. Never remove metadata created by an upstream element.
Model loading, tensor validation, mapping, inference, or metadata allocation
failures return a GStreamer error rather than silently producing stale results.

Log the number of detections plus preprocessing, inference, and postprocessing
durations independently at `GST_LEVEL_LOG`. Keep logs off the default hot path
unless the corresponding debug category is enabled.

## Build plan

Add a CMake target beside the existing native plugins with these dependencies:

```text
gstreamer-1.0
gstreamer-base-1.0
gstreamer-video-1.0
gstreamer-analytics-1.0
ONNX Runtime 1.29.0 from bt_gst/third_party
```

Do not find or link OpenCV. Reuse the ONNX Runtime discovery and build-RPATH
pattern from `src/cpunanotracker/CMakeLists.txt`, and add
`gstreamer-analytics-1.0` to the pkg-config modules. Produce
`libgstcpuyolodetect.so` and a small `cpuyolodetect-check` test executable.

The normal development environment is sufficient:

```bash
export GST_PLUGIN_PATH="$PWD/bt_gst/build-cpuyolodetect${GST_PLUGIN_PATH:+:$GST_PLUGIN_PATH}"
export LD_LIBRARY_PATH="$PWD/bt_gst/third_party/onnxruntime-linux-x64-1.29.0/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
gst-inspect-1.0 cpuyolodetect
gst-inspect-1.0 objectdetectionoverlay
```

No alternate GStreamer installation, Rust compiler, or modelinfo generator is
required.

## Quick pipeline checks

Define the plugin, runtime, model, and test-image paths from the
workspace root:

```bash
export GST_PLUGIN_PATH="$PWD/bt_gst/build-cpuyolodetect${GST_PLUGIN_PATH:+:$GST_PLUGIN_PATH}"
export LD_LIBRARY_PATH="$PWD/bt_gst/third_party/onnxruntime-linux-x64-1.29.0/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export YOLO_MODEL=/absolute/path/to/model.onnx
export YOLO_IMAGE=/absolute/path/to/test-image.jpg
```

First run a finite, headless smoke check. This verifies decoding, RGB caps,
model loading, inference, `GstAnalyticsODMtd` creation, and consumption by
`objectdetectionoverlay`. It processes five copies of the image and exits:

```bash
GST_DEBUG="cpuyolodetect:6,objectdetectionoverlay:5" \
gst-launch-1.0 -e \
  filesrc location="$YOLO_IMAGE" ! \
  decodebin ! \
  imagefreeze num-buffers=5 ! \
  videoconvert ! \
  video/x-raw,format=RGB ! \
  cpuyolodetect \
    model-file="$YOLO_MODEL" \
    confidence-threshold=0.4 \
    iou-threshold=0.7 \
    max-detections=100 ! \
  objectdetectionoverlay draw-labels=true ! \
  fakesink sync=false
```

The command passes when it reaches EOS without an ERROR and the detector log
reports the expected number of detections. A zero-detection result is not a
sufficient positive test; use an image containing an object represented in the
model's classes. Without `labels-file`, logs and overlays use decimal class IDs.

Then run the same path with visible output to check label text and bounding-box
alignment on the original-resolution frame:

```bash
GST_DEBUG="cpuyolodetect:6" \
gst-launch-1.0 -e \
  filesrc location="$YOLO_IMAGE" ! \
  decodebin ! \
  imagefreeze num-buffers=150 ! \
  videoconvert ! \
  video/x-raw,format=RGB ! \
  cpuyolodetect \
    model-file="$YOLO_MODEL" ! \
  objectdetectionoverlay draw-labels=true ! \
  videoconvert ! \
  autovideosink sync=false
```

## Reference pipeline

```bash
gst-launch-1.0 -e \
  filesrc location=/absolute/path/to/test-image.jpg ! \
  decodebin ! \
  imagefreeze num-buffers=150 ! \
  videoconvert ! \
  video/x-raw,format=RGB ! \
  cpuyolodetect \
    model-file=/absolute/path/to/model.onnx \
    confidence-threshold=0.4 \
    iou-threshold=0.7 \
    max-detections=100 ! \
  objectdetectionoverlay draw-labels=true ! \
  videoconvert ! \
  autovideosink sync=false
```

For a live source, place a one-buffer leaky queue immediately before the
detector to prefer recent frames:

```text
... ! queue max-size-buffers=1 leaky=downstream ! cpuyolodetect ! ...
```

## Tests and acceptance criteria

### Unit tests

- Validate accepted and rejected ONNX input/output types and shapes.
- Verify model tensor names are discovered rather than assumed, session
  construction follows `start()`/`stop()`, and `intra-op-threads` is applied.
- Verify RGB-to-NCHW normalization, stride handling, letterbox fill, scale, and
  padding for landscape, portrait, and square frames.
- Verify confidence filtering, per-class NMS, global result ordering, maximum
  detection count, non-finite rejection, inverse letterbox mapping, and frame
  clamping.
- Verify omitted labels produce decimal class IDs, while supplied labels
  enforce the exact class count and reject empty lines.
- Verify reusable work buffers do not grow during repeated inference at an
  unchanged resolution and model shape.

### GStreamer tests

- `gst-inspect-1.0` loads both `cpuyolodetect` and
  `objectdetectionoverlay` on the existing GStreamer 1.24.2 runtime.
- RGB caps negotiate while unsupported formats fail negotiation cleanly.
- A known image produces `GstAnalyticsODMtd` with the expected label,
  confidence range, and source-frame bounding box.
- Pre-existing `GstAnalyticsRelationMeta` is reused and its upstream entries
  remain intact.
- `objectdetectionoverlay` draws that box at the correct location on
  non-square input without requiring a 640x640 output frame.
- A zero-detection frame passes unchanged.
- `enabled=false` bypasses inference and metadata creation.
- Missing model, malformed labels, inference failure, and non-writable buffer
  paths produce deterministic GStreamer errors and never reuse detections from
  an earlier frame.

Acceptance requires correct, aligned overlays on at least one landscape and one
portrait image. Record CPU model, ONNX model hash, startup time, steady-state
FPS, and average inference time, but do not impose a minimum FPS in version 1.

## Reference implementation guidance

The
[`robobe/gst_cpp_plugin_tutorial` YOLO detector](https://github.com/robobe/gst_cpp_plugin_tutorial/blob/master/src/yolodetect/yolodetect.cpp)
is a useful structural reference for the in-place transform, ONNX session
validation, letterbox bookkeeping, raw YOLOv8 decoding, per-class NMS,
source-coordinate restoration, analytics metadata attachment, and stage timing.

Do not copy its OpenCV dependency, READY-only threshold properties, per-frame
full-size allocations, or lack of explicit non-finite checks and detection
limits. Numeric class IDs are an intentional fallback only when `labels-file`
is omitted; supplied human-readable labels remain supported. The requirements
in this document take precedence where the tutorial differs.

## Future split

If another inference backend or tensor decoder is later needed, extract the
internal stages into separate elements while preserving the downstream
contract:

```text
preprocess ! inference ! yolo-postprocess
    | GstAnalyticsODMtd
    v
tracker ! objectdetectionoverlay / telemetry
```

The first extraction should only happen after a second consumer demonstrates a
need for the intermediate tensor result. Until then, the single detector keeps
installation, versioning, debugging, and runtime behavior substantially
simpler.
