import threading
import time
from typing import Any

from loguru import logger as log

from bt_app import FREQ_HZ
from bt_app.common import State
from bt_app.bt_app.context_old import Context
from bt_app.control.pid import PID
from bt_app.control.rc_mapper import BetaflightRcMapper
from bt_app.msp.bt_v2 import (
    RC_MAX,
    RC_MIN,
    RC_MID,
    RCChannel_alias as RCChannel,
)
from bt_app.parameters import Parameters


class HoverYawController:
    """Hold altitude and command a slow constant yaw maneuver."""

    def __init__(
        self,
        context: Context,
        params: Parameters,
        *,
        enabled_states: tuple[State, ...] = (State.SEARCH,),
    ):
        self.context = context
        self.params = params
        self.enabled_states = enabled_states
        self.enable = False
        self.hover_altitude = 0 # update by other keep the last altitude in context
        self.yaw_rate = self.params.get("hover_yaw.yaw_rate")
        self.yaw_stick_range = self.params.get("betaflight_yaw_rate_full_stick_dps")
        self.rc_mapper = BetaflightRcMapper(
            yaw_rate_full_stick_dps=self.yaw_stick_range,
        )
        self._stop_event = threading.Event()
        self._thread = None
        self.params.on_parameter_changed.subscribe(self.on_parameter_changed)
        self.context.on_state_changed += self.on_state_changed
        self.first_run = True
        self._setup()

    def _setup(self):
        self.alt_pid = PID(
            kp=self.params.get("altitude.kp"),
            ki=self.params.get("altitude.ki"),
            kd=self.params.get("altitude.kd"),
            output_limits=self.params.get("altitude.output_limits"),
        )

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="hover-yaw-controller",
            daemon=True,
        )
        self._thread.start()
        log.info("HoverYawController started")

    def stop(self, timeout=2.0):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                log.warning("HoverYawController thread did not stop cleanly")
            else:
                self._thread = None

    def _run(self):
        period_s = 1.0 / FREQ_HZ
        next_tick = time.monotonic()

        while not self._stop_event.is_set():
            try:
                self.update()
            except Exception as exc:
                log.exception("HoverYawController update failed: {}", exc)

            next_tick += period_s
            sleep_s = max(0.0, next_tick - time.monotonic())
            self._stop_event.wait(timeout=sleep_s)

    def initialize(self):
        altitude = self.context.msp.last_altitude
        self.hover_altitude = float(altitude.get("altitude_m", 0.0))
        log.info("HoverYawController initialized with hover altitude: {:.2f}m", self.hover_altitude)

    def update(self):
        """
        if controller is not enabled, do nothing. On first run, initialize hover altitude from current altitude.
         Then read current altitude, compute throttle output from PID, compute yaw output from yaw_rate parameter, and send RC commands to MSP.
        """
        if self.enable is False:
            return
        if self.first_run:
            self.initialize()
            self.first_run = False
        altitude = self.context.msp.last_altitude

        if altitude is None:
            log.warning("No altitude data available for HoverYawController")
            return
        
        current_altitude_m = float(altitude.get("altitude_m", 0.0))
        self.context.set_current_altitude(current_altitude_m)
        throttle_output = int(self.alt_pid.update(self.hover_altitude, current_altitude_m))

        rc_yaw = self.rc_mapper.yaw_rate_to_rc(self.yaw_rate)


        channels = self.make_channels(
            throttle=throttle_output,
            yaw=rc_yaw,
        )
        self.context.msp.set_rc(channels, rate_hz=FREQ_HZ)

    def make_channels(self, throttle: int = 0, yaw: int = 0) -> list[int]:
        channels = [RC_MID] * 8
        throttle = RC_MID + int(throttle)

        channels[RCChannel.THROTTLE] = max(RC_MIN, min(RC_MAX, throttle))
        channels[RCChannel.YAW] = max(RC_MIN, min(RC_MAX, yaw))
        channels[RCChannel.ARM] = RC_MAX

        return channels

    def on_parameter_changed(self, name: str, value: Any) -> None:
        log.info("Parameter changed: {} = {}", name, value)
        if name == "altitude.kp":
            self.alt_pid.kp = value
        elif name == "altitude.ki":
            self.alt_pid.ki = value
        elif name == "altitude.kd":
            self.alt_pid.kd = value
        elif name == "altitude.output_limits":
            self.alt_pid.set_output_limits(value)
        elif name == "hover_yaw.yaw_rate":
            self.yaw_rate = value
        elif name == "betaflight_yaw_rate_full_stick_dps":
            self.yaw_stick_range = value
            self.rc_mapper.yaw_rate_full_stick_dps = value

    def on_state_changed(self, state: State) -> None:
        log.info("State changed: {}", state)
        self.enable = state in [State.SEARCH]
