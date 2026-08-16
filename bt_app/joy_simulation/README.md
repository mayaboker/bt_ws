# Joy simulation

These scripts send MAVLink RC override messages to exercise bt-app joystick
and flight-state scenarios. Run them from the `bt_app` package directory:

```bash
cd /home/user/projects/bt_ws/bt_app
python3 joy_simulation/send_rc_arm.py
```

## Scenario scripts

| Test script | Short description |
| --- | --- |
| `send_rc_arm.py` | Arm in MANUAL, verify the armed state, then disarm and verify IDLE. |
| `send_rc_manual_alt_hold.py` | Ramp MANUAL throttle to 5 m, hold ALT_HOLD for 10 seconds, descend in MANUAL, then disarm. |
| `send_rc_takeoff_diagnostic.py` | Run automatic takeoff and record the takeoff-to-ALT_HOLD response. |
| `joy_simulation/send_rc_auto_yaw.py` | Exercise controlled yaw commands while in ALT_HOLD. |
| `joy_simulation/send_rc_auto_roll.py` | Exercise controlled roll commands while in ALT_HOLD. |
| `joy_simulation/send_rc_auto_pitch.py` | Exercise controlled pitch commands while in ALT_HOLD. |
| `joy_simulation/send_rc_glide.py` | Run the visual GLIDE entry and tracking scenario. |
| `joy_simulation/send_rc_tracking.py` | Exercise tracker-mode and visual tracking transitions. |

The scripts use the default SITL endpoints of destination `127.0.0.1:14560`
and telemetry listener `0.0.0.0:14550`. Confirm that bt-app/SITL is running
before starting a scenario. Stop an active scenario with `Ctrl-C`; airborne
failures stop RC transmission so bt-app's communication failsafe can recover.

## Adding a new scenario

Create a new `send_rc_<name>.py` module and subclass
`MavlinkRcScenarioBase` from `joy_simulation/mavlink_rc_scenario.py`:

```python
from joy_simulation.mavlink_rc_scenario import (
    ARM_IN_MANUAL,
    MANUAL_DISARMED,
    NEUTRAL_DISARMED,
    STATE_IDLE,
    STATE_MANUAL,
    MavlinkRcScenarioBase,
)


class MyScenario(MavlinkRcScenarioBase):
    def run(self) -> None:
        self._open()
        try:
            self._wait_for(
                NEUTRAL_DISARMED,
                lambda: self.telemetry.state is not None,
                self.state_timeout_s,
                "application heartbeat",
            )
            self._wait_for_state(
                ARM_IN_MANUAL,
                STATE_MANUAL,
                self.state_timeout_s,
            )
            # Add the scenario-specific RC flow here.
            self._wait_for(
                MANUAL_DISARMED,
                lambda: self.telemetry.state == STATE_IDLE
                and not self.telemetry.armed,
                self.state_timeout_s,
                "IDLE with armed flag cleared",
            )
            self._completed = True
        finally:
            self._cleanup()
```

Use the base helpers for all transport and timing operations:

- `_open()` and `_cleanup()` manage the UDP socket and safety behavior.
- `_send_rc(channels)` sends one RC override frame.
- `_send_for(channels, duration_s)` repeatedly sends a command.
- `_wait_for(...)` sends a command while waiting for a predicate.
- `_wait_for_state(...)` waits for a named bt-app state.
- `self.telemetry` contains the latest state, armed flag, and relative altitude.

Keep scenario-specific flight logic in `run()` or small private methods. Add a
short row to the scenario table above and keep fixed test values in the script
when the scenario is intended for repeatable SITL validation.
