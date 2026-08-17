# bt-gst

`bt-gst` captures video from a file, V4L2 camera, or Gazebo image source,
optionally detects red objects, and streams H.264 over RTP/UDP. Detection
results can be drawn directly on the video.

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
ID and GStreamer PTS. The publisher sends only the latest result on the
configured PUB endpoint at no more than `zmq.max_rate_hz`, without doing
serialization or socket work on the GStreamer streaming thread.
