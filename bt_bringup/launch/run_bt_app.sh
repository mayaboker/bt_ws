#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

: "${BT_APP_CONFIG:=${WORKSPACE_ROOT}/bt_app/config/vehicle_config.yaml}"
: "${BT_APP_LOG_LEVEL:=INFO}"

if ! command -v uv >/dev/null 2>&1; then
  echo "Missing required command: uv" >&2
  echo "Install uv, then run this script again." >&2
  exit 1
fi

if [[ ! -f "${WORKSPACE_ROOT}/bt_app/pyproject.toml" ]]; then
  echo "Missing bt_app package at ${WORKSPACE_ROOT}/bt_app" >&2
  exit 1
fi

if [[ ! -f "${BT_APP_CONFIG}" ]]; then
  echo "Missing bt-app configuration: ${BT_APP_CONFIG}" >&2
  exit 1
fi

echo "bt-app config: ${BT_APP_CONFIG}"
echo "bt-app log level: ${BT_APP_LOG_LEVEL}"

cd "${WORKSPACE_ROOT}"
exec uv run --project bt_app bt-app \
  --log-level "${BT_APP_LOG_LEVEL}" \
  run \
  --config "${BT_APP_CONFIG}"
