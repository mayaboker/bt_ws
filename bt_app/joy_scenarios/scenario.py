"""Scenario orchestration facade and safety lifecycle."""

from __future__ import annotations

from collections.abc import Callable
import time

from joy_scenarios.console import ConsoleScenarioLogger, ScenarioLogger
from joy_scenarios.models import (
    JoystickCommand,
    ScenarioConfig,
    ScenarioError,
    TelemetrySnapshot,
)
from joy_scenarios.telemetry import TelemetryMonitor
from joy_scenarios.transport import MavlinkUdpTransport, RcTransport


class JoyScenario:
    """Coordinate reusable operator actions over an injected RC transport."""

    def __init__(
        self,
        config: ScenarioConfig,
        *,
        transport: RcTransport | None = None,
        logger: ScenarioLogger | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.transport = transport or MavlinkUdpTransport(
            destination=config.destination,
            listen=config.listen,
        )
        self.logger = logger or ConsoleScenarioLogger(color=config.color)
        self.clock = clock
        self.sleep = sleep
        self.monitor = TelemetryMonitor()
        self._airborne = False
        self._completed = False
        self._opened = False

    @property
    def telemetry(self) -> TelemetrySnapshot:
        return self.monitor.snapshot

    @property
    def period_s(self) -> float:
        return 1.0 / self.config.rate_hz

    def __enter__(self) -> JoyScenario:
        self.transport.open()
        self._opened = True
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self._cleanup()
        return False

    def send(self, command: JoystickCommand) -> None:
        self.transport.send(command)

    def poll(self) -> None:
        for message in self.transport.receive():
            update = self.monitor.consume(message)
            if update.transition is not None:
                self.logger.state_transition(update.transition)

    def send_for(
        self,
        command: JoystickCommand,
        duration_s: float,
        *,
        guard: Callable[[], bool] | None = None,
        guard_description: str = "scenario guard",
    ) -> None:
        deadline = self.clock() + duration_s
        while self.clock() < deadline:
            self.send(command)
            self.poll()
            if guard is not None and not guard():
                raise ScenarioError(
                    f"Failed {guard_description}; last telemetry: "
                    f"{self.telemetry.describe()}"
                )
            self.sleep(self.period_s)

    def send_for_or_until(
        self,
        command: JoystickCommand,
        duration_s: float,
        predicate: Callable[[], bool],
    ) -> bool:
        """Send for at most ``duration_s``, stopping when predicate is true."""

        deadline = self.clock() + duration_s
        while self.clock() < deadline:
            self.send(command)
            self.poll()
            if predicate():
                return True
            self.sleep(self.period_s)
        return predicate()

    def wait_until(
        self,
        command: JoystickCommand,
        predicate: Callable[[], bool],
        timeout_s: float,
        expectation: str,
    ) -> None:
        deadline = self.clock() + timeout_s
        next_send = 0.0
        while self.clock() < deadline:
            now = self.clock()
            if now >= next_send:
                self.send(command)
                next_send = now + self.period_s
            self.poll()
            if predicate():
                return
            self.sleep(min(0.005, self.period_s))
        raise ScenarioError(
            f"Timed out after {timeout_s:.1f}s waiting for {expectation}; "
            f"last telemetry: {self.telemetry.describe()}"
        )

    def wait_for_state(
        self,
        command: JoystickCommand,
        state: int,
        timeout_s: float,
        *,
        armed: bool | None = None,
    ) -> None:
        def reached() -> bool:
            if self.telemetry.state != state:
                return False
            return armed is None or self.telemetry.armed is armed

        expectation = f"state {state}"
        if armed is not None:
            expectation += f" armed={armed}"
        self.wait_until(command, reached, timeout_s, expectation)

    def mark_airborne(self) -> None:
        self._airborne = True

    def mark_grounded(self) -> None:
        self._airborne = False

    def complete(self) -> None:
        self._completed = True

    def wait_for_telemetry(self) -> None:
        from joy_scenarios.steps import wait_for_telemetry

        wait_for_telemetry(self)

    def arm_manual(self) -> None:
        from joy_scenarios.steps import arm_manual

        arm_manual(self)

    def auto_takeoff(self) -> None:
        from joy_scenarios.steps import auto_takeoff

        auto_takeoff(self)

    def hold_altitude(self, duration_s: float) -> None:
        from joy_scenarios.steps import hold_altitude

        hold_altitude(self, duration_s)

    def wait_for_altitude(
        self,
        target_m: float,
        *,
        tolerance_m: float = 0.3,
        timeout_s: float | None = None,
    ) -> None:
        from joy_scenarios.steps import wait_for_altitude

        wait_for_altitude(
            self,
            target_m,
            tolerance_m=tolerance_m,
            timeout_s=timeout_s,
        )

    def change_altitude(
        self,
        target_m: float,
        *,
        tolerance_m: float = 0.3,
        timeout_s: float | None = None,
    ) -> None:
        from joy_scenarios.steps import change_altitude

        change_altitude(
            self,
            target_m,
            tolerance_m=tolerance_m,
            timeout_s=timeout_s,
        )

    def turn_yaw(
        self,
        angle_deg: float,
        *,
        clockwise: bool,
        timeout_s: float,
    ) -> float:
        from joy_scenarios.steps import turn_yaw

        return turn_yaw(
            self,
            angle_deg,
            clockwise=clockwise,
            timeout_s=timeout_s,
        )

    def enter_tracker_1(
        self,
        *,
        entry_timeout_s: float,
        pulse_duration_s: float,
    ) -> int:
        from joy_scenarios.steps import enter_tracker_1

        return enter_tracker_1(
            self,
            entry_timeout_s=entry_timeout_s,
            pulse_duration_s=pulse_duration_s,
        )

    def move_target_gate(
        self,
        *,
        roll: int,
        pitch: int,
        duration_s: float,
    ) -> None:
        from joy_scenarios.steps import move_target_gate

        move_target_gate(
            self,
            roll=roll,
            pitch=pitch,
            duration_s=duration_s,
        )

    def wait_for_tracker_exit(self, *, tracking_timeout_s: float) -> None:
        from joy_scenarios.steps import wait_for_tracker_exit

        wait_for_tracker_exit(self, tracking_timeout_s=tracking_timeout_s)

    def disable_tracker_and_recover(self, *, timeout_s: float) -> None:
        from joy_scenarios.steps import disable_tracker_and_recover

        disable_tracker_and_recover(self, timeout_s=timeout_s)

    def land_manual(self, throttle: int) -> None:
        from joy_scenarios.steps import land_manual

        land_manual(self, throttle)

    def disarm(self) -> None:
        from joy_scenarios.steps import disarm

        disarm(self)

    def _cleanup(self) -> None:
        if not self._opened:
            return
        try:
            if not self._completed and not self._airborne:
                self.logger.phase("Sending final ground-safe disarm command")
                self.send_for(JoystickCommand.manual_disarmed(), 0.5)
            elif not self._completed:
                self.logger.failure(
                    "Stopping RC while airborne; bt-app failsafe must recover"
                )
        except (OSError, ScenarioError):
            pass
        finally:
            self.transport.close()
            self._opened = False
