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
bt-gst play
bt-gst play data/vtest.avi
```

The default `bt-gst play` command opens `data/vtest.avi` with a GTK window using
GStreamer's `gtksink`. The command sets `GST_PLUGIN_PATH` automatically so
GStreamer can find the Python plugins in `plugins/python`.

To inspect the bundled pass-through plugin manually:

```bash
GST_PLUGIN_PATH="$PWD/plugins" gst-inspect-1.0 btpassthrough
```

## Test

```bash
pytest
```
