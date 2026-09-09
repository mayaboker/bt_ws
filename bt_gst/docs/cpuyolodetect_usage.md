# `cpuyolodetect` usage

This guide covers loading, inspecting, and running the CPU YOLO detector with
GStreamer's standard `objectdetectionoverlay` element.

Run all commands from:

```bash
cd /home/user/projects/bt_ws/bt_gst
```

## 1. Build the plugins

```bash
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build
ctest --test-dir build --output-on-failure
```

The detector is built as:

```text
build/plugins/libgstcpuyolodetect.so
```

## 2. Export the plugin path

```bash
export GST_PLUGIN_PATH="$PWD/build/plugins${GST_PLUGIN_PATH:+:$GST_PLUGIN_PATH}"
```

The plugin has a build RPATH for the bundled ONNX Runtime. If the loader cannot
find it, also export:

```bash
export LD_LIBRARY_PATH="$PWD/third_party/onnxruntime-linux-x64-1.29.0/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
```

These exports apply only to the current terminal.

## 3. Inspect the elements

```bash
gst-inspect-1.0 cpuyolodetect
gst-inspect-1.0 objectdetectionoverlay
```

The detector inspection should show:

- sink and source caps `video/x-raw,format=RGB`;
- required `model-file`;
- optional `labels-file`;
- `enabled=true` by default;
- confidence threshold `0.4`;
- IoU threshold `0.7`;
- maximum detections `100`.

If inspection cannot find the plugin, verify the file and its dependencies:

```bash
ls -l build/plugins/libgstcpuyolodetect.so
ldd build/plugins/libgstcpuyolodetect.so
GST_DEBUG=GST_PLUGIN_LOADING:6 gst-inspect-1.0 cpuyolodetect
```

## 4. Select a compatible model

Set the model and input paths:

```bash
export YOLO_MODEL=/absolute/path/to/model.onnx
export YOLO_IMAGE=/absolute/path/to/test-image.jpg
```

The model must have:

- one fixed FLOAT32 NCHW input `[1,3,H,W]`;
- one raw FLOAT32 output `[1,4+classes,candidates]`;
- center-x, center-y, width, height box fields;
- no embedded NMS.

No modelinfo sidecar is needed.

`labels-file` is optional. Without it, the overlay displays decimal class IDs
such as `0` and `1`.

To use names, create a UTF-8 file containing exactly one non-empty label per
model class:

```bash
export YOLO_LABELS=/absolute/path/to/labels.txt
```

Example for a two-class model:

```text
person
vehicle
```

## 5. Headless smoke-test pipeline

This processes five copies of one image, sends detections through
`objectdetectionoverlay`, and exits automatically:

```bash
GST_DEBUG=cpuyolodetect:6 gst-launch-1.0 -e \
  filesrc location="$YOLO_IMAGE" ! \
  decodebin ! \
  imagefreeze num-buffers=5 ! \
  videoconvert ! video/x-raw,format=RGB ! \
  cpuyolodetect \
    model-file="$YOLO_MODEL" \
    confidence-threshold=0.4 \
    iou-threshold=0.7 \
    max-detections=100 ! \
  objectdetectionoverlay draw-labels=true ! \
  fakesink sync=false
```

A successful run reaches EOS without `ERROR`. At debug level 6, the detector
prints the detection count and preprocessing, inference, and postprocessing
times.

To use class names, add this property to `cpuyolodetect` before the `!`:

```text
labels-file="$YOLO_LABELS"
```

## 6. Display detections on an image

```bash
GST_DEBUG=cpuyolodetect:6 gst-launch-1.0 -e \
  filesrc location="$YOLO_IMAGE" ! \
  decodebin ! \
  imagefreeze num-buffers=150 ! \
  videoconvert ! video/x-raw,format=RGB ! \
  cpuyolodetect \
    model-file="$YOLO_MODEL" ! \
  objectdetectionoverlay draw-labels=true ! \
  videoconvert ! autovideosink
```

The element performs model-size letterboxing internally but passes the original
frame downstream. Bounding boxes are mapped back to the original image before
`objectdetectionoverlay` draws them.

## 7. Run on a video file

```bash
export YOLO_VIDEO=/absolute/path/to/video.mp4

GST_DEBUG=cpuyolodetect:6 gst-launch-1.0 -e \
  filesrc location="$YOLO_VIDEO" ! \
  decodebin ! \
  videoconvert ! video/x-raw,format=RGB ! \
  cpuyolodetect model-file="$YOLO_MODEL" ! \
  objectdetectionoverlay draw-labels=true ! \
  videoconvert ! autovideosink sync=false
```

Do not put a leaky queue before the detector for a non-live file. File decoding
can run far ahead of the playback clock; dropping queued buffers can jump to a
far-future timestamp and make the displayed image appear frozen while the sink
waits for that timestamp. Use a normal queue or no queue for file playback.

## 8. Run on a V4L2 camera

```bash
gst-launch-1.0 -e \
  v4l2src device=/dev/video0 ! \
  videoconvert ! video/x-raw,format=RGB ! \
  queue max-size-buffers=1 max-size-bytes=0 max-size-time=0 leaky=downstream ! \
  cpuyolodetect model-file="$YOLO_MODEL" ! \
  objectdetectionoverlay draw-labels=true ! \
  videoconvert ! autovideosink sync=false
```

## 9. Useful properties

```text
cpuyolodetect
  model-file=/path/model.onnx
  labels-file=/path/labels.txt
  enabled=true
  confidence-threshold=0.4
  iou-threshold=0.7
  max-detections=100
  intra-op-threads=0
```

`confidence-threshold`, `iou-threshold`, `max-detections`, and `enabled` may be
changed while PLAYING from an application. `model-file`, `labels-file`, and
`intra-op-threads` may only be changed in NULL or READY.

Set `enabled=false` to pass RGB frames through without inference or new
detection metadata:

```bash
gst-launch-1.0 videotestsrc num-buffers=5 ! \
  videoconvert ! video/x-raw,format=RGB ! \
  cpuyolodetect model-file="$YOLO_MODEL" enabled=false ! \
  fakesink
```

The model is still loaded when the pipeline starts.

## 10. Common failures

`No such element or plugin 'cpuyolodetect'` means `GST_PLUGIN_PATH` does not
include `build/plugins`, the plugin failed to load, or its shared dependencies
are missing. Use the inspection commands in section 3.

`model-file is required` means the property was omitted or empty.

`expected fixed FLOAT32 NCHW input` means the model input is dynamic, not
FLOAT32, not four-dimensional, or not `[1,3,H,W]`.

`expected raw FLOAT32 YOLO output` usually means the model was exported with
embedded NMS or uses a different task/output layout.

`labels count ... does not match model class count` means a supplied labels
file has the wrong number of lines. Remove `labels-file` to use numeric class
IDs, or correct the file.

If the pipeline runs but detects nothing, lower `confidence-threshold`, confirm
the model was exported without NMS, and test with an image known to contain one
of the trained classes.

## 11. Final detection-demo pipeline

The source video is 12 FPS. This pipeline uses four ONNX Runtime inference
threads, draws detections, and displays measured FPS on the video:

```bash
cd /home/user/projects/bt_ws/bt_gst

export GST_PLUGIN_PATH="$PWD/build/plugins${GST_PLUGIN_PATH:+:$GST_PLUGIN_PATH}"

GST_DEBUG=cpuyolodetect:6 gst-launch-1.0 -e \
  filesrc location="$PWD/assets/detection-demo.mp4" ! \
  decodebin ! \
  videoconvert ! video/x-raw,format=RGB ! \
  cpuyolodetect \
    model-file="$PWD/models/yolov8n.onnx" \
    intra-op-threads=4 \
    confidence-threshold=0.4 \
    iou-threshold=0.7 \
    max-detections=100 ! \
  objectdetectionoverlay draw-labels=true ! \
  videoconvert ! \
  fpsdisplaysink \
    video-sink=autovideosink \
    text-overlay=true \
    sync=true
```

Do not add a leaky queue to this file pipeline. To measure maximum processing
throughput without rendering or the source's 12 FPS clock limit, use:

```bash
GST_DEBUG=cpuyolodetect:6 gst-launch-1.0 -e \
  filesrc location="$PWD/assets/detection-demo.mp4" ! \
  decodebin ! \
  videoconvert ! video/x-raw,format=RGB ! \
  cpuyolodetect \
    model-file="$PWD/models/yolov8n.onnx" \
    intra-op-threads=4 ! \
  objectdetectionoverlay ! \
  fpsdisplaysink \
    video-sink=fakesink \
    text-overlay=false \
    sync=false
```

Set `intra-op-threads=1`, `2`, `4`, or another positive value to compare CPU
thread counts. A value of `0` lets ONNX Runtime choose its default.
