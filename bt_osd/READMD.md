
## osd

```
export GST_PLUGIN_PATH=$PWD/plugins:$GST_PLUGIN_PATH
```

```
GST_DEBUG=python:6,GST_PLUGIN_LOADING:6 \
GST_PLUGIN_PATH=$PWD \
gst-inspect-1.0 pointoverlay
```

```
gst-launch-1.0 \
  videotestsrc ! \
  video/x-raw,format=BGR,width=640,height=480 ! \
  videoconvert ! \
  ximagesink
```

## From camera to pipe

```
v4l2-ctl -d /dev/video0 --list-formats-ext
ioctl: VIDIOC_ENUM_FMT
        Type: Video Capture

        [0]: 'MJPG' (Motion-JPEG, compressed)
                Size: Discrete 1920x1080
                        Interval: Discrete 0.033s (30.000 fps)
                ...
        [1]: 'YUYV' (YUYV 4:2:2)
                Size: Discrete 640x480
                        Interval: Discrete 0.033s (30.000 fps)
                Size: Discrete 640x360
                        Interval: Discrete 0.033s (30.000 fps)
```

```
gst-launch-1.0 \
  v4l2src device=/dev/video0 ! \
  video/x-raw,format=YUY2,width=640,height=480,framerate=30/1 ! \
  videoconvert ! \
  autovideosink
```


---

## Rockchip

```
sudo apt update
sudo apt install -y \
    gstreamer1.0-rockchip \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-tools
```

---

```
gst-launch-1.0 -v \
  videotestsrc is-live=true pattern=ball ! \
  video/x-raw,format=RGB,width=640,height=480,framerate=30/1 ! \
  queue ! \
  shmsink socket-path=/tmp/camera_shm \
          shm-size=20000000 \
          wait-for-connection=false \
          sync=false
```

```
gst-launch-1.0 -v \
  shmsrc socket-path=/tmp/camera_shm is-live=true do-timestamp=true ! \
  video/x-raw,format=RGB,width=640,height=480,framerate=30/1 ! \
  videoconvert ! \
  autovideosink sync=false
```

---

# LK

```
gst-launch-1.0 \
  videotestsrc is-live=true pattern=ball ! \
  video/x-raw,width=640,height=480,framerate=30/1 ! \
  videoconvert ! video/x-raw,format=BGR ! \
  lkroiflow x1=150 y1=120 x2=350 y2=300 max-points=80 ! \
  videoconvert ! autovideosink
```

Print ROI metadata from Python bus messages while playing the same pipeline:

```
python3 plugins/python/demo_lkroiflow_metadata.py
```

The `lkroiflow` plugin posts `lkroiflow-roi` element messages on the GStreamer bus.
Fields:

```
x1 y1 x2 y2 dx dy points pts
```

## LK with appsink metadata

Use `lkroiflowmeta` when you want metadata as a second source pad:

```
python3 plugins/python/demo_lkroiflow_appsink.py
```

The `lkroiflowmeta` plugin exposes:

```
src   video/x-raw,format=BGR
meta  application/x-lkroiflow-roi,format=json
```

The demo links `flow.meta` to an `appsink` and prints JSON metadata buffers.
