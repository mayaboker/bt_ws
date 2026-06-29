from enum import Enum, IntEnum, auto
from bt_app.common.event import Event

TREE_TICK_INTERVAL_S = 0.1
FREQ_HZ = 50.0
GAZEBO_CAMERA_TOPIC = "/camera"
GAZEBO_ULTRASONIC_LIDAR_TOPIC = "/ultrasonic_lidar"
ZMQ_CAMERA_ENDPOINT = "ipc:///tmp/bt_app.camera"
ZMQ_CAMERA_TOPIC = b"camera.image"
ZMQ_ULTRASONIC_LIDAR_ENDPOINT = "ipc:///tmp/bt_app.ultrasonic_lidar"
ZMQ_ULTRASONIC_LIDAR_TOPIC = b"ultrasonic_lidar.scan"
ZMQ_TRACKER_RESULT_ENDPOINT = "ipc:///tmp/bt_app.tracker_result"
ZMQ_TRACKER_RESULT_TOPIC = b"tracker_result"

class AETR1234(IntEnum):
    """
    roll, pitch, throttle, yaw
    """
    ROLL= auto()
    PITCH = auto()
    THROTTLE = auto()
    YAW = auto()
    AUX1 = auto()
    AUX2 = auto()
    AUX3 = auto()
    AUX4 = auto()
    AUX5 = auto()
    AUX6 = auto()
    AUX7 = auto()

class RobotState(Enum):
    IDLE = "IDLE"
    MANUAL = "MANUAL"
    TRACKING = "TRACKING"
    RECOVERY = "RECOVERY"
    FAILSAFE = "FAILSAFE"
    TAKEOFF = "TAKEOFF"
    ARM = "ARM"

__all__ = [
    "FREQ_HZ",
    "TREE_TICK_INTERVAL_S",
    "Event",
    "GAZEBO_CAMERA_TOPIC",
    "GAZEBO_ULTRASONIC_LIDAR_TOPIC",
    "ZMQ_CAMERA_ENDPOINT",
    "ZMQ_CAMERA_TOPIC",
    "ZMQ_ULTRASONIC_LIDAR_ENDPOINT",
    "ZMQ_ULTRASONIC_LIDAR_TOPIC",
    "ZMQ_TRACKER_RESULT_ENDPOINT",
    "ZMQ_TRACKER_RESULT_TOPIC",
    "State"
]
