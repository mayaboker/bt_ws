"""ZMQ adapter for tracker requests and telemetry."""

from typing import Protocol

from loguru import logger

from bt_gst.zmq_models import (
    TrackRequest,
    TrackerDataMessage,
    TrackerDebugMessage,
    decode_request,
    encode_message,
)

DEFAULT_REQUEST_ENDPOINT = "tcp://127.0.0.1:5555"
DEFAULT_TELEMETRY_ENDPOINT = "tcp://127.0.0.1:5556"


class TrackerIoAdapter(Protocol):
    def poll_latest_request(self) -> TrackRequest | None:
        """Return the newest pending request, dropping older pending requests."""

    def publish_tracker_data(self, message: TrackerDataMessage) -> None:
        """Publish tracker metadata without blocking."""

    def publish_tracker_debug(self, message: TrackerDebugMessage) -> None:
        """Publish tracker debug data without blocking."""

    def close(self) -> None:
        """Release transport resources."""


class NullTrackerIoAdapter:
    def poll_latest_request(self) -> TrackRequest | None:
        return None

    def publish_tracker_data(self, message: TrackerDataMessage) -> None:
        return

    def publish_tracker_debug(self, message: TrackerDebugMessage) -> None:
        return

    def close(self) -> None:
        return


class ZmqTrackerIoAdapter:
    def __init__(
        self,
        request_endpoint: str = DEFAULT_REQUEST_ENDPOINT,
        telemetry_endpoint: str = DEFAULT_TELEMETRY_ENDPOINT,
        *,
        bind: bool = True,
        context: object | None = None,
    ) -> None:
        import zmq

        self._zmq = zmq
        self._context = context if context is not None else zmq.Context()
        self._owns_context = context is None
        self._request_socket = self._context.socket(zmq.SUB)
        self._telemetry_socket = self._context.socket(zmq.PUB)

        self._request_socket.setsockopt(zmq.LINGER, 0)
        self._request_socket.setsockopt(zmq.RCVHWM, 10)
        self._request_socket.setsockopt(zmq.SUBSCRIBE, b"")

        self._telemetry_socket.setsockopt(zmq.LINGER, 0)
        self._telemetry_socket.setsockopt(zmq.SNDHWM, 1)

        if bind:
            self._request_socket.bind(request_endpoint)
            self._telemetry_socket.bind(telemetry_endpoint)
        else:
            self._request_socket.connect(request_endpoint)
            self._telemetry_socket.connect(telemetry_endpoint)

    def poll_latest_request(self) -> TrackRequest | None:
        latest_request = None
        while True:
            try:
                payload = self._request_socket.recv(flags=self._zmq.NOBLOCK)
            except self._zmq.Again:
                return latest_request

            try:
                latest_request = decode_request(payload)
            except (KeyError, TypeError, ValueError, self._zmq.ZMQError) as exc:
                logger.warning("ignored invalid tracker request reason={}", exc)

    def publish_tracker_data(self, message: TrackerDataMessage) -> None:
        self._publish(message)

    def publish_tracker_debug(self, message: TrackerDebugMessage) -> None:
        self._publish(message)

    def close(self) -> None:
        self._request_socket.close(linger=0)
        self._telemetry_socket.close(linger=0)
        if self._owns_context:
            self._context.term()

    def _publish(self, message: TrackerDataMessage | TrackerDebugMessage) -> None:
        try:
            self._telemetry_socket.send(encode_message(message), flags=self._zmq.NOBLOCK)
        except self._zmq.Again:
            logger.debug("dropped tracker telemetry reason=send-would-block")
