# bt-gst

`bt-gst` captures video from a file, V4L2 camera, or Gazebo image source,
optionally detects red objects, and streams H.264 over RTP/UDP. Detection
results can be drawn on the video and published to `bt_app` over ZMQ.

## Setup

Install the native dependencies:

```bash
./scripts/install-deps-ubuntu.sh
```

Create the Python environment and install the package:

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
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
bt-gst show -c config.example.yaml
bt-gst run -c config.example.yaml
```

`show` prints the resolved pipeline. `run` starts it and exits on EOS, an
error, or Ctrl+C.

The detector runs before the video tee, so its output reaches both the RTP
stream and the optional local preview. With `overlay_enabled: true`, the
preview and stream include the detected bounding box.

The ZMQ request and red-detection telemetry contract is documented in
[`docs/design/bt_app_zmq_interface.md`](docs/design/bt_app_zmq_interface.md).
