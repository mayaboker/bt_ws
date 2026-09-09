#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

: "${GZIMGSRC_PLUGIN_DIR:=/home/user/projects/gz_betaflight_bridge/gst/gst_gzimgsrc/build}"
: "${DETECTOR_PLUGIN_DIR:=${WORKSPACE_ROOT}/bt_gst/plugins/gst_detector/build}"
: "${CPUNANOTRACK_PLUGIN_DIR:=${WORKSPACE_ROOT}/bt_gst/build/plugins}"
: "${CPUYOLO_PLUGIN_DIR:=${WORKSPACE_ROOT}/bt_gst/build/plugins}"
: "${ONNXRUNTIME_LIBRARY_DIR:=${WORKSPACE_ROOT}/bt_gst/third_party/onnxruntime-linux-x64-1.29.0/lib}"
: "${BT_GST_PYTHON:=${WORKSPACE_ROOT}/bt_gst/.venv/bin/python}"
GZ_IMAGE_TOPIC="${GZ_IMAGE_TOPIC:-/X3/front_camera/image}"

choose_tracker() {
  if [[ -n "${TRACKER_BACKEND:-}" ]]; then
    return
  fi
  if [[ ! -t 0 ]]; then
    echo "No interactive terminal; set TRACKER_BACKEND=controlled_red, cpu_nano, or cpu_yolo" >&2
    exit 2
  fi

  echo "Select tracker backend:"
  PS3="Tracker [1-3]: "
  select tracker in controlled_red cpu_nano cpu_yolo; do
    if [[ -n "${tracker}" ]]; then
      TRACKER_BACKEND="${tracker}"
      return
    fi
    echo "Invalid selection; enter 1 or 2." >&2
  done
}

choose_tracker

case "${TRACKER_BACKEND}" in
  controlled_red)
    : "${GST_CONFIG:=${SCRIPT_DIR}/gst.yaml}"
    TRACKER_PLUGIN_DIR="${DETECTOR_PLUGIN_DIR}"
    TRACKER_PLUGIN_FILE="${TRACKER_PLUGIN_DIR}/libgstcontrolledreddetect.so"
    TRACKER_ELEMENT="controlledreddetect"
    ;;
  cpu_nano)
    : "${GST_CONFIG:=${SCRIPT_DIR}/gst_cpu_nano.yaml}"
    TRACKER_PLUGIN_DIR="${CPUNANOTRACK_PLUGIN_DIR}"
    TRACKER_PLUGIN_FILE="${TRACKER_PLUGIN_DIR}/libgstcpunanotrack.so"
    TRACKER_ELEMENT="cpunanotrack"
    ;;
  cpu_yolo)
    : "${GST_CONFIG:=${SCRIPT_DIR}/gst_cpu_yolo.yaml}"
    TRACKER_PLUGIN_DIR="${CPUYOLO_PLUGIN_DIR}"
    TRACKER_PLUGIN_FILE="${TRACKER_PLUGIN_DIR}/libgstcpuyolodetect.so"
    TRACKER_ELEMENT="cpuyolodetect"
    export LD_LIBRARY_PATH="${ONNXRUNTIME_LIBRARY_DIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
    ;;
  *)
    echo "Unsupported TRACKER_BACKEND: ${TRACKER_BACKEND}" >&2
    echo "Expected controlled_red, cpu_nano, or cpu_yolo." >&2
    exit 2
    ;;
esac

for plugin in "${GZIMGSRC_PLUGIN_DIR}/libgstgzimgsrc.so" "${TRACKER_PLUGIN_FILE}"; do
  if [[ ! -f "${plugin}" ]]; then
    echo "Missing GStreamer plugin: ${plugin}" >&2
    exit 1
  fi
done

if [[ ! -f "${GST_CONFIG}" ]]; then
  echo "Missing bt-gst configuration: ${GST_CONFIG}" >&2
  exit 1
fi

if [[ ! -x "${BT_GST_PYTHON}" ]]; then
  echo "Missing bt-gst Python environment: ${BT_GST_PYTHON}" >&2
  echo "Run: cd ${WORKSPACE_ROOT}/bt_gst && uv sync --extra dev" >&2
  exit 1
fi

if ! (
  cd "${WORKSPACE_ROOT}/bt_gst"
  "${BT_GST_PYTHON}" -c \
    'from bt_msgs import TrackerResultMessage; import bt_gst.app' 2>/dev/null
)
then
  echo "The bt-gst Python environment is missing bt-gst or bt-msgs." >&2
  echo "Run: cd ${WORKSPACE_ROOT}/bt_gst && uv sync --extra dev" >&2
  exit 1
fi

export GST_PLUGIN_PATH="${GZIMGSRC_PLUGIN_DIR}:${TRACKER_PLUGIN_DIR}${GST_PLUGIN_PATH:+:${GST_PLUGIN_PATH}}"

echo "Tracker backend=${TRACKER_BACKEND}"
echo "GST_PLUGIN_PATH=${GST_PLUGIN_PATH}"
echo "Gazebo image topic=${GZ_IMAGE_TOPIC}"
echo "bt-gst config=${GST_CONFIG}"
echo "bt-gst python=${BT_GST_PYTHON}"

gst-inspect-1.0 gzimgsrc >/dev/null
gst-inspect-1.0 "${TRACKER_ELEMENT}" >/dev/null

cd "${WORKSPACE_ROOT}/bt_gst"
exec "${BT_GST_PYTHON}" -m bt_gst.app \
  --log-level INFO \
  run \
  --config "${GST_CONFIG}" \
  --source simulation \
  --topic "${GZ_IMAGE_TOPIC}"
