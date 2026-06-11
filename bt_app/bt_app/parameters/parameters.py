from __future__ import annotations

from pathlib import Path
import threading
from typing import Any

from loguru import logger

from bt_app.parameters.models import ParameterLimits
from bt_app.parameters.service import ParameterService
from bt_app.parameters.storage import ParameterStorage
from bt_app.parameters.zmq_server import ZmqParameterServer


class Parameters:
    def __init__(
        self,
        yaml_path: str | Path | None = None,
        endpoint: str = "tcp://127.0.0.1:5555",
    ) -> None:
        if yaml_path is None:
            storage = ParameterStorage({})
        else:
            logger.info(f"Loading parameters from {yaml_path}")
            storage = ParameterStorage.from_yaml(yaml_path)

        self.service = ParameterService(storage)
        self.server = ZmqParameterServer(self.service, endpoint)
        self._server_thread: threading.Thread | None = None
        self.on_parameter_changed = self.service.on_parameter_changed
        self.__start()
        
    def declare(
        self,
        name: str,
        default: Any,
        limits: ParameterLimits | dict[str, Any] | None = None,
        value_type: type | str | None = None,
    ) -> Any:
        return self.service.declare(name, default, limits, value_type)

    def get(self, name: str) -> Any:
        return self.service.get(name)

    def set(self, name: str, value: Any) -> Any:
        return self.service.set(name, value)

    def list(self, full: bool = False) -> list[str] | list[dict[str, Any]]:
        return self.service.list(full=full)

    def dump(self) -> str:
        return self.service.dump()

    def dump_values(self) -> dict[str, Any]:
        return self.service.dump_values()

    def save(self) -> str:
        return self.service.save()

    def describe(self) -> dict[str, dict[str, Any]]:
        return self.service.describe()

    def __start(self) -> None:
        if self._server_thread is not None and self._server_thread.is_alive():
            return

        self._server_thread = threading.Thread(
            target=self.server.start,
            name="parameter-zmq-server",
            daemon=True,
        )
        self._server_thread.start()

    def stop(self, timeout: float | None = 2.0) -> None:
        self.server.stop()
        if self._server_thread is not None:
            self._server_thread.join(timeout=timeout)
            self._server_thread = None
