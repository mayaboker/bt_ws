from dataclasses import dataclass, field
from enum import Enum

@dataclass
class DroneSink(Enum):
    """
    Enum for the drone sink type.
    """
    SERIAL = 1
    ETHERNET = 2


@dataclass
class VehicleConfig():
    has_external_pilot: bool = field(default=True)
    # FCU connection type serial, ethernet
    drone_sink: int = 2#field(default_factory=lambda: DroneSink.ETHERNET.value)
    drone_eth_host: str = field(default="127.0.0.1")
    drone_eth_port: int = field(default=5761)
    drone_serial_port: str = field(default="/dev/ttyUSB0")
    # gcs
    gcs_ip: str = field(default="127.0.0.1")
    gcs_port: int = field(default=14550)
    # rc diagnostic
    rc_record_enabled: bool = field(default=False)
    rc_record_path: str = field(default="logs/rc_state.csv")
    rc_record_flush_interval_s: float = field(default=1.0)
    rc_record_queue_size: int = field(default=1000)
    # parameters file
    config_name: str = field(default="parameters.yaml")
    # application logging
    log_level: str = field(default="INFO")
    # visual
    visual_observer_enabled: bool = field(default=False)
    visual_zmq_endpoint: str = field(default="tcp://127.0.0.1:5556")

    visual_image_width: int = field(default=640)
    visual_image_height: int = field(default=480)
    visual_camera_fx_px: float = field(default=320.0)
    visual_camera_fy_px: float = field(default=320.0)
    visual_camera_cx_px: float = field(default=320.0)
    visual_camera_cy_px: float = field(default=240.0)
    visual_target_width_m: float = field(default=1.0)
    visual_target_height_m: float = field(default=1.0)
    visual_print_rate_hz: float = field(default=2.0)
    visual_mavlink_rate_hz: float = field(default=20.0)
    tracker_request_endpoint: str = field(default="tcp://127.0.0.1:5555")
    tracker_initial_x: int = field(default=320)
    tracker_initial_y: int = field(default=240)
    tracker_adjust_step_x_px: int = field(default=5)
    tracker_adjust_step_y_px: int = field(default=3)
    tracker_adjust_rate_hz: float = field(default=5.0)
    tracker_adjust_deadband_pwm: int = field(default=100)
    tracker_bridge_health_timeout_s: float = field(default=1.0)
    tracker_result_timeout_s: float = field(default=0.25)
    glide_target_speed_m_s: float = field(default=5.0)
    glide_max_vertical_speed_m_s: float = field(default=3.0)
    glide_center_deadband: float = field(default=0.05)
    glide_center_error_max: float = field(default=0.40)
    glide_lock_frame_count: int = field(default=2)
    glide_commit_depth_m: float = field(default=1.0)
    glide_commit_timeout_s: float = field(default=2.0)
    # glide diagnostic
    glide_log_enabled: bool = field(default=True)
    glide_log_path: str = field(default="logs/glide_control.csv")
    glide_log_flush_interval_s: float = field(default=1.0)
    glide_log_queue_size: int = field(default=3000)

    # region singleton
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._initialized = True
    # endregion
