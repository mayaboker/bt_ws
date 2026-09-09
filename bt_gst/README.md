# bt-gst

`bt-gst` captures video from a file, V4L2 camera, or Gazebo image source,
optionally detects red objects, and streams H.264 over RTP/UDP. Detection
results can be drawn directly on the video.

## Build all native plugins

The root CMake project builds `controlledreddetect`, `cpunanotrack`,
`metaprint`, and `cpuyolodetect` into one directory:

```bash
cd /home/user/projects/bt_ws/bt_gst
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build
ctest --test-dir build --output-on-failure
export GST_PLUGIN_PATH="$PWD/build/plugins${GST_PLUGIN_PATH:+:$GST_PLUGIN_PATH}"
gst-inspect-1.0 controlledreddetect
gst-inspect-1.0 cpunanotrack
gst-inspect-1.0 metaprint
gst-inspect-1.0 cpuyolodetect
```

The CPU inference plugins require a complete ONNX Runtime SDK under
`third_party/onnxruntime-linux-x64-1.29.0`, including
`lib/libonnxruntime.so`. Optional plugins can be disabled when their
dependencies are unavailable:

```bash
cmake -S . -B build -G Ninja \
  -DBT_GST_BUILD_CPU_NANOTRACK=OFF \
  -DBT_GST_BUILD_CPU_YOLO_DETECT=OFF
```

Each plugin's standalone CMake build remains supported.

See the [`cpuyolodetect` usage guide](docs/cpuyolodetect_usage.md) for model
requirements, inspection, headless checks, and image/video/camera pipelines.

## Setup

Install the native dependencies:

```bash
./scripts/install-deps-ubuntu.sh
```

Create the Python environment and install the package:

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -e ../bt_msgs
python -m pip install -e ".[dev]"
```

`--system-site-packages` lets the environment use the distribution-provided
GStreamer introspection modules.

## Build the detector plugin

```bash
cmake -S plugins/gst_detector -B plugins/gst_detector/build
cmake --build plugins/gst_detector/build
```

Inspect the plugin with:

```bash
GST_PLUGIN_PATH="$PWD/plugins/gst_detector/build" \
  gst-inspect-1.0 controlledreddetect
```

## Run

```bash
bt-gst --help
bt-gst version
bt-gst show --source file --path data/vtest.avi
bt-gst run --source file --path data/vtest.avi
```

`show` prints the resolved pipeline. `run` starts it and exits on EOS, an
error, or Ctrl+C.

The detector runs before the video tee, so its output reaches both the RTP
stream and the optional local preview. With `overlay_enabled: true`, the
preview and stream include the detected bounding box.

When `zmq.enabled` is true, each detector frame supplies a
`bt_msgs.TrackerResultMessage` to a background publisher. It contains the frame
ID, GStreamer PTS in nanoseconds, detection lock, and bounding box, plus generic
tracker fields with explicit placeholder values. The publisher sends only the
latest result on the configured PUB endpoint at no more than
`zmq.max_rate_hz`, without doing serialization or socket work on the GStreamer
streaming thread.

With red detection enabled, bt_gst also connects by default to
`tcp://127.0.0.1:5557` for absolute `TargetSelectorCommandMessage` updates from
bt-app. The socket worker validates and stores only the newest command; the
pipeline runner applies it to `controlledreddetect`. The Cairo overlay draws
all candidates blue, an invalid selector yellow, and the selected target and
valid selector green.

## Tracker backends

The legacy `detector:` configuration continues to select
`controlledreddetect`. New configurations can select either backend explicitly
with `tracker.type: controlled_red` or `tracker.type: cpu_nano`.

CPU NanoTrack consumes BGR frames and publishes the same
`TrackerResultMessage` wire format as the red detector. Its native metadata is
different: confidence from `GstVideoRegionOfInterestMeta` is compared with
`confidence_threshold`; only qualifying boxes are published as locked.

Use `bt_bringup/launch/gst_cpu_nano.yaml` for selector-controlled NanoTrack:

```bash
export GST_PLUGIN_PATH="$PWD/build-cpunanotracker${GST_PLUGIN_PATH:+:$GST_PLUGIN_PATH}"
bt-gst run -c ../bt_bringup/launch/gst_cpu_nano.yaml
```

In `initialization: selector` mode, target-selector coordinates reposition a
configured `selector_roi_size` and reinitialize tracking. Use
`initialization: fixed` with `fixed_roi: [x, y, width, height]` to start from a
static ROI instead. Existing `selector_zmq` and `zmq` endpoints are unchanged.
