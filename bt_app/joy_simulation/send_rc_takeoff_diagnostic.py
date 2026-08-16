#!/usr/bin/env python3
"""Automatic TAKEOFF, ALT_HOLD dwell, manual descent, and disarm scenario."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Sequence

os.environ.setdefault("MAVLINK20", "1")

try:
    from joy_simulation.mavlink_rc_scenario import (
        ALT_HOLD_ARMED,
        ARM_IN_MANUAL,
        AUTO_TAKEOFF_ARMED,
        MANUAL_DISARMED,
        NEUTRAL_DISARMED,
        STATE_ALT_HOLD,
        STATE_IDLE,
        STATE_MANUAL,
        STATE_TAKEOFF,
        MavlinkRcScenarioBase,
        ScenarioError,
        Telemetry,
        rc_channels,
    )
except ModuleNotFoundError:  # direct script execution
    from mavlink_rc_scenario import (  # type: ignore[no-redef]
        ALT_HOLD_ARMED,
        ARM_IN_MANUAL,
        AUTO_TAKEOFF_ARMED,
        MANUAL_DISARMED,
        NEUTRAL_DISARMED,
        STATE_ALT_HOLD,
        STATE_IDLE,
        STATE_MANUAL,
        STATE_TAKEOFF,
        MavlinkRcScenarioBase,
        ScenarioError,
        Telemetry,
        rc_channels,
    )


SCENARIO_BANNER = """\
==============================================================================
bt-app Automatic TAKEOFF / ALT_HOLD Scenario
==============================================================================
Flight flow:
  1. Arm in MANUAL with low throttle.
  2. Request automatic TAKEOFF.
  3. Wait for TAKEOFF and ALT_HOLD.
  4. Hold ALT_HOLD for 10 seconds.
  5. Switch to MANUAL and descend.
  6. Confirm touchdown and disarm.
=============================================================================="""

ALT_HOLD_DURATION_S = 10.0
STATE_TIMEOUT_S = 20.0
LANDING_TIMEOUT_S = 60.0
TOUCHDOWN_ALTITUDE_M = 0.15
DESCENT_THROTTLE = 1600


class TakeoffScenario(MavlinkRcScenarioBase):
    """Simple automatic TAKEOFF scenario with fixed flight defaults."""

    FIELDNAMES: tuple[str, ...] = ()

    def __init__(self) -> None:
        super().__init__(
            destination=("127.0.0.1", 14560),
            listen=("0.0.0.0", 14550),
            rate_hz=50.0,
            state_timeout_s=STATE_TIMEOUT_S,
            landing_timeout_s=LANDING_TIMEOUT_S,
            touchdown_altitude_m=TOUCHDOWN_ALTITUDE_M,
        )
        self.manual_descent_channels = rc_channels(
            armed=True,
            manual=True,
            throttle=DESCENT_THROTTLE,
        )

    @staticmethod
    def _print_banner() -> None:
        print(SCENARIO_BANNER, flush=True)

    def run(self) -> None:
        self._print_banner()
        self._open()
        try:
            self._phase("Waiting for bt-app telemetry")
            self._wait_for(
                NEUTRAL_DISARMED,
                lambda: self.telemetry.state is not None,
                self.state_timeout_s,
                "application heartbeat",
            )

            self._phase("Arming in MANUAL mode")
            self._wait_for_state(ARM_IN_MANUAL, STATE_MANUAL, self.state_timeout_s)

            self._phase("Requesting automatic TAKEOFF")
            self._wait_for_state(AUTO_TAKEOFF_ARMED, STATE_TAKEOFF, self.state_timeout_s)
            self._airborne = True

            self._phase("Waiting for automatic TAKEOFF to enter ALT_HOLD")
            self._wait_for_state(AUTO_TAKEOFF_ARMED, STATE_ALT_HOLD, self.landing_timeout_s)

            self._phase(f"Holding ALT_HOLD for {ALT_HOLD_DURATION_S:.1f} seconds")
            self._send_for(ALT_HOLD_ARMED, ALT_HOLD_DURATION_S)
            if self.telemetry.state != STATE_ALT_HOLD:
                raise ScenarioError(
                    "Vehicle left ALT_HOLD during dwell; "
                    f"last telemetry: {self.telemetry.describe()}"
                )

            self._phase(f"Switching to MANUAL descent at throttle {DESCENT_THROTTLE}")
            self._wait_for_state(
                self.manual_descent_channels,
                STATE_MANUAL,
                self.state_timeout_s,
            )
            self._wait_for_touchdown()

            self._airborne = False
            self._phase("Disarming and waiting for IDLE")
            self._wait_for(
                MANUAL_DISARMED,
                lambda: self.telemetry.state == STATE_IDLE and not self.telemetry.armed,
                self.state_timeout_s,
                "IDLE with armed flag cleared",
            )
            self._send_for(MANUAL_DISARMED, 0.5)
            self._completed = True
            self._phase("Scenario completed successfully")
        finally:
            self._cleanup()

    def _wait_for_touchdown(self) -> None:
        self._phase("Waiting for touchdown")
        consecutive = 0
        last_sample_count = self.telemetry.altitude_samples

        def touchdown_confirmed() -> bool:
            nonlocal consecutive, last_sample_count
            if self.telemetry.altitude_samples == last_sample_count:
                return consecutive >= 3
            last_sample_count = self.telemetry.altitude_samples
            if (
                self.telemetry.altitude_m is not None
                and self.telemetry.altitude_m <= self.touchdown_altitude_m
            ):
                consecutive += 1
            else:
                consecutive = 0
            return consecutive >= 3

        self._wait_for(
            self.manual_descent_channels,
            touchdown_confirmed,
            self.landing_timeout_s,
            f"three touchdown samples <= {self.touchdown_altitude_m:.2f} m",
        )


# Compatibility names for scenario modules that still import the old symbols.
TakeoffDiagnosticScenario = TakeoffScenario
DiagnosticTelemetry = Telemetry
PARAMETERS: tuple[str, ...] = ()


def build_base_parser() -> argparse.ArgumentParser:
    """Return a compatibility parser; flight settings remain fixed in code."""
    return argparse.ArgumentParser(description=SCENARIO_BANNER)


def main() -> int:
    try:
        TakeoffScenario().run()
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except ScenarioError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
