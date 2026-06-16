

```
gst-launch-1.0 -v \
  mpegtsmux name=mux alignment=7 ! \
    udpsink host=127.0.0.1 port=5000 sync=false async=false \
  videotestsrc is-live=true pattern=ball ! \
    video/x-raw,width=1280,height=720,framerate=30/1 ! \
    queue leaky=downstream max-size-buffers=1 max-size-time=0 max-size-bytes=0 ! \
    videoconvert ! \
    x264enc tune=zerolatency speed-preset=ultrafast bitrate=2500 key-int-max=30 bframes=0 byte-stream=true ! \
    h264parse config-interval=1 ! \
    queue ! mux. \
  appsrc name=klvsrc is-live=true format=time do-timestamp=true \
    caps="meta/x-klv,parsed=true" ! \
    queue leaky=downstream max-size-buffers=1 max-size-time=0 max-size-bytes=0 ! \
    mux.
```


```
gst-launch-1.0 -v \
  udpsrc port=5000 buffer-size=2097152 caps="video/mpegts, systemstream=true, packetsize=188" ! \
  tsdemux latency=0 name=demux \
  demux. ! queue leaky=downstream max-size-buffers=1 max-size-time=0 max-size-bytes=0 ! \
    h264parse ! avdec_h264 max-threads=1 ! videoconvert ! autovideosink sync=false \
  demux. ! queue ! "meta/x-klv" ! filesink location=~/tmp/received.klv
```