import math
import msgpack
import threading
import time
from dataclasses import dataclass
from typing import Any
import zmq
from loguru import logger as log
from bt_app.msgs import RCChannels
from bt_app.parameters import Parameters
from bt_app.control.rc_mapper import BetaflightRcMapper, clamp
from bt_app.parameters.generated import ParameterKey

DEFAULT_VISUAL_ZMQ_ENDPOINT = "tcp://127.0.0.1:5556"

VISUAL_TRACKER_PARAMETERS = {
    ParameterKey.VIS_HOV_THR: "hover_throttle",
    ParameterKey.VIS_FWD_PITCH: "forward_pitch_deg",
    ParameterKey.VIS_MAX_PITCH: "max_pitch_deg",
    ParameterKey.VIS_MAX_THR: "max_throttle",
    ParameterKey.VIS_KP_YAW: "kp_yaw",
    ParameterKey.VIS_MAX_YAW: "max_yaw_rate_dps",
    ParameterKey.VIS_KP_PITCH: "kp_pitch_y",
    ParameterKey.VIS_KP_THR: "kp_throttle_y",
    ParameterKey.BF_YAW_RATE: "betaflight_yaw_rate_full_stick_dps",
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

@dataclass(frozen=True)
class VisualDetectionMessage:
    frame_id: int
    timestamp_ns: int | None
    found: bool
    x: int
    y: int
    width: int
    height: int
    locked: bool = False
    lock_found_frames: int = 0
    lock_missing_frames: int = 0


def decode_visual_detection(payload: bytes) -> VisualDetectionMessage | None:
    data = msgpack.unpackb(payload, raw=False, strict_map_key=False)
    if not isinstance(data, dict):
        raise ValueError("visual telemetry payload must decode to a map")
    if data.get("type") != "red-detection":
        return None
    timestamp_ns = data["timestamp_ns"]
    return VisualDetectionMessage(
        frame_id=int(data["frame_id"]),
        timestamp_ns=None if timestamp_ns is None else int(timestamp_ns),
        found=bool(data["found"]),
        x=int(data["x"]),
        y=int(data["y"]),
        width=int(data["width"]),
        height=int(data["height"]),
        locked=bool(data.get("locked", False)),
        lock_found_frames=int(data.get("lock_found_frames", 0)),
        lock_missing_frames=int(data.get("lock_missing_frames", 0)),
    )


class VisualTargetComm:
    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_VISUAL_ZMQ_ENDPOINT,
        context=None,
        on_result=None,
        poll_timeout_ms: int = 50,
    ):
        self.endpoint = endpoint
        self.context = context or zmq.Context.instance()
        self.on_result = on_result
        self.poll_timeout_ms = poll_timeout_ms

        self._stop_event = threading.Event()
        self._thread = None
        self._socket = None


    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        print("Starting visual target comm thread...------------------------------------------------")
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
        socket.setsockopt(zmq.SUBSCRIBE, b"")
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
                        payload = socket.recv(flags=zmq.NOBLOCK)
                    except zmq.Again:
                        break
                    except zmq.ZMQError:
                        return
                    try:
                        candidate = decode_visual_detection(payload)
                    except (
                        KeyError,
                        TypeError,
                        ValueError,
                        msgpack.exceptions.UnpackException,
                    ) as exc:
                        log.warning("Ignored invalid visual telemetry: {}", exc)
                        continue
                    if candidate is not None:
                        result = candidate
                if result is not None and self.on_result is not None:
                    self.on_result(result)
        finally:
            self._close_socket()

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
    deadband_normalized: float = 0.02

    # X error -> yaw
    kp_yaw: float = 3.0               # deg/s yaw per deg image error
    kd_yaw: float = 0.0
    max_yaw_rate_dps: float = 15.0

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
    # Positive image X means the target is to the camera's right. This vehicle
    # uses RC yaw > 1500 to turn right, matching PRE_TRACKING acquisition.
    yaw_sign: float = 1.0
    pitch_y_sign: float = 1.0
    throttle_y_sign: float = 1.0

    # -------------------------
    # RC output conversion
    # -------------------------
    betaflight_angle_limit_deg: float = 60.0
    betaflight_yaw_rate_full_stick_dps: float = 67.0

    rc_roll_sign: float = 1.0
    # The Gazebo/Betaflight vehicle maps RC pitch above 1500 to the physical
    # forward direction, while the controller uses negative pitch as its
    # forward semantic convention.
    rc_pitch_sign: float = -1.0
    rc_yaw_sign: float = 1.0


class VisualTargetController:
    def __init__(self, cfg: ControllerConfig):
        self.cfg = cfg
        self.prev_ex = None
        self.prev_ey = None
        self.last_time = None
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

    def update(self, error_x, error_y, target_visible=True):
        """
        Inputs:
            error_x:
                Normalized horizontal image error in [-1, 1].
                Positive means the target is right of image center.

            error_y:
                Normalized vertical image error in [-1, 1].
                Positive means the target is above image center.

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
        ex = apply_deadband(error_x, cfg.deadband_normalized)
        ey = apply_deadband(error_y, cfg.deadband_normalized)

        # Derivatives, optional
        if self.prev_ex is None or self.prev_ey is None or self.last_time is None:
            dt = 0.0
            ey_dot = 0.0
        else:
            dt = now - self.last_time
            if dt > 0.0:
                ey_dot = (ey - self.prev_ey) / dt
            else:
                ey_dot = 0.0

        self.prev_ex = ex
        self.prev_ey = ey
        self.last_time = now

        # --------------------------------------------------
        # 1. Horizontal image error controls yaw
        # --------------------------------------------------
        yaw_rate_dps = clamp(
            cfg.yaw_sign * cfg.kp_yaw * ex,
            -cfg.max_yaw_rate_dps,
            cfg.max_yaw_rate_dps,
        )

        # --------------------------------------------------
        # 2. Vertical image error gives small pitch correction
        # --------------------------------------------------
        # This POC intentionally monitors vertical image error without using it
        # for flight control. ALT_HOLD owns the vertical axis.
        pitch_deg = cfg.forward_pitch_deg

        pitch_deg = clamp(
            pitch_deg,
            -cfg.max_pitch_deg,
            cfg.max_pitch_deg,
        )
        log.trace("visual pitch command={:.2f}", pitch_deg)
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

@dataclass(frozen=True)
class VisualObservation:
    detection: VisualDetectionMessage
    error_x: float
    error_y: float
    command: RCChannels


class VisualTrackerObserver:
    def __init__(
        self,
        params: Parameters,
        *,
        endpoint: str = DEFAULT_VISUAL_ZMQ_ENDPOINT,
        image_width: int = 640,
        image_height: int = 480,
        print_rate_hz: float = 2.0,
        context=None,
        clock=time.monotonic,
    ):
        self.params = params
        self.cfg = self.build_config(params)
        self.controller = VisualTargetController(self.cfg)
        self.image_width = image_width
        self.image_height = image_height
        self.print_period_s = 1.0 / print_rate_hz
        self._clock = clock
        self._last_printed_at = float("-inf")
        self._last_found: bool | None = None
        self._observation_lock = threading.Lock()
        self._latest_observation: VisualObservation | None = None
        self._latest_received_at = float("-inf")
        self.comm = VisualTargetComm(endpoint=endpoint, context=context)
        self.comm.on_result = self.resolve
        self.params.on_parameter_changed.subscribe(self.on_parameter_changed)

    def start(self):
        self.comm.start()
        log.info(
            "Visual observer subscribed endpoint={} image={}x{} print_rate_hz={:.2f}",
            self.comm.endpoint,
            self.image_width,
            self.image_height,
            1.0 / self.print_period_s,
        )

    def stop(self, timeout=2.0):
        self.comm.stop(timeout=timeout)

    def state(self):
        """Return whether the observer thread is running."""
        return self.comm._thread is not None and self.comm._thread.is_alive()
    
    def build_config(self, params: Parameters) -> ControllerConfig:
        return ControllerConfig(
            hover_throttle=params.get(ParameterKey.VIS_HOV_THR),
            forward_pitch_deg=params.get(ParameterKey.VIS_FWD_PITCH),
            max_pitch_deg=params.get(ParameterKey.VIS_MAX_PITCH),
            max_throttle=params.get(ParameterKey.VIS_MAX_THR),
            kp_yaw=params.get(ParameterKey.VIS_KP_YAW),
            max_yaw_rate_dps=params.get(ParameterKey.VIS_MAX_YAW),
            kp_pitch_y=params.get(ParameterKey.VIS_KP_PITCH),
            kp_throttle_y=params.get(ParameterKey.VIS_KP_THR),
            betaflight_yaw_rate_full_stick_dps=params.get(
                ParameterKey.BF_YAW_RATE
            ),
        )

    def on_parameter_changed(self, name: str, value: Any) -> None:
        field_name = VISUAL_TRACKER_PARAMETERS.get(name)
        if field_name is None:
            return

        self.controller.update_config(field_name, value)

    def resolve(self, detection: VisualDetectionMessage) -> VisualObservation:
        received_at = self._clock()
        error_x, error_y = normalized_target_error(
            detection,
            image_width=self.image_width,
            image_height=self.image_height,
        )
        command = self.controller.update(
            error_x=error_x,
            error_y=error_y,
            target_visible=detection.found,
        )
        observation = VisualObservation(detection, error_x, error_y, command)
        with self._observation_lock:
            self._latest_observation = observation
            self._latest_received_at = received_at
        if self._should_print(detection.found, now=received_at):
            self._print_observation(observation)
        return observation

    def latest_received_at(self) -> float:
        with self._observation_lock:
            return self._latest_received_at

    def is_healthy(self, timeout_s: float, *, now: float | None = None) -> bool:
        current = self._clock() if now is None else now
        return current - self.latest_received_at() <= timeout_s

    def fresh_observation(
        self,
        *,
        received_after: float,
        max_age_s: float,
        now: float | None = None,
    ) -> VisualObservation | None:
        current = self._clock() if now is None else now
        with self._observation_lock:
            if self._latest_received_at <= received_after:
                return None
            if current - self._latest_received_at > max_age_s:
                return None
            return self._latest_observation

    def _should_print(self, found: bool, *, now: float | None = None) -> bool:
        now = self._clock() if now is None else now
        state_changed = self._last_found is None or found != self._last_found
        due = now - self._last_printed_at >= self.print_period_s
        self._last_found = found
        if not state_changed and not due:
            return False
        self._last_printed_at = now
        return True

    @staticmethod
    def _print_observation(observation: VisualObservation) -> None:
        detection = observation.detection
        command = observation.command
        log.info(
            "visual frame={} found={} locked={} lock_frames=({},{}) "
            "bbox=({}, {}, {}, {}) error=({:+.3f}, {:+.3f}) "
            "requested_rc=(pitch={} yaw={})",
            detection.frame_id,
            detection.found,
            detection.locked,
            detection.lock_found_frames,
            detection.lock_missing_frames,
            detection.x,
            detection.y,
            detection.width,
            detection.height,
            observation.error_x,
            observation.error_y,
            command.pitch,
            command.yaw,
        )


def normalized_target_error(
    detection: VisualDetectionMessage,
    *,
    image_width: int,
    image_height: int,
) -> tuple[float, float]:
    if not detection.found:
        return 0.0, 0.0
    center_x = detection.x + detection.width / 2.0
    center_y = detection.y + detection.height / 2.0
    error_x = (center_x - image_width / 2.0) / (image_width / 2.0)
    error_y = (image_height / 2.0 - center_y) / (image_height / 2.0)
    return clamp(error_x, -1.0, 1.0), clamp(error_y, -1.0, 1.0)
