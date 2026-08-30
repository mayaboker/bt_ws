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
    gcs_ip: str = field(default="127.0.0.1")
    gcs_port: int = field(default=14550)
    debug_mode: bool = field(default=False)
    blackbox_enabled: bool = field(default=False)
    blackbox_directory: str = field(default="logs/blackbox")
    blackbox_chunk_duration_s: float = field(default=5.0)
    blackbox_queue_size: int = field(default=1000)
    config_name: str = field(default="parameters.yaml")
    log_level: str = field(default="INFO")
    visual_zmq_endpoint: str = field(default="tcp://127.0.0.1:5556")
    selector_zmq_endpoint: str = field(default="tcp://127.0.0.1:5557")
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
