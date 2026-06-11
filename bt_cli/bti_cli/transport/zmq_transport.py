from __future__ import annotations

from typing import Any

import zmq


class ZmqTransportError(RuntimeError):
    """Raised when the remote endpoint returns an error response."""


class ZmqTransportTimeout(TimeoutError):
    """Raised when the remote endpoint does not reply before the timeout."""


class ZmqRequestResponseTransport:
    def __init__(self, endpoint: str, timeout_ms: int = 3000) -> None:
        self.endpoint = endpoint
        self.timeout_ms = timeout_ms
        self._context = zmq.Context.instance()

    def request(self, action: str, params: dict[str, Any] | None = None) -> Any:
        message = {
            "namespace": "param",
            "action": action,
            "params": params or {},
        }
        return self.send(message)

    def send(self, message: dict[str, Any]) -> Any:
        socket = self._context.socket(zmq.REQ)
        socket.setsockopt(zmq.LINGER, 0)
        socket.connect(self.endpoint)

        try:
            socket.send_json(message)

            if socket.poll(self.timeout_ms) == 0:
                raise ZmqTransportTimeout(
                    f"No response from {self.endpoint} after {self.timeout_ms} ms"
                )

            response = socket.recv_json()
        finally:
            socket.close()

        if not response.get("ok", False):
            error = response.get("error", "Remote command failed")
            raise ZmqTransportError(str(error))

        return response.get("result")
