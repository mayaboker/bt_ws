from enum import IntEnum, auto, StrEnum
from bt_app.common.event import Event
from bt_app.common.mavlink import MavSeverity

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

NO_RC_CHANNELS = 8

class JoyInterrupt(StrEnum):
    TAKEOFF_REQUEST = "takeoff_request"
    MANUAL_REQUEST = "manual_request"


class InternalJoy(IntEnum):
    """
        roll, pitch, throttle, yaw
    """
    ROLL= 0
    PITCH = auto()
    THROTTLE = auto()
    YAW = auto()
    ARM = auto() # SE(4)
    MANUAL = auto() # SA(5)
    AUTO_TAKE_OFF = auto() # SD(6)

class AETR1234(IntEnum):
    """
    roll, pitch, throttle, yaw
    """
    ROLL= 0
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

class RobotState(IntEnum):
    IDLE = 0
    MANUAL = 1
    RECOVERY = 3
    FAILSAFE = 4
    TAKEOFF = 5
    ARM = 6
    ALT_HOLD = 7


def print_channels(channels: list[int]):
    """
    print rc channels
    """
    if not channels:
        return

    for index, channel in enumerate(AETR1234):
        if index >= len(channels):
            break
        print(f"{channel.name}: {channels[index]}")

    aux_count = sum(1 for channel in AETR1234 if channel.name.startswith("AUX"))
    for extra_index, channel_value in enumerate(channels[len(AETR1234):], start=aux_count + 1):
        print(f"AUX{extra_index}: {channel_value}")


__all__ = [
    "FREQ_HZ",
    "TREE_TICK_INTERVAL_S",
    "Event",
    "MavSeverity",
    "GAZEBO_CAMERA_TOPIC",
    "GAZEBO_ULTRASONIC_LIDAR_TOPIC",
    "ZMQ_CAMERA_ENDPOINT",
    "ZMQ_CAMERA_TOPIC",
    "ZMQ_ULTRASONIC_LIDAR_ENDPOINT",
    "ZMQ_ULTRASONIC_LIDAR_TOPIC",
    "ZMQ_TRACKER_RESULT_ENDPOINT",
    "ZMQ_TRACKER_RESULT_TOPIC",
    "RobotState"
]
