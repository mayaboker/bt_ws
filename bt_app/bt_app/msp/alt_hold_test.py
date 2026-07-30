from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from bt_app.msp.bt_v2 import BetaflightMspClient
from bt_app.msp.command_dispatcher import RcChannels
from bt_app.msp.transport import SerialMspTransport, TcpMspTransport


RC_MIN = 1000
RC_MID = 1500
RC_MAX = 2000

ROLL = 0
PITCH = 1
THROTTLE = 2
YAW = 3
AUX1_ARM = 4
AUX2_ANGLE = 5
AUX3_ALT_HOLD = 6
AUX4 = 7


class FlightPhase(str, Enum):
    PREARM = "prearm"
    ARM = "arm"
    TAKEOFF = "takeoff"
    HOLD = "alt_hold"
    LAND = "land"
    DISARM = "disarm"
    TELEMETRY_FAILSAFE = "telemetry_failsafe"
    COMPLETE = "complete"


@dataclass(frozen=True)
class AltHoldTestConfig:
    target_altitude_m: float = 4.0
    hold_duration_s: float = 10.0
    prearm_duration_s: float = 2.0
    arm_duration_s: float = 2.0
    disarm_duration_s: float = 1.0
    takeoff_timeout_s: float = 30.0
    max_altitude_m: float = 6.0
    target_tolerance_m: float = 0.5
    target_settle_s: float = 1.0
    landed_altitude_m: float = 0.2
    landed_vertical_speed_m_s: float = 0.2
    landed_settle_s: float = 1.0
    telemetry_loss_grace_s: float = 2.0
    kp: float = 60.0
    ki: float = 0.0
    kd: float = 6.0
    base_throttle: int = RC_MID
    output_limit: int = 400

    def validate(self) -> None:
        positive_values = {
            "target_altitude_m": self.target_altitude_m,
            "hold_duration_s": self.hold_duration_s,
            "takeoff_timeout_s": self.takeoff_timeout_s,
            "max_altitude_m": self.max_altitude_m,
            "target_tolerance_m": self.target_tolerance_m,
            "target_settle_s": self.target_settle_s,
            "landed_altitude_m": self.landed_altitude_m,
            "landed_vertical_speed_m_s": self.landed_vertical_speed_m_s,
            "landed_settle_s": self.landed_settle_s,
            "telemetry_loss_grace_s": self.telemetry_loss_grace_s,
        }
        for name, value in positive_values.items():
            if value <= 0:
                raise ValueError(f"{name} must be > 0")
        if self.max_altitude_m <= self.target_altitude_m:
            raise ValueError("max_altitude_m must be above target_altitude_m")
        if not RC_MIN <= self.base_throttle <= RC_MAX:
            raise ValueError("base_throttle must be between 1000 and 2000")
        if self.output_limit <= 0:
            raise ValueError("output_limit must be > 0")


class AltitudePid:
    def __init__(self, config: AltHoldTestConfig) -> None:
        self.config = config
        self.integral = 0.0
        self.previous_error = 0.0
        self.previous_time: float | None = None

    def reset(self) -> None:
        self.integral = 0.0
        self.previous_error = 0.0
        self.previous_time = None

    def throttle(self, target_m: float, altitude_m: float, now: float) -> int:
        error = target_m - altitude_m
        if self.previous_time is None:
            dt = 0.0
            derivative = 0.0
        else:
            dt = max(0.0, now - self.previous_time)
            derivative = (error - self.previous_error) / dt if dt else 0.0

        self.integral += error * dt
        correction = (
            self.config.kp * error
            + self.config.ki * self.integral
            + self.config.kd * derivative
        )
        correction = max(
            -self.config.output_limit,
            min(self.config.output_limit, correction),
        )
        self.previous_error = error
        self.previous_time = now
        return round(
            max(
                RC_MIN,
                min(RC_MAX, self.config.base_throttle + correction),
            )
        )


class AltHoldFlightTest:
    def __init__(
        self,
        config: AltHoldTestConfig,
        start_time: float,
        initial_altitude_m: float,
    ) -> None:
        config.validate()
        self.config = config
        self.phase = FlightPhase.PREARM
        self.phase_started_at = start_time
        self.altitude_m = initial_altitude_m
        self.vertical_speed_m_s = 0.0
        self.last_telemetry_at = start_time
        self.telemetry_failure_since: float | None = None
        self.target_reached_since: float | None = None
        self.landed_since: float | None = None
        self.pid = AltitudePid(config)
        self.message = "sending disarmed low-throttle RC"

    @property
    def airborne(self) -> bool:
        return self.phase in {
            FlightPhase.TAKEOFF,
            FlightPhase.HOLD,
            FlightPhase.LAND,
            FlightPhase.TELEMETRY_FAILSAFE,
        }

    def update_telemetry(
        self,
        altitude_m: float,
        vertical_speed_m_s: float,
        now: float,
    ) -> None:
        if not math.isfinite(altitude_m) or not math.isfinite(vertical_speed_m_s):
            raise ValueError("altitude telemetry must be finite")
        self.altitude_m = altitude_m
        self.vertical_speed_m_s = vertical_speed_m_s
        self.last_telemetry_at = now
        self.telemetry_failure_since = None
        if self.phase is FlightPhase.TELEMETRY_FAILSAFE:
            self._transition(
                FlightPhase.LAND,
                now,
                "telemetry recovered; starting controlled landing",
            )

    def mark_telemetry_failure(self, now: float) -> None:
        if self.telemetry_failure_since is None:
            self.telemetry_failure_since = now
        if not self.airborne:
            raise RuntimeError("altitude telemetry lost before takeoff")
        if (
            self.phase is not FlightPhase.TELEMETRY_FAILSAFE
            and now - self.telemetry_failure_since
            >= self.config.telemetry_loss_grace_s
        ):
            self._transition(
                FlightPhase.TELEMETRY_FAILSAFE,
                now,
                "telemetry unavailable; holding with AUX3 and awaiting operator",
            )

    def request_land(self, now: float) -> None:
        if self.phase in {FlightPhase.TAKEOFF, FlightPhase.HOLD}:
            self._transition(
                FlightPhase.LAND,
                now,
                "operator requested controlled landing",
            )

    def channels(self, now: float) -> RcChannels:
        self._advance_timed_phase(now)

        if self.telemetry_failure_since is not None and self.airborne:
            return self._make_channels(
                throttle=RC_MID,
                armed=True,
                angle=True,
                alt_hold=True,
            )

        if self.phase is FlightPhase.PREARM:
            return self._make_channels(RC_MIN, armed=False, angle=False, alt_hold=False)
        if self.phase is FlightPhase.ARM:
            return self._make_channels(RC_MIN, armed=True, angle=True, alt_hold=False)
        if self.phase is FlightPhase.TAKEOFF:
            return self._takeoff_channels(now)
        if self.phase is FlightPhase.HOLD:
            return self._make_channels(RC_MID, armed=True, angle=True, alt_hold=True)
        if self.phase is FlightPhase.LAND:
            return self._landing_channels(now)
        if self.phase is FlightPhase.TELEMETRY_FAILSAFE:
            return self._make_channels(RC_MID, armed=True, angle=True, alt_hold=True)
        return self._make_channels(RC_MIN, armed=False, angle=False, alt_hold=False)

    def _advance_timed_phase(self, now: float) -> None:
        elapsed = now - self.phase_started_at
        if (
            self.phase is FlightPhase.PREARM
            and elapsed >= self.config.prearm_duration_s
        ):
            self._transition(FlightPhase.ARM, now, "arming on AUX1 with ANGLE on AUX2")
        elif self.phase is FlightPhase.ARM and elapsed >= self.config.arm_duration_s:
            self._transition(
                FlightPhase.TAKEOFF,
                now,
                f"closed-loop takeoff to {self.config.target_altitude_m:.2f} m",
            )
        elif self.phase is FlightPhase.HOLD and elapsed >= self.config.hold_duration_s:
            self._transition(
                FlightPhase.LAND,
                now,
                "ALT HOLD interval complete; starting controlled landing",
            )
        elif (
            self.phase is FlightPhase.DISARM
            and elapsed >= self.config.disarm_duration_s
        ):
            self._transition(FlightPhase.COMPLETE, now, "test complete")

    def _takeoff_channels(self, now: float) -> RcChannels:
        elapsed = now - self.phase_started_at
        if self.altitude_m >= self.config.max_altitude_m:
            self._transition(
                FlightPhase.LAND,
                now,
                "maximum-altitude guard triggered; starting landing",
            )
            return self._landing_channels(now)
        if elapsed >= self.config.takeoff_timeout_s:
            self._transition(
                FlightPhase.LAND,
                now,
                "takeoff timeout; starting landing",
            )
            return self._landing_channels(now)

        if (
            abs(self.config.target_altitude_m - self.altitude_m)
            <= self.config.target_tolerance_m
        ):
            if self.target_reached_since is None:
                self.target_reached_since = now
            elif now - self.target_reached_since >= self.config.target_settle_s:
                self._transition(
                    FlightPhase.HOLD,
                    now,
                    "target reached; enabling ALT HOLD on AUX3",
                )
                return self._make_channels(
                    RC_MID,
                    armed=True,
                    angle=True,
                    alt_hold=True,
                )
        else:
            self.target_reached_since = None

        throttle = self.pid.throttle(
            self.config.target_altitude_m,
            self.altitude_m,
            now,
        )
        return self._make_channels(throttle, armed=True, angle=True, alt_hold=False)

    def _landing_channels(self, now: float) -> RcChannels:
        landed = (
            self.altitude_m <= self.config.landed_altitude_m
            and abs(self.vertical_speed_m_s)
            <= self.config.landed_vertical_speed_m_s
        )
        if landed:
            if self.landed_since is None:
                self.landed_since = now
            elif now - self.landed_since >= self.config.landed_settle_s:
                self._transition(
                    FlightPhase.DISARM,
                    now,
                    "landing confirmed; disarming AUX1",
                )
                return self._make_channels(
                    RC_MIN,
                    armed=False,
                    angle=False,
                    alt_hold=False,
                )
        else:
            self.landed_since = None

        throttle = self.pid.throttle(0.0, self.altitude_m, now)
        return self._make_channels(throttle, armed=True, angle=True, alt_hold=False)

    def _transition(self, phase: FlightPhase, now: float, message: str) -> None:
        self.phase = phase
        self.phase_started_at = now
        self.message = message
        self.target_reached_since = None
        self.landed_since = None
        self.pid.reset()

    @staticmethod
    def _make_channels(
        throttle: int,
        armed: bool,
        angle: bool,
        alt_hold: bool,
    ) -> RcChannels:
        channels = [RC_MID] * 8
        channels[THROTTLE] = int(max(RC_MIN, min(RC_MAX, throttle)))
        channels[AUX1_ARM] = RC_MAX if armed else RC_MIN
        channels[AUX2_ANGLE] = RC_MAX if angle else RC_MIN
        channels[AUX3_ALT_HOLD] = RC_MAX if alt_hold else RC_MIN
        channels[AUX4] = RC_MIN
        return tuple(channels)  # type: ignore[return-value]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Arm, take off to 4 m, test Betaflight ALT HOLD, and land over MSP."
    )
    parser.add_argument("--transport", choices=("tcp", "serial"), default="tcp")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5761)
    parser.add_argument("--device", default="/dev/ttyUSB0")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--target-altitude", type=float, default=4.0)
    parser.add_argument("--hold-duration", type=float, default=10.0)
    parser.add_argument("--rc-rate-hz", type=float, default=50.0)
    parser.add_argument("--telemetry-rate-hz", type=float, default=10.0)
    parser.add_argument("--telemetry-timeout", type=float, default=0.25)
    parser.add_argument("--takeoff-timeout", type=float, default=30.0)
    parser.add_argument("--max-altitude", type=float, default=6.0)
    parser.add_argument("--kp", type=float, default=60.0)
    parser.add_argument("--ki", type=float, default=0.0)
    parser.add_argument("--kd", type=float, default=6.0)
    parser.add_argument("--base-throttle", type=int, default=1500)
    parser.add_argument("--output-limit", type=int, default=400)
    parser.add_argument("--target-tolerance", type=float, default=0.5)
    parser.add_argument("--target-settle", type=float, default=1.0)
    parser.add_argument("--landed-altitude", type=float, default=0.2)
    parser.add_argument("--landed-vertical-speed", type=float, default=0.2)
    parser.add_argument("--landed-settle", type=float, default=1.0)
    parser.add_argument("--telemetry-loss-grace", type=float, default=2.0)
    return parser


def _config_from_args(args: argparse.Namespace) -> AltHoldTestConfig:
    return AltHoldTestConfig(
        target_altitude_m=args.target_altitude,
        hold_duration_s=args.hold_duration,
        takeoff_timeout_s=args.takeoff_timeout,
        max_altitude_m=args.max_altitude,
        target_tolerance_m=args.target_tolerance,
        target_settle_s=args.target_settle,
        landed_altitude_m=args.landed_altitude,
        landed_vertical_speed_m_s=args.landed_vertical_speed,
        landed_settle_s=args.landed_settle,
        telemetry_loss_grace_s=args.telemetry_loss_grace,
        kp=args.kp,
        ki=args.ki,
        kd=args.kd,
        base_throttle=args.base_throttle,
        output_limit=args.output_limit,
    )


def _transport_from_args(args: argparse.Namespace):
    if args.transport == "serial":
        return SerialMspTransport(args.device, baudrate=args.baudrate)
    return TcpMspTransport(args.host, args.port)


def _print_sample(
    controller: AltHoldFlightTest,
    channels: Sequence[int],
    event: str | None = None,
) -> None:
    record = {
        "timestamp_s": time.time(),
        "phase": controller.phase.value,
        "altitude_m": round(controller.altitude_m, 3),
        "vertical_speed_m_s": round(controller.vertical_speed_m_s, 3),
        "throttle": channels[THROTTLE],
        "aux1_arm": channels[AUX1_ARM],
        "aux2_angle": channels[AUX2_ANGLE],
        "aux3_alt_hold": channels[AUX3_ALT_HOLD],
    }
    if event is not None:
        record["event"] = event
    print(json.dumps(record, separators=(",", ":"), sort_keys=True), flush=True)


def run(args: argparse.Namespace) -> int:
    if args.rc_rate_hz <= 0 or args.telemetry_rate_hz <= 0:
        raise ValueError("RC and telemetry rates must be > 0")
    config = _config_from_args(args)
    config.validate()
    client = BetaflightMspClient(_transport_from_args(args))
    client.open()
    try:
        initial = client.read_altitude(timeout=args.telemetry_timeout)
        now = time.monotonic()
        controller = AltHoldFlightTest(
            config,
            start_time=now,
            initial_altitude_m=initial["altitude_m"],
        )
        controller.update_telemetry(
            initial["altitude_m"],
            initial["vertical_speed_m_s"],
            now,
        )

        rc_period = 1.0 / args.rc_rate_hz
        telemetry_period = 1.0 / args.telemetry_rate_hz
        next_telemetry = now
        previous_phase = controller.phase
        interrupted = False

        while controller.phase is not FlightPhase.COMPLETE:
            loop_started = time.monotonic()
            try:
                telemetry_sampled = False
                if loop_started >= next_telemetry:
                    telemetry_sampled = True
                    try:
                        telemetry = client.read_altitude(
                            timeout=args.telemetry_timeout
                        )
                    except (TimeoutError, ConnectionError, ValueError) as exc:
                        controller.mark_telemetry_failure(loop_started)
                        print(
                            f"MSP altitude telemetry unavailable: {exc}",
                            flush=True,
                        )
                    else:
                        controller.update_telemetry(
                            telemetry["altitude_m"],
                            telemetry["vertical_speed_m_s"],
                            loop_started,
                        )
                    next_telemetry = loop_started + telemetry_period

                channels = controller.channels(loop_started)
                client.send_raw_rc(channels)
                event = None
                if controller.phase is not previous_phase:
                    event = controller.message
                    previous_phase = controller.phase
                if telemetry_sampled or event is not None:
                    _print_sample(controller, channels, event=event)

                elapsed = time.monotonic() - loop_started
                time.sleep(max(0.0, rc_period - elapsed))
            except KeyboardInterrupt:
                if interrupted:
                    raise
                interrupted = True
                if controller.phase is FlightPhase.TELEMETRY_FAILSAFE:
                    print(
                        "Telemetry is unavailable; automatic landing is disabled. "
                        "Restore telemetry or take over manually. Press Ctrl-C again "
                        "to stop MSP output.",
                        flush=True,
                    )
                else:
                    controller.request_land(time.monotonic())
                    print("Interrupt received; requesting controlled landing", flush=True)
                continue
        return 0
    finally:
        client.close()


def main() -> None:
    raise SystemExit(run(_parser().parse_args()))


if __name__ == "__main__":
    main()
