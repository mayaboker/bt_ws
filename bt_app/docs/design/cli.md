`bt-app` runs the main drone control application the application listen to different rc command source and forward the selected one depend on the state machine to the drone over MSP

## Commands

```bash
bt-app [--log-level LEVEL] COMMAND [OPTIONS]
```

| Command | Description |
| --- | --- |
| `version` | Print the installed client package version. |
| `dump_config` | Load the client YAML, apply supported CLI overrides, validate it, and print the effective YAML to stdout. If `-c` is omitted, the packaged default config is printed. |
| `run` | Start the joystick client and block until the process is stopped. |

`--log-level` can be `TRACE`, `DEBUG`, `INFO`, `SUCCESS`, `WARNING`, `ERROR`, or
`CRITICAL`. When provided, it overrides the YAML `log_level` value.

## Common Usage

Print the version:

```bash
bt-app version
```

## `run` Options

| Option | YAML field overridden | Description |
| --- | --- | --- |
| `-c, --config PATH` | none | Client YAML file. The packaged default is used when omitted. |
