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
resolved starter GStreamer pipeline. The `run` command starts the resolved
pipeline and exits on EOS, error, or Ctrl+C.

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
