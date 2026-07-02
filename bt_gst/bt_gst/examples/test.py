import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
from bt_gst.gst_environment import remove_local_python_plugin_paths_from_gst_scan, register_local_python_elements

remove_local_python_plugin_paths_from_gst_scan()
Gst.init(None)
register_local_python_elements(Gst)
Gst.parse_launch('gzimagesrc topic=/camera fps=30 ! videoconvert ! fakesink')
print('parse ok')

"""
export GST_PLUGIN_PATH=$PWD/plugins \
     gst-launch-1.0 gzimagesrc topic=/camera fps=30 \
        ! videoconvert \
        ! tee name=video_tee video_tee. ! queue ! videoconvert \
        ! x264enc tune=zerolatency speed-preset=ultrafast \
        ! h264parse config-interval=1 ! rtph264pay pt=96 mtu=1200 \
        ! udpsink host=127.0.0.1 port=5000 sync=false async=false \
        video_tee. ! queue ! videoconvert \
        ! fpsdisplaysink video-sink=glimagesink sync=true
"""