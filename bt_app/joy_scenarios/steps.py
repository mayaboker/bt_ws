"""Reusable operator actions for joystick-driven flight scenarios."""

from __future__ import annotations

from typing import Protocol

from bt_app.common import RobotState

from joy_scenarios.models import (
    RC_MAX,
    JoystickCommand,
    ScenarioConfig,
    ScenarioError,
    TelemetrySnapshot,
)


class ScenarioRuntime(Protocol):
    config: ScenarioConfig

    @property
    def telemetry(self) -> TelemetrySnapshot: ...

    def send_for(self, command: JoystickCommand, duration_s: float, **kwargs) -> None: ...

    def send_for_or_until(
        self,
        command: JoystickCommand,
        duration_s: float,
        predicate,
    ) -> bool: ...

    def wait_until(
        self,
        command: JoystickCommand,
        predicate,
        timeout_s: float,
        expectation: str,
    ) -> None: ...

    def wait_for_state(
        self,
        command: JoystickCommand,
        state: int,
        timeout_s: float,
        *,
        armed: bool | None = None,
    ) -> None: ...

    def mark_airborne(self) -> None: ...

    def mark_grounded(self) -> None: ...

    @property
    def logger(self): ...

    def clock(self) -> float: ...


def wait_for_telemetry(scenario: ScenarioRuntime) -> None:
    scenario.logger.phase("Waiting for bt-app telemetry")
    scenario.wait_until(
        JoystickCommand.neutral_disarmed(),
        lambda: scenario.telemetry.state is not None,
        scenario.config.state_timeout_s,
        "application heartbeat",
    )


def arm_manual(scenario: ScenarioRuntime) -> None:
    scenario.logger.phase("Arming in MANUAL mode")
    scenario.wait_for_state(
        JoystickCommand.manual_armed(),
        RobotState.MANUAL,
        scenario.config.state_timeout_s,
        armed=True,
    )


def auto_takeoff(scenario: ScenarioRuntime) -> None:
    command = JoystickCommand.automatic_takeoff()
    scenario.logger.phase("Requesting automatic takeoff")
    scenario.wait_for_state(
        command,
        RobotState.TAKEOFF,
        scenario.config.state_timeout_s,
        armed=True,
    )
    scenario.mark_airborne()
    scenario.logger.phase("Waiting for automatic takeoff to enter ALT_HOLD")
    scenario.wait_for_state(
        command,
        RobotState.ALT_HOLD,
        scenario.config.takeoff_timeout_s,
        armed=True,
    )


def hold_altitude(scenario: ScenarioRuntime, duration_s: float) -> None:
    if duration_s < 0:
        raise ValueError("duration_s cannot be negative")
    scenario.logger.phase(f"Holding ALT_HOLD for {duration_s:.1f} seconds")
    scenario.send_for(
        JoystickCommand.altitude_hold(),
        duration_s,
        guard=lambda: scenario.telemetry.state == RobotState.ALT_HOLD,
        guard_description="ALT_HOLD state during dwell",
    )


def wait_for_altitude(
    scenario: ScenarioRuntime,
    target_m: float,
    *,
    tolerance_m: float = 0.3,
    timeout_s: float | None = None,
) -> None:
    """Hold centered throttle until altitude settles around a target."""

    if target_m < 0:
        raise ValueError("target altitude cannot be negative")
    if tolerance_m <= 0:
        raise ValueError("altitude tolerance must be greater than zero")
    timeout = scenario.config.takeoff_timeout_s if timeout_s is None else timeout_s
    if timeout <= 0:
        raise ValueError("altitude timeout must be greater than zero")

    consecutive_samples = 0
    last_sample_count = scenario.telemetry.altitude_samples

    def settled() -> bool:
        nonlocal consecutive_samples, last_sample_count
        if scenario.telemetry.state != RobotState.ALT_HOLD:
            raise ScenarioError(
                "Vehicle left ALT_HOLD while waiting for altitude; "
                f"last telemetry: {scenario.telemetry.describe()}"
            )
        if scenario.telemetry.altitude_samples == last_sample_count:
            return consecutive_samples >= 3
        last_sample_count = scenario.telemetry.altitude_samples
        altitude = scenario.telemetry.altitude_m
        if altitude is not None and abs(altitude - target_m) <= tolerance_m:
            consecutive_samples += 1
        else:
            consecutive_samples = 0
        return consecutive_samples >= 3

    scenario.logger.phase(
        f"Waiting for altitude {target_m:.2f} m ± {tolerance_m:.2f} m"
    )
    scenario.wait_until(
        JoystickCommand.altitude_hold(),
        settled,
        timeout,
        f"three fresh altitude samples near {target_m:.2f} m",
    )


def change_altitude(
    scenario: ScenarioRuntime,
    target_m: float,
    *,
    tolerance_m: float = 0.3,
    timeout_s: float | None = None,
) -> None:
    """Move the ALT_HOLD setpoint with the throttle stick, then settle."""

    if target_m < 0:
        raise ValueError("target altitude cannot be negative")
    if tolerance_m <= 0:
        raise ValueError("altitude tolerance must be greater than zero")
    timeout = scenario.config.takeoff_timeout_s if timeout_s is None else timeout_s
    if timeout <= 0:
        raise ValueError("altitude timeout must be greater than zero")
    current_altitude = scenario.telemetry.altitude_m
    if current_altitude is None:
        raise ScenarioError("Cannot change altitude without altitude telemetry")

    # Center first to complete the TAKEOFF -> ALT_HOLD throttle handover.
    scenario.send_for(
        JoystickCommand.altitude_hold(),
        0.5,
        guard=lambda: scenario.telemetry.state == RobotState.ALT_HOLD,
        guard_description="ALT_HOLD throttle handover",
    )

    ascending = target_m > current_altitude
    throttle = RC_MAX if ascending else 1000
    command = JoystickCommand.altitude_hold().with_controls(throttle=throttle)

    def setpoint_reached() -> bool:
        if scenario.telemetry.state != RobotState.ALT_HOLD:
            raise ScenarioError(
                "Vehicle left ALT_HOLD during altitude command; "
                f"last telemetry: {scenario.telemetry.describe()}"
            )
        setpoint = scenario.telemetry.altitude_setpoint_m
        if setpoint is None:
            return False
        return setpoint >= target_m if ascending else setpoint <= target_m

    direction = "climbing" if ascending else "descending"
    scenario.logger.phase(
        f"ALT_HOLD {direction}: moving setpoint to {target_m:.2f} m"
    )
    scenario.wait_until(
        command,
        setpoint_reached,
        timeout,
        f"ALT_HOLD setpoint {target_m:.2f} m",
    )

    # Center immediately so the controller retains the requested setpoint.
    scenario.send_for(
        JoystickCommand.altitude_hold(),
        0.25,
        guard=lambda: scenario.telemetry.state == RobotState.ALT_HOLD,
        guard_description="ALT_HOLD after centering throttle",
    )
    wait_for_altitude(
        scenario,
        target_m,
        tolerance_m=tolerance_m,
        timeout_s=timeout,
    )


def turn_yaw(
    scenario: ScenarioRuntime,
    angle_deg: float,
    *,
    clockwise: bool,
    timeout_s: float,
) -> float:
    """Command full-stick yaw until measured rotation reaches an angle."""

    if angle_deg <= 0:
        raise ValueError("yaw angle must be greater than zero")
    if timeout_s <= 0:
        raise ValueError("yaw timeout must be greater than zero")
    if scenario.telemetry.yaw_deg is None:
        raise ScenarioError("Cannot turn without ATTITUDE yaw telemetry")

    yaw_rc = RC_MAX if clockwise else 1000
    command = JoystickCommand.altitude_hold().with_controls(yaw=yaw_rc)
    direction = "CW" if clockwise else "CCW"
    previous_yaw = scenario.telemetry.yaw_deg
    last_sample_count = scenario.telemetry.attitude_samples
    accumulated_deg = 0.0

    def reached_angle() -> bool:
        nonlocal previous_yaw, last_sample_count, accumulated_deg
        if scenario.telemetry.state != RobotState.ALT_HOLD:
            raise ScenarioError(
                f"Vehicle left ALT_HOLD during {direction} yaw; "
                f"last telemetry: {scenario.telemetry.describe()}"
            )
        if scenario.telemetry.attitude_samples == last_sample_count:
            return False
        last_sample_count = scenario.telemetry.attitude_samples
        current_yaw = scenario.telemetry.yaw_deg
        if current_yaw is None or previous_yaw is None:
            previous_yaw = current_yaw
            return False
        delta = (current_yaw - previous_yaw + 180.0) % 360.0 - 180.0
        accumulated_deg += delta
        previous_yaw = current_yaw
        directed_progress = accumulated_deg if clockwise else -accumulated_deg
        return directed_progress >= angle_deg

    scenario.logger.phase(
        f"Commanding measured {angle_deg:.0f}° {direction} yaw at full stick"
    )
    started_at = scenario.clock()
    scenario.wait_until(
        command,
        reached_angle,
        timeout_s,
        f"measured {angle_deg:.0f} degree {direction} yaw",
    )
    elapsed_s = max(0.001, scenario.clock() - started_at)
    measured_angle = accumulated_deg if clockwise else -accumulated_deg
    measured_rate = measured_angle / elapsed_s
    scenario.logger.phase(
        f"Completed {direction} yaw: rotation={measured_angle:.1f}° "
        f"elapsed={elapsed_s:.1f}s average_rate={measured_rate:.1f}°/s"
    )
    scenario.send_for(
        JoystickCommand.altitude_hold(),
        1.0,
        guard=lambda: scenario.telemetry.state == RobotState.ALT_HOLD,
        guard_description="ALT_HOLD while centering yaw",
    )
    return measured_rate


def enter_tracker_1(
    scenario: ScenarioRuntime,
    *,
    entry_timeout_s: float,
    pulse_duration_s: float,
) -> int:
    """Select tracker 1 and pulse enable until TRACK is observed."""

    if entry_timeout_s <= 0 or pulse_duration_s <= 0:
        raise ValueError("tracker entry timeout and pulse duration must be positive")
    low = JoystickCommand.tracker_1_selected(enable=False)
    high = JoystickCommand.tracker_1_selected(enable=True)
    deadline = scenario.clock() + entry_timeout_s
    pulse_count = 0
    scenario.logger.phase("Selecting tracker 1 and waiting for target lock")

    while scenario.clock() < deadline:
        low_duration = min(pulse_duration_s, max(0.0, deadline - scenario.clock()))
        if scenario.send_for_or_until(
            low,
            low_duration,
            lambda: scenario.telemetry.state == RobotState.TRACK,
        ):
            break
        pulse_count += 1
        scenario.logger.phase(f"Sending tracker enable pulse {pulse_count}")
        high_duration = min(pulse_duration_s, max(0.0, deadline - scenario.clock()))
        if scenario.send_for_or_until(
            high,
            high_duration,
            lambda: scenario.telemetry.state == RobotState.TRACK,
        ):
            break
    else:
        raise ScenarioError(
            "Timed out waiting for TRACK; verify bt-gst target detection"
        )

    scenario.send_for(low, 0.1)
    scenario.logger.phase(f"TRACK entered after {pulse_count} enable pulse(s)")
    return pulse_count


def move_target_gate(
    scenario: ScenarioRuntime,
    *,
    roll: int,
    pitch: int,
    duration_s: float,
) -> None:
    """Move the image-space target gate while the aircraft remains in ALT_HOLD."""

    if duration_s <= 0:
        raise ValueError("target gate move duration must be positive")
    command = JoystickCommand.tracker_1_selected().with_controls(
        roll=roll,
        pitch=pitch,
    )
    scenario.logger.phase(
        f"Moving target gate with roll={roll} pitch={pitch} for {duration_s:.2f}s"
    )
    scenario.send_for(
        command,
        duration_s,
        guard=lambda: scenario.telemetry.state == RobotState.ALT_HOLD,
        guard_description="ALT_HOLD while moving target gate",
    )
    scenario.logger.phase("Centering target gate command before lock")
    scenario.send_for(
        JoystickCommand.tracker_1_selected(),
        0.25,
        guard=lambda: scenario.telemetry.state == RobotState.ALT_HOLD,
        guard_description="ALT_HOLD while centering target gate command",
    )


def wait_for_tracker_exit(
    scenario: ScenarioRuntime,
    *,
    tracking_timeout_s: float,
) -> None:
    """Keep tracker 1 selected until TRACK exits automatically."""

    if tracking_timeout_s <= 0:
        raise ValueError("tracking timeout must be positive")
    scenario.logger.phase("TRACK active; waiting for automatic ALT_HOLD exit")
    scenario.wait_for_state(
        JoystickCommand.tracker_1_selected(enable=False),
        RobotState.ALT_HOLD,
        tracking_timeout_s,
        armed=True,
    )
    scenario.logger.phase("Tracking exited automatically")


def disable_tracker_and_recover(
    scenario: ScenarioRuntime,
    *,
    timeout_s: float,
) -> None:
    """Disable tracker selection and confirm recovery in ALT_HOLD."""

    if timeout_s <= 0:
        raise ValueError("tracker recovery timeout must be positive")
    scenario.logger.phase("Disabling tracker and recovering ALT_HOLD")
    scenario.wait_for_state(
        JoystickCommand.altitude_hold(),
        RobotState.ALT_HOLD,
        timeout_s,
        armed=True,
    )


def land_manual(scenario: ScenarioRuntime, throttle: int) -> None:
    if not 1000 <= throttle <= 1650:
        raise ValueError("landing throttle must be between 1000 and 1650")
    command = JoystickCommand.manual_armed(throttle=throttle)
    scenario.logger.phase(
        f"Switching to MANUAL for fixed-throttle landing at {throttle}"
    )
    scenario.wait_for_state(
        command,
        RobotState.MANUAL,
        scenario.config.state_timeout_s,
        armed=True,
    )

    consecutive_samples = 0
    last_sample_count = scenario.telemetry.altitude_samples

    def touchdown() -> bool:
        nonlocal consecutive_samples, last_sample_count
        if scenario.telemetry.altitude_samples == last_sample_count:
            return consecutive_samples >= 3
        last_sample_count = scenario.telemetry.altitude_samples
        altitude = scenario.telemetry.altitude_m
        if (
            altitude is not None
            and altitude <= scenario.config.touchdown_altitude_m
        ):
            consecutive_samples += 1
        else:
            consecutive_samples = 0
        return consecutive_samples >= 3

    scenario.logger.phase("Waiting for touchdown")
    scenario.wait_until(
        command,
        touchdown,
        scenario.config.landing_timeout_s,
        "three consecutive fresh touchdown altitude samples",
    )
    scenario.mark_grounded()


def disarm(scenario: ScenarioRuntime) -> None:
    scenario.logger.phase("Disarming and waiting for IDLE")
    command = JoystickCommand.manual_disarmed()
    scenario.wait_for_state(
        command,
        RobotState.IDLE,
        scenario.config.state_timeout_s,
        armed=False,
    )
    scenario.send_for(command, 0.5)
