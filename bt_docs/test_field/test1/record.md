# Record

```bash
uv run bt-gst-record run -c config.yaml
```

```bash
gst-launch-1.0 -v udpsrc port=5600 caps="application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000" \
            ! rtph264depay \
            ! h264parse \
            ! avdec_h264 \
            ! videoconvert \
            ! fpsdisplaysink video-sink=autovideosink sync=false text-overlay=true
```

```bash
