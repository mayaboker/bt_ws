# CPU YOLO detector

`cpuyolodetect` runs a raw Ultralytics detection ONNX model on CPU and adds
`GstVideoRegionOfInterestMeta` to the original RGB video buffer. It uses the
same `bt-object-detection` parameter structure as `cpunanotrack`, and remains
compatible with GStreamer 1.18. Preprocessing, letterbox mapping, decoding,
and per-class NMS use standard C++ and do not require OpenCV.

See the [implementation design](../../docs/design/yolo_gstreamer_simple_alternative.md)
for the model contract and complete pipeline checks.

## Build

The bundled ONNX Runtime SDK must contain both its headers and
`lib/libonnxruntime.so`. From the `bt_gst` directory:

```bash
cmake -S src/cpuyolodetect -B build-cpuyolodetect -G Ninja \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build-cpuyolodetect
ctest --test-dir build-cpuyolodetect --output-on-failure
export GST_PLUGIN_PATH="$PWD/build-cpuyolodetect${GST_PLUGIN_PATH:+:$GST_PLUGIN_PATH}"
gst-inspect-1.0 cpuyolodetect
```

## Pipeline

```bash
gst-launch-1.0 -e \
  filesrc location="$YOLO_IMAGE" ! decodebin ! imagefreeze num-buffers=150 ! \
  videoconvert ! video/x-raw,format=RGB ! \
  cpuyolodetect model-file="$YOLO_MODEL" ! \
  metaprint ! fakesink sync=false
```

Supported models have one fixed FLOAT32 NCHW input `[1,3,H,W]` and one raw
FLOAT32 output `[1,4+classes,candidates]`, exported without embedded NMS.
Without `labels-file`, object types are decimal class IDs such as `0` and `1`.
Set `labels-file="$YOLO_LABELS"` to use names; a supplied file must contain
exactly one non-empty line per model class.

Each result is an ROI whose type is the label (or decimal class ID) and whose
`bt-object-detection` structure contains `confidence`, `class-id`, and
`initialized=false`. GStreamer 1.18 has no standard ROI drawing element; use
the application's existing Cairo overlay when visualization is required.
