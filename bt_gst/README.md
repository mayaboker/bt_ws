# bt-gst

GStreamer utilities for the BT workspace.

## Setup

```bash
cd bt_gst
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

This project uses the GStreamer Python binding through `PyGObject`. The Python
packages are declared in `pyproject.toml`, but GStreamer itself is a native
system dependency. Use `--system-site-packages` so the virtualenv can see the
system `gi` modules. On Ubuntu/Debian, install the runtime packages with:

```bash
sudo apt install \
  python3-gi \
  gir1.2-gstreamer-1.0 \
  gir1.2-gtk-3.0 \
  gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good \
  gstreamer1.0-libav
```

## Run

```bash
bt-gst --help
bt-gst version
bt-gst show -c config.example.yaml
bt-gst run -c config.example.yaml
```

The `show` command loads YAML config, merges CLI overrides, and prints the
resolved H.264 RTP/UDP streaming pipeline. The `run` command starts the
resolved pipeline and exits on EOS, error, or Ctrl+C.

To inspect the bundled pass-through plugin manually:

```bash
GST_PLUGIN_PATH="$PWD/plugins" gst-inspect-1.0 btpassthrough
```

## gst gazebo image src plugin

```bash
GST_PLUGIN_PATH="$PWD/plugins" gst-inspect-1.0 customsrc
```

```bash
GST_PLUGIN_PATH="$PWD/plugins" gst-launch-1.0 customsrc ! videoconvert ! autovideosink
```



```
gst-launch-1.0 -v videotestsrc is-live=true pattern=smpte   ! video/x-raw,width=640,height=480,framerate=30/1   ! videoconvert   ! videoscale   ! video/x-raw,format=I420,width=640,height=480,framerate=30/1   ! x264enc bitrate=1500 tune=zerolatency speed-preset=ultrafast       key-int-max=30 bframes=0 byte-stream=true aud=true       intra-refresh=false sliced-threads=false threads=1   ! video/x-h264,stream-format=byte-stream,alignment=au,profile=constrained-baseline   ! h264parse config-interval=1   ! rtph264pay pt=96 mtu=800 config-interval=1 aggregate-mode=zero-latency   ! udpsink host=127.0.0.1 port=5600 sync=false async=false
```

```
GST_PLUGIN_PATH="$PWD/plugins" gst-launch-1.0 -v   gzimagesrc topic=/camera fps=30   ! videoconvert   ! videoscale   ! video/x-raw,format=I420,width=640,height=480,framerate=30/1   ! x264enc bitrate=1500 tune=zerolatency speed-preset=ultrafast       key-int-max=30 bframes=0 byte-stream=true aud=true       intra-refresh=false sliced-threads=false threads=1   ! video/x-h264,stream-format=byte-stream,alignment=au,profile=constrained-baseline   ! h264parse config-interval=1   ! rtph264pay pt=96 mtu=800 config-interval=1 aggregate-mode=zero-latency   ! udpsink host=127.0.0.1 port=5600 sync=false async=false 
```