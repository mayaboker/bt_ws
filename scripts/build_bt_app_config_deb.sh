#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VEHICLE_TEMPLATE="${VEHICLE_TEMPLATE:-${ROOT_DIR}/bt_app/config/vehicle_config.yaml}"
PARAMETERS_TEMPLATE="${PARAMETERS_TEMPLATE:-${ROOT_DIR}/bt_app/parameters.yaml}"
JOY_SERVER_TEMPLATE="${JOY_SERVER_TEMPLATE:-${ROOT_DIR}/joy_config/server.yaml}"
VERSION_FILE="${VERSION_FILE:-${ROOT_DIR}/bt_app/bt_app/_version.py}"
TARGET_USER="${TARGET_USER:-user}"
OUTPUT_DIR="${OUTPUT_DIR:-${ROOT_DIR}/build/deb}"
STAGING_ROOT="${ROOT_DIR}/build/deb-staging"

require_file() {
  local path="$1"
  local label="$2"
  if [ ! -f "$path" ]; then
    echo "$label not found: $path" >&2
    exit 1
  fi
}

prompt_default() {
  local prompt="$1"
  local default="$2"
  local value
  read -r -p "$prompt [$default]: " value
  printf '%s' "${value:-$default}"
}

require_file "$VEHICLE_TEMPLATE" "Vehicle config template"
require_file "$PARAMETERS_TEMPLATE" "Parameters template"
require_file "$JOY_SERVER_TEMPLATE" "Joystick server config template"
require_file "$VERSION_FILE" "Version file"

DEFAULTS="$(
  python3 - "$VEHICLE_TEMPLATE" "$VERSION_FILE" <<'PY'
from pathlib import Path
import ast
import re
import sys

import yaml

vehicle_config = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
version_tree = ast.parse(Path(sys.argv[2]).read_text(encoding="utf-8"))
version = None
for node in version_tree.body:
    if (
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ):
        version = node.value.value
        break
if version is None:
    raise SystemExit("Could not find __version__ in version file")

debian_version = re.sub(r"[^A-Za-z0-9.+:~_-]", "~", version)
debian_version = debian_version.replace("-dev", "~dev")

print(vehicle_config.get("gcs_ip", "127.0.0.1"))
print(vehicle_config.get("gcs_port", 14550))
print(debian_version)
PY
)"

DEFAULT_GCS_IP="$(printf '%s\n' "$DEFAULTS" | sed -n '1p')"
DEFAULT_GCS_PORT="$(printf '%s\n' "$DEFAULTS" | sed -n '2p')"
VERSION="$(printf '%s\n' "$DEFAULTS" | sed -n '3p')"

VEHICLE_NAME="$(prompt_default "Vehicle/config name" "default")"
GCS_IP="$(prompt_default "GCS IP" "$DEFAULT_GCS_IP")"
GCS_PORT="$(prompt_default "GCS port" "$DEFAULT_GCS_PORT")"

SLUG="$(python3 - "$VEHICLE_NAME" <<'PY'
import re
import sys

slug = sys.argv[1].strip().lower()
slug = re.sub(r"[^a-z0-9.+-]+", "-", slug)
slug = slug.strip(".+-")
if not slug:
    raise SystemExit("Vehicle/config name must contain at least one letter or number")
if not re.match(r"^[a-z0-9]", slug):
    raise SystemExit("Vehicle/config name must start with a letter or number after normalization")
print(slug)
PY
)"

PACKAGE_NAME="bt-app-config-${SLUG}"
CONFIG_DIR="/home/${TARGET_USER}/config/${SLUG}"
WRAPPER_NAME="bt-app-${SLUG}"
JOY_SERVER_WRAPPER_NAME="bt-joy-server-${SLUG}"
PACKAGE_ROOT="${STAGING_ROOT}/${PACKAGE_NAME}"
DEB_PATH="${OUTPUT_DIR}/${PACKAGE_NAME}_${VERSION}_all.deb"

rm -rf "$PACKAGE_ROOT"
mkdir -p \
  "$PACKAGE_ROOT/DEBIAN" \
  "$PACKAGE_ROOT${CONFIG_DIR}" \
  "$PACKAGE_ROOT/usr/local/bin" \
  "$OUTPUT_DIR"

python3 - "$VEHICLE_TEMPLATE" "$PACKAGE_ROOT${CONFIG_DIR}/vehicle_config.yaml" "$CONFIG_DIR/parameters.yaml" "$GCS_IP" "$GCS_PORT" <<'PY'
from pathlib import Path
import sys

import yaml

template_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])
parameters_path = sys.argv[3]
gcs_ip = sys.argv[4]
gcs_port_raw = sys.argv[5]

try:
    gcs_port = int(gcs_port_raw)
except ValueError as exc:
    raise SystemExit(f"GCS port must be an integer: {gcs_port_raw}") from exc

data = yaml.safe_load(template_path.read_text(encoding="utf-8")) or {}
data["gcs_ip"] = gcs_ip
data["gcs_port"] = gcs_port
data["config_name"] = parameters_path
output_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
PY

cp "$PARAMETERS_TEMPLATE" "$PACKAGE_ROOT${CONFIG_DIR}/parameters.yaml"
cp "$JOY_SERVER_TEMPLATE" "$PACKAGE_ROOT${CONFIG_DIR}/joy_server.yaml"

cat >"$PACKAGE_ROOT/usr/local/bin/${WRAPPER_NAME}" <<EOF
#!/usr/bin/env bash
set -euo pipefail

exec bt-app run -c "${CONFIG_DIR}/vehicle_config.yaml" "\$@"
EOF
chmod 0755 "$PACKAGE_ROOT/usr/local/bin/${WRAPPER_NAME}"

cat >"$PACKAGE_ROOT/usr/local/bin/${JOY_SERVER_WRAPPER_NAME}" <<EOF
#!/usr/bin/env bash
set -euo pipefail

exec bt-joy-server run -c "${CONFIG_DIR}/joy_server.yaml" "\$@"
EOF
chmod 0755 "$PACKAGE_ROOT/usr/local/bin/${JOY_SERVER_WRAPPER_NAME}"

cat >"$PACKAGE_ROOT/DEBIAN/control" <<EOF
Package: ${PACKAGE_NAME}
Version: ${VERSION}
Section: misc
Priority: optional
Architecture: all
Maintainer: Betaloop <noreply@example.invalid>
Description: bt-app vehicle config package for ${SLUG}
 Installs bt-app runtime config files for vehicle ${SLUG}.
EOF

cat >"$PACKAGE_ROOT/DEBIAN/postinst" <<EOF
#!/usr/bin/env bash
set -e

if ! id "${TARGET_USER}" >/dev/null 2>&1; then
  echo "Target user '${TARGET_USER}' does not exist; cannot set config ownership." >&2
  exit 1
fi

chown -R "${TARGET_USER}:${TARGET_USER}" "${CONFIG_DIR}"
chmod 0755 "/home/${TARGET_USER}/config" "${CONFIG_DIR}"
chmod 0644 "${CONFIG_DIR}/vehicle_config.yaml" "${CONFIG_DIR}/parameters.yaml" "${CONFIG_DIR}/joy_server.yaml"
EOF
chmod 0755 "$PACKAGE_ROOT/DEBIAN/postinst"

dpkg-deb --root-owner-group --build "$PACKAGE_ROOT" "$DEB_PATH"

echo "Built $DEB_PATH"
echo "Config will install to $CONFIG_DIR"
echo "Run with: $WRAPPER_NAME"
echo "Run joystick server with: $JOY_SERVER_WRAPPER_NAME"
