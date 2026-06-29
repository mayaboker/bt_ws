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