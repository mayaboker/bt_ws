# video test

```bash
gst-launch-1.0 v4l2src name=camera device=/dev/video0 \
            ! video/x-raw,format=I420,width=640,height=512,framerate=30/1 \
            ! videoconvert \
            ! video/x-raw,format=I420 \
            ! tee name=tee \
        tee. \
            ! queue name=live-queue \
            ! videoconvert name=live-convert \
            ! x264enc bitrate=1500 tune=zerolatency speed-preset=ultrafast \
               key-int-max=30 bframes=0 byte-stream=true aud=true \
               intra-refresh=false sliced-threads=false threads=1 \
            ! video/x-h264,stream-format=byte-stream,alignment=au,profile=constrained-baseline  \
            ! h264parse config-interval=1 \
            ! rtph264pay pt=96 mtu=800 config-interval=1 aggregate-mode=zero-latency \
            ! udpsink host=10.0.0.48 port=5600 sync=false async=false 
```