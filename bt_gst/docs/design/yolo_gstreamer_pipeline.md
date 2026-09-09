# YOLO GStreamer analytics pipeline

> **Historical design:** this document requires GStreamer 1.24 or newer. The
> implemented GStreamer 1.18-compatible metadata contract is documented in
> [common_roi_metadata_gstreamer_1_18.md](common_roi_metadata_gstreamer_1_18.md).

## Status and goal

This document defines the first standalone YOLO detection pipeline for
`bt_gst`. The implementation deliberately reuses GStreamer elements instead of
adding another project-owned inference plugin:

```text
camera / image
    |
    v
videoconvertscale + caps       preprocessing and letterboxing
    |
    v
onnxinference                  ONNX Runtime inference
    | GstTensorMeta
    v
yolov8tensordec2               YOLO decode, confidence filtering, and NMS
    | GstAnalyticsODMtd
    v
objectdetectionoverlay         boxes and labels
    |
    v
video sink
```

Version 1 is CPU-only and synchronous. It ends with object-detection metadata;
tracking and `GstAnalyticsTrackingMtd` are a version 2 extension. It does not
modify `bt_gst.pipeline_builder`, application YAML, or the existing tracker
plugins.

The host currently has GStreamer 1.24.2. That version cannot be mixed directly
with the current `yolov8tensordec2`: the decoder uses the newer analytics tensor
contract. To avoid disturbing existing pipelines, the required GStreamer stack
is installed into a project-local prefix and is active only in shells where its
environment has been exported.

## Supported model contract

The initial contract is intentionally narrow:

- one float32 RGB input in NCHW order, exactly `[1,3,640,640]`;
- input pixels normalized from `[0,255]` to `[0,1]`;
- one raw Ultralytics detection output shaped `[1,4+classes,N]`;
- a one-to-many, non-NMS detection head, with NMS performed by
  `yolov8tensordec2`;
- one label per line, in model class-index order.

Dynamic input sizes, end-to-end NMS exports, segmentation, pose, and
classification models are out of scope. The ONNX model and its labels are
user-supplied and are not committed to this repository.

The pipeline requires an INI-style model information file alongside the ONNX
file. For a model named `best.onnx`, save this as `best.onnx.modelinfo`:

```ini
[modelinfo]
version=1.0
group-id=yolo-v8-out

[images]
id=yolo-v8-in
type=float32
dims=1,3,640,640
dir=input
ranges=0.0,1.0;0.0,1.0;0.0,1.0

[output0]
id=yolo-v8-out
type=float32
dims=1,-1,-1
dir=output
dims-order=col-major
```

`images` and `output0` should match the tensor names in the exported model. If
the exporter used different names, rename the corresponding sections. The
output ID must remain `yolo-v8-out`, because that is the ID consumed by
`yolov8tensordec2`.

## Local dependency stack

The commands below assume the workspace is
`/home/user/projects/bt_ws`. They pin GStreamer to 1.28.7 and the Rust analytics
plugin to a reviewed commit that contains `yolov8tensordec2`.

```bash
export BT_WS=/home/user/projects/bt_ws
export YOLO_GST_ROOT="$BT_WS/build/yolo-gst"
export YOLO_GST_PREFIX="$YOLO_GST_ROOT/prefix"
export YOLO_GST_SRC="$YOLO_GST_ROOT/src/gstreamer"
export YOLO_GST_BUILD="$YOLO_GST_ROOT/build-gstreamer"
export YOLO_GST_RS_SRC="$YOLO_GST_ROOT/src/gst-plugins-rs"
export YOLO_ORT_ROOT="$BT_WS/bt_gst/third_party/onnxruntime-linux-x64-1.29.0"
export YOLO_PKGCONFIG="$YOLO_GST_ROOT/pkgconfig"

mkdir -p "$YOLO_GST_ROOT/src" "$YOLO_PKGCONFIG"
sed \
  -e "s|^prefix=.*|prefix=$YOLO_ORT_ROOT|" \
  -e 's|^libdir=.*|libdir=${prefix}/lib|' \
  -e 's|^includedir=.*|includedir=${prefix}/include|' \
  "$YOLO_ORT_ROOT/lib/pkgconfig/libonnxruntime.pc" \
  > "$YOLO_PKGCONFIG/libonnxruntime.pc"

git clone --branch 1.28.7 --depth 1 \
  https://github.com/GStreamer/gstreamer.git "$YOLO_GST_SRC"

export PKG_CONFIG_PATH="$YOLO_PKGCONFIG${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
export LD_LIBRARY_PATH="$YOLO_ORT_ROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

meson setup "$YOLO_GST_BUILD" "$YOLO_GST_SRC" \
  --prefix="$YOLO_GST_PREFIX" \
  --libdir=lib \
  --buildtype=release \
  -Dtests=disabled \
  -Dexamples=disabled \
  -Ddoc=disabled \
  -Dgst-plugins-bad:onnx=enabled
meson compile -C "$YOLO_GST_BUILD"
meson install -C "$YOLO_GST_BUILD"

git clone https://github.com/GStreamer/gst-plugins-rs.git "$YOLO_GST_RS_SRC"
git -C "$YOLO_GST_RS_SRC" checkout \
  2e071d2b60470aae54c72a374d7c91427e19030d
```

Activate the new C stack before compiling the Rust analytics plugin:

```bash
export PATH="$YOLO_GST_PREFIX/bin:$PATH"
export LD_LIBRARY_PATH="$YOLO_GST_PREFIX/lib:$YOLO_ORT_ROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PKG_CONFIG_PATH="$YOLO_GST_PREFIX/lib/pkgconfig:$YOLO_PKGCONFIG${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
export GST_PLUGIN_PATH="$YOLO_GST_PREFIX/lib/gstreamer-1.0${GST_PLUGIN_PATH:+:$GST_PLUGIN_PATH}"

cargo build \
  --manifest-path "$YOLO_GST_RS_SRC/Cargo.toml" \
  --release \
  --package gst-plugin-analytics \
  --features v1_28

export GST_PLUGIN_PATH="$YOLO_GST_RS_SRC/target/release:$GST_PLUGIN_PATH"
```

These exports must also be applied in every shell that runs the YOLO pipeline.
They intentionally do not modify system-wide loader or GStreamer settings.

## Preflight checks

Verify that the shell is using only the intended local stack:

```bash
gst-launch-1.0 --version
gst-inspect-1.0 onnxinference
gst-inspect-1.0 yolov8tensordec2
gst-inspect-1.0 objectdetectionoverlay
ldd "$YOLO_GST_PREFIX/lib/gstreamer-1.0/libgstonnx.so" | grep onnxruntime
```

Expected results:

- `gst-launch-1.0` reports 1.28.7;
- all three elements are found;
- `libgstonnx.so` resolves `libonnxruntime.so` from
  `bt_gst/third_party/onnxruntime-linux-x64-1.29.0/lib`.

If an element is missing, clear only the local registry and inspect again:

```bash
export GST_REGISTRY="$YOLO_GST_ROOT/registry.bin"
rm -f "$GST_REGISTRY"
gst-inspect-1.0 yolov8tensordec2
```

## Reference pipeline

Set paths to a compatible model, its labels, and a still image containing a
known object:

```bash
export YOLO_MODEL=/absolute/path/to/best.onnx
export YOLO_LABELS=/absolute/path/to/labels.txt
export YOLO_IMAGE=/absolute/path/to/test-image.jpg
```

Run the standalone visual pipeline:

```bash
GST_DEBUG="onnxruntime:4,yolotensordec:6" \
gst-launch-1.0 -e \
  filesrc location="$YOLO_IMAGE" ! \
  decodebin ! \
  imagefreeze num-buffers=150 ! \
  videoconvertscale add-borders=true ! \
  video/x-raw,format=RGB,width=640,height=640,pixel-aspect-ratio=1/1 ! \
  queue max-size-buffers=1 leaky=downstream ! \
  onnxinference \
    execution-provider=cpu \
    optimization-level=enable-all \
    model-file="$YOLO_MODEL" ! \
  yolov8tensordec2 \
    label-file="$YOLO_LABELS" \
    class-confidence-threshold=0.4 \
    iou-threshold=0.7 \
    max-detections=100 ! \
  objectdetectionoverlay draw-labels=true ! \
  videoconvertscale ! \
  autovideosink sync=false
```

`videoconvertscale add-borders=true` performs aspect-preserving letterboxing
without OpenCV. Inference, decoding, and overlay operate on the same 640x640
buffer, so the object coordinates do not require remapping. Version 1 displays
that letterboxed frame; a separate native-resolution display branch is out of
scope.

The decoder debug output is the non-visual inspection interface for version 1.
No JSON or application telemetry schema is introduced.

## Correctness and failure tests

Run these tests before using another model or camera source:

1. Use a known image and confirm the debug log contains decoded detections and
   the overlay boxes align with the objects, including when black letterbox
   borders are present.
2. Use an image with no relevant objects and confirm the pipeline continues
   with zero detections rather than failing.
3. Temporarily omit the `.onnx.modelinfo` file and confirm `onnxinference`
   rejects the model with a clear model-information error.
4. Change the modelinfo input dimensions or output type and confirm startup
   fails instead of producing incorrect metadata.
5. Use a labels file with the correct number and order of classes. A mismatch is
   a model-package error and must be fixed rather than hidden in the pipeline.

## Benchmark procedure

Performance is reported, not gated, for version 1. Replace the final display
sink in the reference pipeline with:

```text
objectdetectionoverlay !
fpsdisplaysink video-sink=fakesink text-overlay=false sync=false
```

Run enough frames to exclude model/session startup from the steady-state
sample. Record:

- ONNX model name and file hash;
- CPU model and logical-core count;
- GStreamer and ONNX Runtime versions;
- input resolution and frame count;
- startup time, steady-state FPS, and observed per-frame latency.

No minimum FPS is required yet. If live input later outruns synchronous CPU
inference, place `videorate` before preprocessing or retain the one-buffer leaky
queue so stale frames are discarded.

## Tracker extension boundary

A future tracker belongs between the decoder and output stages:

```text
yolov8tensordec2
    | GstAnalyticsODMtd
    v
tracker
    | GstAnalyticsTrackingMtd
    v
objectdetectionoverlay / telemetry
```

That tracker must consume `GstAnalyticsODMtd`, preserve the detection relation
metadata, and attach `GstAnalyticsTrackingMtd` to the same `GstBuffer`. Tracker
selection, lifecycle, IDs, and telemetry integration are explicitly deferred
and must not be inferred as part of this standalone v1.
