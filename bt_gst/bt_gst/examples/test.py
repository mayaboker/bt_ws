import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

Gst.init(None)
Gst.parse_launch('gzimgsrc topic=/camera ! videoconvert ! fakesink')
print('parse ok')

"""
export GST_PLUGIN_PATH=/path/to/gst_gzimgsrc/build \
     gst-launch-1.0 gzimgsrc topic=/camera \
        ! videoconvert \
        ! tee name=video_tee video_tee. ! queue ! videoconvert \
        ! x264enc tune=zerolatency speed-preset=ultrafast \
        ! h264parse config-interval=1 ! rtph264pay pt=96 mtu=1200 \
        ! udpsink host=127.0.0.1 port=5000 sync=false async=false \
        video_tee. ! queue ! videoconvert \
        ! fpsdisplaysink video-sink=glimagesink sync=true
"""
