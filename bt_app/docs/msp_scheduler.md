# MSP Command Scheduler

`MspCommandDispatcher` serializes Betaflight MSP access through one worker thread. Controllers submit command objects instead of calling the MSP client directly, and the dispatcher executes those commands one at a time from a time-ordered heap queue.

## Implementation Idea

The scheduler lives in `bt_app.msp.command_dispatcher`.

The main pieces are:

- `MspCommand`: base class for commands. Each command implements `execute(dispatcher)`.
- `submit(command, delay_s=0.0)`: queues a one-shot command.
- `schedule(command, interval_s=..., delay_s=..., callback=..., key=...)`: wraps a command in `ScheduledCommand` and repeats it after each successful execution.
- `_queue`: a heap of `(run_at, sequence, token, command)` items. The earliest `run_at` is executed first.
- `_active_tokens`: the cancellation/replacement mechanism for keyed commands.
- `_run()`: worker loop that pops ready commands, executes them, and requeues repeating commands.

Every command may define a class-level `key`.

```python
class ReadStateCommand(MspCommand):
    key = "state"
```

When a keyed command is submitted, the dispatcher creates a new token and stores it in `_active_tokens[key]`. Older queued commands with the same key remain in the heap, but become inactive because their token no longer matches. `_pop_ready_command()` skips inactive commands, and `_run()` only reschedules repeating commands while their token is still active.

This gives the scheduler cheap replacement without scanning the heap.

## Register a New Command

Create a class that inherits from `MspCommand`, give it a stable `key` if only one instance should be active at a time, and implement `execute()`.

```python
from dataclasses import dataclass
from typing import ClassVar

from bt_app.msp.command_dispatcher import FunctionCommand, MspCommand, MspCommandDispatcher


@dataclass
class ReadMotorsCommand(MspCommand):
    key: ClassVar[str | None] = "motors"
    repeat_interval_s: float | None = None

    def execute(self, dispatcher: MspCommandDispatcher) -> list[int]:
        motors = dispatcher.msp.read_motors()
        return motors
```

Then schedule it from the adapter or from the controller that owns the behavior:

```python
dispatcher.schedule(ReadMotorsCommand(), interval_s=0.5)
```

For a one-shot command:

```python
dispatcher.submit(ReadMotorsCommand())
```

For a command implemented as a function:

```python
dispatcher.submit(FunctionCommand(lambda dispatcher: dispatcher.set_rc(channels)))
```

Use `callback` when the result should be consumed after execution:

```python
dispatcher.schedule(
    ReadMotorsCommand(),
    interval_s=0.5,
    callback=lambda dispatcher, result: print(result),
)
```

## Replace or Remove a Scheduled Command

There is no explicit `remove_command()` method. Scheduled commands are removed by replacing their active token.

To replace a running command, submit or schedule another command with the same key:

```python
dispatcher.schedule(ReadMotorsCommand(), interval_s=1.0, key="motors")
```

Any older queued or repeating command with key `"motors"` becomes inactive and will not execute again.

To stop an active repeating command, schedule a safe replacement with the same key. For RC output, replace the active `"rc"` command with neutral or disarmed channels:

```python
dispatcher.set_rc((1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000), rate_hz=50.0)
```

To stop all scheduled MSP work, stop the dispatcher thread:

```python
dispatcher.stop()
```

If a public per-command removal API is needed later, implement it by updating `_active_tokens[key]` to a new token under `_lock` and waking `_wake_event`. That uses the existing lazy cancellation behavior without scanning or rebuilding the heap.
