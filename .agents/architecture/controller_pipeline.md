# bt-joy Controller Pipeline Design Prompt

When planning or implementing server-side flight behavior in `bt_joy`, use this architecture.

## Separation Rules

Keep these responsibilities separate:

- `udp_server.py`
  - UDP socket receive loop
  - packet parsing
  - keepalive response
  - joystick-data freshness/failsafe timing
  - no MSP logic
  - no Crossfire logic
  - no automation logic

- `controller.py`
  - application orchestration layer
  - receives parsed joystick frames
  - updates manual input state
  - reads state snapshots
  - runs automation manager
  - sends final output channels to adapter
  - owns final decision point before output

- `automation/`
  - flight behavior state machines
  - takeoff, hover, land, emergency logic
  - no UDP socket code
  - no MSP transport code

- `adapters/`
  - output protocols only
  - MSP, Crossfire, mock output
  - receive final channels and transmit them
  - no automation decisions

- `state.py`
  - thread-safe shared server state
  - manual channels
  - output channels
  - FC-reported RC
  - status
  - altitude
  - snapshots only for readers

## Desired Pipeline

```text
UDP packet
  -> parse JoystickFrame
  -> JoystickController.handle_frame()
  -> update manual channels
  -> automation manager produces output channels
  -> update output channels
  -> adapter.write_channels(output_channels)
```

## Core Types

Use a parsed frame object:

```python
@dataclass(frozen=True)
class JoystickFrame:
    channels: tuple[int, ...]
    sequence: int
    timestamp_us: int
    source: tuple[str, int]
```

Use named channel indexes:

```python
RcChannel.THROTTLE
RcChannel.AUX4
RcChannel.AUX1
```

Do not use raw indexes like `channels[2]` unless wrapped by the enum.

## Planning Requirement

When adding automation or flight logic:

1. Do not put the logic in `udp_server.py`.
2. Do not put the logic in `adapters/msp.py`.
3. First propose or use the controller pipeline.
4. Show which module owns each responsibility.
5. Keep the first implementation pass-through if needed.
6. Add tests for each layer independently.

## Implementation Order

1. Add or update `server/controller.py`.
2. Make UDP parsing return `JoystickFrame`.
3. Wire `run_udp_server()` to call controller.
4. Add pass-through controller behavior.
5. Add automation manager.
6. Add automation process.
7. Keep adapter behavior protocol-only.
