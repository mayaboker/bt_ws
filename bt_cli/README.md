# BTI CLI

`bti` reads and changes `bt_app` parameters over MAVLink. The application must
be running and reachable before using the parameter commands.

## Install

From the repository root:

```bash
cd bt_cli
uv sync
```

Run commands through `uv`:

```bash
uv run bti param --help
```

Alternatively, install the package into the active Python environment:

```bash
python -m pip install -e .
bti param --help
```

## Connection options

Commands connect to `127.0.0.1:14551` and target MAVLink system/component
`1/1` by default. Override these settings when the application is elsewhere:

```bash
uv run bti param list \
  --endpoint 192.168.2.10:14551 \
  --system 1 \
  --component 1 \
  --timeout-ms 3000
```

The endpoint and timeout can also be configured with
`BTI_MAVLINK_ENDPOINT` and `BTI_MAVLINK_TIMEOUT_MS`.

## List parameters

List every available parameter, including its current value, MAVLink type,
count, and index:

```bash
uv run bti param list
```

Parameter names are the canonical uppercase MAVLink IDs shown in this output,
for example `TAKEOFF_ALT`, `HOV_BASELINE`, and `FS_HOLD_TIME`.

## Get a parameter

Read one parameter by name:

```bash
uv run bti param get TAKEOFF_ALT
uv run bti param get HOV_BASELINE
```

The result is printed as JSON with the name, value, MAVLink type, total count,
and parameter index.

## Set a parameter

Set a floating-point parameter:

```bash
uv run bti param set TAKEOFF_ALT 3.5
```

Set an integer parameter:

```bash
uv run bti param set HOV_BASELINE 1400
```

The CLI first reads the parameter to discover its type, sends the update, and
then verifies the value echoed by the application. Limits defined in
`bt_app/parameters.yaml` are enforced by the application. A rejected value
returns a non-zero exit code and reports the current value.

Accepted changes take effect immediately, including while the vehicle is
armed. Use remote writes carefully because controller gains and failsafe values
can change active flight behavior.

## Save parameters

Set operations update runtime state only. Persist the current values to the
application's parameter YAML file with:

```bash
uv run bti param save
```

Saving is rejected while the vehicle is armed. After a successful save, the
values are restored the next time `bt_app` starts.

## Examples

```bash
# Inspect all parameters
uv run bti param list

# Read the current failsafe hold time
uv run bti param get FS_HOLD_TIME

# Change it to 20 seconds
uv run bti param set FS_HOLD_TIME 20.0

# Persist the change after the vehicle is disarmed
uv run bti param save
```

Use `--help` on any command for its available options:

```bash
uv run bti param get --help
uv run bti param set --help
```
