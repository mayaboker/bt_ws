# Agent Notes For `bt_record`

Use the `bt_app` entrypoint shape as the model for `bt_record`: keep parsing,
startup validation, configuration loading, and long-running application code in
separate places. This makes failures predictable, tests cheap, and service
startup safer.

## Recommended Structure

Prefer these modules:

```text
bt_record/
├── bt_record/
│   ├── cli.py
│   ├── errors.py
│   ├── main.py
│   ├── record_app.py
│   └── record_controller.py
└── tests/
```

Suggested ownership:

- `cli.py`: only parse CLI args into a small immutable options object.
- `main.py`: configure logging, build config, handle expected startup errors,
  then dispatch commands.
- `errors.py`: define exit-code enum and expected startup exceptions.
- `record_app.py`: define FastAPI routes and app factory only.
- `record_controller.py`: own GStreamer process/pipeline behavior.

## Exit Codes

Centralize process exit codes in one enum. Do not scatter raw `1`, `2`, `3`
through the code.

Recommended starting point:

```python
from enum import IntEnum


class RecordExitCode(IntEnum):
    SUCCESS = 0
    STARTUP_ERROR = 1
    CLI_USAGE_ERROR = 2
    DEVICE_NOT_FOUND = 3
    GSTREAMER_DEPENDENCY_MISSING = 4
```

Expected startup failures should raise a project exception:

```python
class RecordStartupError(RuntimeError):
    def __init__(
        self,
        message: str,
        exit_code: RecordExitCode = RecordExitCode.STARTUP_ERROR,
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
```

`main.py` should be the only place that turns these exceptions into
`SystemExit(int(code))`.

## CLI Pattern

Follow the `bt_app.cli` style:

- Parse into a `CliOptions` dataclass.
- Keep `click` or `argparse` details out of the app/server code.
- Expose `main(args=None, standalone_mode=True)` so tests can call it directly.
- In `standalone_mode=False`, raise `RuntimeError(message)` instead of exiting.

Useful commands for `bt_record`:

- `run`: start the FastAPI recorder service.
- `version`: print package version.
- `dump_config`: print effective config if a config file is added.

## Startup Validation

Validate before starting Uvicorn or the recorder worker thread.

Check at startup:

- Camera device exists, for example `/dev/video0`.
- Record format is one of `mp4` or `raw`.
- Stream IP is valid.
- Target recording directory can be created or written.
- GStreamer/PyGObject dependencies are importable.

For a missing camera device, prefer:

```text
ERROR | Camera device not found: /dev/video0
```

with exit code `RecordExitCode.DEVICE_NOT_FOUND`.

Do not let `FileNotFoundError` or a GStreamer traceback escape for expected
configuration problems.

## Avoid Global Startup Work

This line in `record_app.py` is risky:

```python
app = create_app(RecordingController())
```

It constructs the controller at import time. Importing the module should not
validate hardware, import-heavy runtime dependencies, start threads, or allocate
GStreamer resources.

Prefer a lazy/default factory:

```python
def make_default_app() -> FastAPI:
    return create_app(RecordingController())


app = make_default_app()
```

If `RecordingController()` can validate hardware, then do not create it at module
import at all. Let `main.py` create it after CLI/config validation.

## Dependency Errors

`record_controller.py` currently raises `SystemExit` during import if `gi` is
missing. Avoid process exits from library modules.

Prefer:

```python
try:
    import gi
except ImportError as exc:
    raise RecordStartupError(
        "Missing PyGObject/GStreamer Python dependencies",
        exit_code=RecordExitCode.GSTREAMER_DEPENDENCY_MISSING,
    ) from exc
```

Then let `main.py` log one clean line and exit with the configured code.

## FastAPI App Factory

Keep `create_app(recorder)` pure:

- It should receive a ready `RecordingController`.
- It should define routes.
- It should start/stop the recorder in lifespan.
- It should not parse CLI args.
- It should not choose devices or ports.

This keeps route tests simple:

```python
app = create_app(fake_recorder)
```

## Runtime Error Boundary

Inside HTTP handlers, convert command failures into HTTP errors, as
`await_record_command()` already does.

But be selective:

- Timeout becomes `504`.
- Invalid user request becomes `400`.
- Conflict such as "already recording" becomes `409`.
- Unexpected controller failure can become `500`.

Do not hide startup validation failures as HTTP `500`; those should fail before
the server starts.

## Tests To Add First

Add focused tests before larger refactors:

- Wrong `--device` exits with `RecordExitCode.DEVICE_NOT_FOUND`.
- Bad `--stream-ip` exits with `RecordExitCode.CLI_USAGE_ERROR`.
- Bad `--record-format` is rejected by CLI parsing.
- `main(..., standalone_mode=False)` raises `RuntimeError`, not `SystemExit`.
- `create_app(fake_recorder)` does not touch real camera hardware.
- Importing `bt_record.record_app` does not start recorder threads.

## Practical Rule

For `bt_record`, the startup sequence should be:

```text
parse args
configure logging
validate config and device paths
construct RecordingController
construct FastAPI app
run uvicorn
```

The shutdown sequence should be owned by FastAPI lifespan:

```text
recorder.start()
yield
recorder.stop()
```

Keep expected startup failures boring: one clear log line, one named exit code,
no traceback.
