#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

: "${GZIMGSRC_PLUGIN_DIR:=/home/user/projects/gz_betaflight_bridge/gst/gst_gzimgsrc/build}"
: "${DETECTOR_PLUGIN_DIR:=${WORKSPACE_ROOT}/bt_gst/plugins/gst_detector/build}"
: "${GST_CONFIG:=${SCRIPT_DIR}/gst.yaml}"
GZ_IMAGE_TOPIC="${GZ_IMAGE_TOPIC:-/X3/front_camera/image}"

for plugin in \
  "${GZIMGSRC_PLUGIN_DIR}/libgstgzimgsrc.so" \
  "${DETECTOR_PLUGIN_DIR}/libgstcontrolledreddetect.so"
do
  if [[ ! -f "${plugin}" ]]; then
    echo "Missing GStreamer plugin: ${plugin}" >&2
    exit 1
  fi
done

if [[ ! -f "${GST_CONFIG}" ]]; then
  echo "Missing bt-gst configuration: ${GST_CONFIG}" >&2
  exit 1
fi

export GST_PLUGIN_PATH="${GZIMGSRC_PLUGIN_DIR}:${DETECTOR_PLUGIN_DIR}${GST_PLUGIN_PATH:+:${GST_PLUGIN_PATH}}"

echo "GST_PLUGIN_PATH=${GST_PLUGIN_PATH}"
echo "Gazebo image topic=${GZ_IMAGE_TOPIC}"
echo "bt-gst config=${GST_CONFIG}"

gst-inspect-1.0 gzimgsrc >/dev/null
gst-inspect-1.0 controlledreddetect >/dev/null

cd "${WORKSPACE_ROOT}/bt_gst"
exec "${WORKSPACE_ROOT}/venv/bin/python" -m bt_gst.app \
  --log-level INFO \
  run \
  --config "${GST_CONFIG}" \
  --source simulation \
  --topic "${GZ_IMAGE_TOPIC}"



# gst-launch-1.0 -v \
#   gzimgsrc topic=/X3/front_camera/image \
#   ! videoconvert \
#   ! video/x-raw,format=RGB \
#   ! controlledreddetect \
#       detection-enabled=true \
#       low-h=0 low-s=100 low-v=100 \
#       high-h=10 high-s=255 high-v=255 \
#   ! tee name=video_tee \
#   video_tee. ! queue \
#   ! videoconvert \
#   ! videoscale \
#   ! videorate \
#   ! video/x-raw,format=I420,width=640,height=480,framerate=30/1 \
#   ! x264enc \
#       bitrate=1500 \
#       tune=zerolatency \
#       speed-preset=ultrafast \
#       key-int-max=30 \
#       bframes=0 \
#       byte-stream=true \
#       aud=true \
#       intra-refresh=false \
#       sliced-threads=false \
#       threads=1 \
#   ! video/x-h264,stream-format=byte-stream,alignment=au,profile=constrained-baseline \
#   ! h264parse config-interval=1 \
#   ! rtph264pay \
#       pt=96 \
#       mtu=1200 \
#       config-interval=1 \
#       aggregate-mode=zero-latency \
#   ! udpsink \
#       host=127.0.0.1 \
#       port=5000 \
#       sync=false \
#       async=false