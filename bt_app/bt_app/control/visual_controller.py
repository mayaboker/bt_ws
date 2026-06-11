import math
import threading
import time
from dataclasses import dataclass
from typing import Any
import zmq
from loguru import logger as log
from bt_app.common import ZMQ_TRACKER_RESULT_ENDPOINT, ZMQ_TRACKER_RESULT_TOPIC
from bt_app.msgs import TrackerResult, TrackerState, RCChannels, unpack_tracker_result
from bt_app.msp.command_dispatcher import MspCommandDispatcher
from bt_app.parameters import Parameters
from bt_app.context import Context
from bt_app.common import State
from bt_app import FREQ_HZ
from bt_app.control import PID
from bt_app.control.rc_mapper import BetaflightRcMapper, clamp

VISUAL_TRACKER_PARAMETERS = {
    "visual.hover_throttle": "hover_throttle",
    "visual.forward_pitch_deg": "forward_pitch_deg",
    "visual.max_pitch_deg": "max_pitch_deg",
    "visual.max_throttle": "max_throttle",
    "visual.kp_yaw": "kp_yaw",
    "visual.kp_pitch_y": "kp_pitch_y",
    "visual.kp_throttle_y": "kp_throttle_y",
    "betaflight_yaw_rate_full_stick_dps": "betaflight_yaw_rate_full_stick_dps",
}

# region Utility functions



def cosd(deg):
    return math.cos(math.radians(deg))


def apply_deadband(x, deadband):
    """
    Removes small camera noise around zero.
    """
    if abs(x) < deadband:
        return 0.0

    if x > 0:
        return x - deadband
    else:
        return x + deadband
#endregion

class VisualTargetComm:
    def __init__(
        self,
        *,
        endpoint=ZMQ_TRACKER_RESULT_ENDPOINT,
        topic=ZMQ_TRACKER_RESULT_TOPIC,
        context=None,
        on_result=None,
        poll_timeout_ms=50,
    ):
        self.endpoint = endpoint
        self.topic = topic
        self.context = context or zmq.Context.instance()
        self.on_result = on_result
        self.poll_timeout_ms = poll_timeout_ms

        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        self._socket = None
        self.on_result = None


    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._receive_loop,
            name="visual-target-zmq",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout=2.0):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if not self._thread.is_alive():
                self._thread = None

    

    def _receive_loop(self):
        socket = self.context.socket(zmq.SUB)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.RCVHWM, 1)
        socket.setsockopt(zmq.SUBSCRIBE, self.topic)
        socket.connect(self.endpoint)
        self._socket = socket

        poller = zmq.Poller()
        poller.register(socket, zmq.POLLIN)

        try:
            while not self._stop_event.is_set():
                if not poller.poll(self.poll_timeout_ms):
                    continue

                result = None
                while True:
                    try:
                        _topic, payload = socket.recv_multipart(flags=zmq.NOBLOCK)
                    except zmq.Again:
                        break
                    except zmq.ZMQError:
                        return
                    result = self._decode_result(payload)
                    if self.on_result is not None:
                        self.on_result(result)
        finally:
            self._close_socket()



    @staticmethod
    def _decode_result(payload):
        return unpack_tracker_result(payload)

    def _close_socket(self):
        socket = self._socket
        self._socket = None
        if socket is not None:
            socket.close(linger=0)


@dataclass
class ControllerConfig:
    # -------------------------
    # Drone / throttle settings
    # -------------------------
    hover_throttle: float = 0.45      # throttle needed to hover, 0.0 to 1.0
    min_throttle: float = 0.20
    max_throttle: float = 0.85

    # -------------------------
    # Forward speed command
    # -------------------------
    # Negative pitch = nose down = fly forward.
    # Increase magnitude for faster tracking.
    forward_pitch_deg: float = -30.0

    max_pitch_deg: float = 100.0
    max_roll_deg: float = 10.0

    # -------------------------
    # Camera-error controller
    # -------------------------
    deadband_deg: float = 0.5

    # X error -> yaw
    kp_yaw: float = 3.0               # deg/s yaw per deg image error
    kd_yaw: float = 0.0
    max_yaw_rate_dps: float = 90.0

    # Y error -> small pitch correction
    kp_pitch_y: float = 100          # deg pitch per deg image error
    kd_pitch_y: float = 0.0
    max_visual_pitch_deg: float = 100.0

    # Y error -> throttle correction
    kp_throttle_y: float = 0.006      # throttle per deg image error
    kd_throttle_y: float = 0.0
    max_throttle_y_correction: float = 0.10

    # -------------------------
    # Sign corrections
    # Change these if the drone moves the wrong way.
    # -------------------------
    yaw_sign: float = -1.0
    pitch_y_sign: float = 1.0
    throttle_y_sign: float = 1.0

    # -------------------------
    # RC output conversion
    # -------------------------
    betaflight_angle_limit_deg: float = 60.0
    betaflight_yaw_rate_full_stick_dps: float = 67.0

    rc_roll_sign: float = 1.0
    rc_pitch_sign: float = -1.0
    rc_yaw_sign: float = 1.0


class VisualTargetController:
    def __init__(self, cfg: ControllerConfig):
        self.cfg = cfg
        self.prev_ex = None
        self.prev_ey = None
        self.last_time = None
        self.yaw_pid = PID(kp=cfg.kp_yaw, 
                           ki=0, 
                           kd=cfg.kd_yaw, 
                           output_limits=(-cfg.max_yaw_rate_dps, cfg.max_yaw_rate_dps))
        self.rc_mapper = BetaflightRcMapper(
            yaw_rate_full_stick_dps=cfg.betaflight_yaw_rate_full_stick_dps,
            yaw_sign=cfg.rc_yaw_sign,
        )

    def update_config(self, field_name: str, value: Any) -> None:
        setattr(self.cfg, field_name, value)
        if field_name == "betaflight_yaw_rate_full_stick_dps":
            self.rc_mapper.yaw_rate_full_stick_dps = value
        elif field_name == "rc_yaw_sign":
            self.rc_mapper.yaw_sign = value

    def reset(self):
        self.prev_ex = None
        self.prev_ey = None
        self.last_time = None

    def update(self, error_x_deg, error_y_deg, target_visible=True):
        """
        Inputs:
            error_x_deg:
                Camera horizontal angle error.
                Positive = target is right of image center.

            error_y_deg:
                Camera vertical angle error.
                Positive = target is above image center.

            target_visible:
                If False, controller returns neutral roll/pitch/yaw and hover throttle.

        Returns:
            ControlOutput with roll, pitch, yaw rate, throttle and RC-style commands.
        """

        cfg = self.cfg
        now = time.monotonic()

        if not target_visible:
            self.reset()
            return self._make_output(
                roll_deg=0.0,
                pitch_deg=0.0,
                yaw_rate_dps=0.0,
                throttle=cfg.hover_throttle,
            )

        # Apply deadband to reduce jitter near image center
        ex = apply_deadband(error_x_deg, cfg.deadband_deg)
        ey = apply_deadband(error_y_deg, cfg.deadband_deg)

        # Derivatives, optional
        if self.prev_ex is None or self.prev_ey is None or self.last_time is None:
            dt = 0.0
            ex_dot = 0.0
            ey_dot = 0.0
        else:
            dt = now - self.last_time
            if dt > 0.0:
                ex_dot = (ex - self.prev_ex) / dt
                ey_dot = (ey - self.prev_ey) / dt
            else:
                ex_dot = 0.0
                ey_dot = 0.0

        self.prev_ex = ex
        self.prev_ey = ey
        self.last_time = now

        # --------------------------------------------------
        # 1. Horizontal image error controls yaw
        # --------------------------------------------------
        # yaw_rate_dps = cfg.yaw_sign * (
        #     cfg.kp_yaw * ex + cfg.kd_yaw * ex_dot
        # )

        # yaw_rate_dps = clamp(
        #     yaw_rate_dps,
        #     -cfg.max_yaw_rate_dps,
        #     cfg.max_yaw_rate_dps,
        # )
        yaw_rate_dps = self.yaw_pid.update(0, ex)
        yaw_rate_dps *= cfg.yaw_sign

        # --------------------------------------------------
        # 2. Vertical image error gives small pitch correction
        # --------------------------------------------------
        pitch_visual_deg = cfg.pitch_y_sign * (
            cfg.kp_pitch_y * ey + cfg.kd_pitch_y * ey_dot
        )

        pitch_visual_deg = clamp(
            pitch_visual_deg,
            -cfg.max_visual_pitch_deg,
            cfg.max_visual_pitch_deg,
        )

        # Main pitch command:
        # negative pitch = nose down = move forward
        pitch_deg = cfg.forward_pitch_deg + pitch_visual_deg

        pitch_deg = clamp(
            pitch_deg,
            -cfg.max_pitch_deg,
            cfg.max_pitch_deg,
        )
        log.info(f"pitch_command={pitch_deg:.2f} ")
        # For this forward-camera controller, roll is not used.
        # Horizontal centering is done with yaw.
        roll_deg = 0.0

        # --------------------------------------------------
        # 3. Feed-forward throttle compensation for pitch/roll
        # --------------------------------------------------
        # When the drone tilts, only part of the thrust points upward.
        # Approximate compensation:
        #
        # throttle_ff = hover_throttle / (cos(roll) * cos(pitch))
        #
        # This is the important part that prevents altitude loss
        # when pitching forward.
        denom = cosd(roll_deg) * cosd(pitch_deg)
        denom = max(denom, 0.35)  # safety against extreme tilt

        throttle_ff = cfg.hover_throttle / denom

        # --------------------------------------------------
        # 4. Extra throttle from vertical image error
        # --------------------------------------------------
        # Positive ey = target above center.
        # Usually this means add throttle / climb.
        # If the target moves the wrong way, change throttle_y_sign to -1.
        throttle_y = cfg.throttle_y_sign * (
            cfg.kp_throttle_y * ey + cfg.kd_throttle_y * ey_dot
        )

        throttle_y = clamp(
            throttle_y,
            -cfg.max_throttle_y_correction,
            cfg.max_throttle_y_correction,
        )

        throttle = throttle_ff + throttle_y

        throttle = clamp(
            throttle,
            cfg.min_throttle,
            cfg.max_throttle,
        )

        return self._make_output(
            roll_deg=roll_deg,
            pitch_deg=pitch_deg,
            yaw_rate_dps=yaw_rate_dps,
            throttle=throttle,
        )

    def _make_output(self, roll_deg, pitch_deg, yaw_rate_dps, throttle):
        """
        Converts physical commands into Betaflight-like RC values.

        RC outputs:
            roll/pitch/yaw: 1000 to 2000, center 1500
            throttle:       1000 to 2000
        """

        cfg = self.cfg

        roll_norm = clamp(
            roll_deg / cfg.betaflight_angle_limit_deg,
            -1.0,
            1.0,
        )

        pitch_norm = clamp(
            pitch_deg / cfg.betaflight_angle_limit_deg,
            -1.0,
            1.0,
        )

        rc_roll = int(round(1500 + cfg.rc_roll_sign * 500 * roll_norm))
        rc_pitch = int(round(1500 + cfg.rc_pitch_sign * 500 * pitch_norm))
        rc_yaw = self.rc_mapper.yaw_rate_to_rc(yaw_rate_dps)
        rc_throttle = int(round(1000 + 1000 * clamp(throttle, 0.0, 1.0)))

        return RCChannels(
            roll=rc_roll,
            pitch=rc_pitch,
            yaw=rc_yaw,
            throttle=rc_throttle,
            arm=1900,
            angle_mode=1900,
            aux3=1000,
            aux4=1000,
        )

class VisualTrackerManager():
    def __init__(self, context: Context, params: Parameters):
        self.ctx = context
        self.params = params
        self.cfg = self.build_config(params)
        self.controller = VisualTargetController(self.cfg)
        self.enable = False
        self.comm = VisualTargetComm()
        self.comm.on_result = self.resolve
        self.ctx.on_state_changed += self.on_state_changed
        self.params.on_parameter_changed.subscribe(self.on_parameter_changed)
        
    def on_state_changed(self, state):
        self.enable = state == State.VISUAL_TRACK

    def start(self):
        self.comm.start()

    def stop(self, timeout=2.0):
        self.comm.stop(timeout=timeout)

    def state(self):
        """Returns True if the controller is active and has a recent target."""
        return True
    
    def build_config(self, params: Parameters) -> ControllerConfig:
        return ControllerConfig(
            hover_throttle=params.get("visual.hover_throttle"),
            forward_pitch_deg=params.get("visual.forward_pitch_deg"),
            max_pitch_deg=params.get("visual.max_pitch_deg"),
            max_throttle=params.get("visual.max_throttle"),
            kp_yaw=params.get("visual.kp_yaw"),
            kp_pitch_y=params.get("visual.kp_pitch_y"),
            kp_throttle_y=params.get("visual.kp_throttle_y"),
            betaflight_yaw_rate_full_stick_dps=params.get(
                "betaflight_yaw_rate_full_stick_dps"
            ),
        )

    def on_parameter_changed(self, name: str, value: Any) -> None:
        field_name = VISUAL_TRACKER_PARAMETERS.get(name)
        if field_name is None:
            return

        self.controller.update_config(field_name, value)

    def resolve(self, result: TrackerResult):
        if self.enable is False:
            return
        
        target_visible = result.state == TrackerState.TRACKING and result.score > 0
        cmd_result = self.controller.update(
            error_x_deg=math.degrees(result.error_x),
            error_y_deg=math.degrees(result.error_y),
            target_visible=target_visible,
        )

        self.ctx.msp.set_rc(cmd_result.to_list(), rate_hz=FREQ_HZ)
