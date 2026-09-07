#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

: "${GZIMGSRC_PLUGIN_DIR:=/home/user/projects/gz_betaflight_bridge/gst/gst_gzimgsrc/build}"
: "${CPUNANOTRACK_PLUGIN_DIR:=${WORKSPACE_ROOT}/bt_gst/build-cpunanotracker}"
: "${GZ_IMAGE_TOPIC:=/X3/front_camera/image}"
: "${NANOTRACK_MODELS_DIR:=${WORKSPACE_ROOT}/bt_gst/src/cpunanotracker/models}"
: "${NANOTRACK_ROI:=100,80,60,90}"

for file in \
  "${GZIMGSRC_PLUGIN_DIR}/libgstgzimgsrc.so" \
  "${CPUNANOTRACK_PLUGIN_DIR}/libgstcpunanotrack.so" \
  "${CPUNANOTRACK_PLUGIN_DIR}/libgstmetaprint.so" \
  "${NANOTRACK_MODELS_DIR}/nanotrack_backbone_template.onnx" \
  "${NANOTRACK_MODELS_DIR}/nanotrack_backbone.onnx" \
  "${NANOTRACK_MODELS_DIR}/nanotrack_head.onnx"
do
  if [[ ! -f "${file}" ]]; then
    echo "Missing required file: ${file}" >&2
    exit 1
  fi
done

export GST_PLUGIN_PATH="${GZIMGSRC_PLUGIN_DIR}:${CPUNANOTRACK_PLUGIN_DIR}${GST_PLUGIN_PATH:+:${GST_PLUGIN_PATH}}"

echo "Gazebo topic: ${GZ_IMAGE_TOPIC}"
echo "NanoTrack ROI: ${NANOTRACK_ROI}"
echo "NanoTrack models: ${NANOTRACK_MODELS_DIR}"

exec gst-launch-1.0 -v \
  gzimgsrc topic="${GZ_IMAGE_TOPIC}" \
  ! queue max-size-buffers=1 max-size-bytes=0 max-size-time=0 leaky=downstream \
  ! videoconvert \
  ! video/x-raw,format=BGR \
  ! cpunanotrack enabled=true roi="${NANOTRACK_ROI}" models-dir="${NANOTRACK_MODELS_DIR}" \
  ! metaprint \
  ! fakesink sync=false
