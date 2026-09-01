#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

: "${BT_ANALYSIS_HOST:=127.0.0.1}"
: "${BT_ANALYSIS_PORT:=8002}"
: "${BT_ANALYSIS_LOGS_DIR:=${WORKSPACE_ROOT}/bt_app/logs/blackbox}"

if ! command -v uv >/dev/null 2>&1; then
  echo "Missing required command: uv" >&2
  echo "Install uv, then run this script again." >&2
  exit 1
fi

if [[ ! -f "${WORKSPACE_ROOT}/bt_analysis/pyproject.toml" ]]; then
  echo "Missing bt_analysis package at ${WORKSPACE_ROOT}/bt_analysis" >&2
  exit 1
fi

echo "BT analysis: http://${BT_ANALYSIS_HOST}:${BT_ANALYSIS_PORT}"
echo "Blackbox logs: ${BT_ANALYSIS_LOGS_DIR}"

cd "${WORKSPACE_ROOT}"
exec uv run --project bt_analysis bt-analysis run \
  --host "${BT_ANALYSIS_HOST}" \
  --port "${BT_ANALYSIS_PORT}" \
  --logs-dir "${BT_ANALYSIS_LOGS_DIR}"
