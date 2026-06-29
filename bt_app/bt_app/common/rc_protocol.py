# plugin_api.py
from typing import Protocol, runtime_checkable, Any
from bt_app.msgs import RCChannels

@runtime_checkable
class RCProtocol(Protocol):
    name: str

    def update(self) -> RCChannels:
        ...