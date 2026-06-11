#!/usr/bin/env bash
set -euo pipefail

# Deploy the latest bt_joy wheel to a remote machine via sftp, then install it.
# Usage examples:
# REMOTE_USER=pi REMOTE_DIR=/home/pi/tmp ./scripts/deploy_bt_joy.sh
# REMOTE_USER=pi REMOTE_DIR=/home/pi/tmp REMOTE_RELOAD_CMD='systemctl restart bt-joy' ./scripts/deploy_bt_joy.sh

REMOTE_USER="${REMOTE_USER:-user}"
REMOTE_HOST="${REMOTE_HOS



T:-10.100.102.11}"
REMOTE_DIR="${REMOTE_DIR:-/tmp}"
REMOTE_VENV_DIR="${REMOTE_VENV_DIR:-/home/${REMOTE_USER}/bt_joy_venv}"

WHEEL_PATH=$(ls -t bt_joy/dist/*.whl 2>/dev/null | head -n1 || true)
if [ -z "$WHEEL_PATH" ]; then
  echo "No wheel found in bt_joy/dist. Build the wheel first (e.g. python -m build in bt_joy)."
  exit 1
fi
WHEEL_NAME=$(basename "$WHEEL_PATH")

echo "Uploading $WHEEL_NAME to $REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR"
# Use sftp in batch mode to upload
sftp "$REMOTE_USER@$REMOTE_HOST" <<EOF
put "$WHEEL_PATH" "$REMOTE_DIR/"
bye
EOF

echo "Creating/using virtualenv at $REMOTE_VENV_DIR on $REMOTE_HOST and installing wheel"
ssh "$REMOTE_USER@$REMOTE_HOST" bash -s -- "$REMOTE_VENV_DIR" "$REMOTE_DIR" "$WHEEL_NAME" <<'REMOTE_SCRIPT'
set -euo pipefail
REMOTE_VENV_DIR="$1"
REMOTE_DIR="$2"
WHEEL_NAME="$3"

PY3_BIN="$(command -v python3 || true)"
if [ -z "$PY3_BIN" ]; then
  echo "python3 not found on remote host"
  exit 1
fi

if [ ! -d "$REMOTE_VENV_DIR" ]; then
  echo "Creating virtualenv at $REMOTE_VENV_DIR"
  "$PY3_BIN" -m venv "$REMOTE_VENV_DIR"
fi

echo "Upgrading pip and installing wheel"
"$REMOTE_VENV_DIR/bin/pip" install --upgrade pip >/dev/null
"$REMOTE_VENV_DIR/bin/pip" install --upgrade "$REMOTE_DIR/$WHEEL_NAME"
echo "Installed $WHEEL_NAME into $REMOTE_VENV_DIR"
REMOTE_SCRIPT

# Optional reload/restart command on remote. Set REMOTE_RELOAD_CMD env var to run.
if [ -n "${REMOTE_RELOAD_CMD:-}" ]; then
  echo "Running remote reload command: $REMOTE_RELOAD_CMD"
  ssh "$REMOTE_USER@$REMOTE_HOST" "$REMOTE_RELOAD_CMD"
fi

echo "Done."
