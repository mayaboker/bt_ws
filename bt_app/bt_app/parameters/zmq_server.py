from __future__ import annotations

import json
from typing import Any

import zmq
from loguru import logger
from bt_app.parameters.service import ParameterService


class ZmqParameterServer:
    def __init__(self, parameter_service: ParameterService, endpoint: str) -> None:
        self._parameter_service = parameter_service
        self._endpoint = endpoint
        self._context = zmq.Context.instance()
        self._socket: zmq.Socket | None = None
        self._running = False
        self._poll_timeout_ms = 100

    @property
    def endpoint(self) -> str:
        return self._endpoint

    def start(self) -> None:
        if self._running:
            return

        self._socket = self._context.socket(zmq.REP)
        self._socket.setsockopt(zmq.LINGER, 0)
        self._socket.bind(self._endpoint)
        self._running = True

        logger.info(f"Parameter ZMQ server listening on {self._endpoint}")

        try:
            while self._running:
                if self._socket.poll(self._poll_timeout_ms) == 0:
                    continue
                request = self._socket.recv_json()
                response = self.handle_request(request)
                self._socket.send_json(response)
        except zmq.ZMQError as exc:
            if self._running:
                raise exc
        finally:
            self.stop()

    def stop(self) -> None:
        self._running = False
        if self._socket is not None:
            self._socket.close(linger=0)
            self._socket = None

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            namespace = request.get("namespace")
            action = request.get("action")
            params = request.get("params") or {}

            if namespace != "param":
                return {"ok": False, "error": f"Unsupported namespace: {namespace}"}

            if not isinstance(params, dict):
                return {"ok": False, "error": "Request params must be an object"}

            result = self._execute(action, params)
            return {"ok": True, "result": result}
        except (KeyError, TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def _execute(self, action: str, params: dict[str, Any]) -> Any:
        if action == "list":
            return self._parameter_service.list(full=bool(params.get("full", False)))

        if action == "dump":
            return self._parameter_service.dump()

        if action == "save":
            return self._parameter_service.save()

        if action == "describe":
            return self._parameter_service.describe()

        if action == "get":
            name = params.get("name")
            if not name:
                raise ValueError("Missing parameter name")
            return self._parameter_service.get(str(name))

        if action == "set":
            name = params.get("name")
            if not name:
                raise ValueError("Missing parameter name")

            return {
                "name": name,
                "value": self._parameter_service.set(
                    str(name),
                    self._parse_value(params.get("value")),
                ),
            }

        raise ValueError(f"Unsupported param action: {action}")

    def _parse_value(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value

        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
