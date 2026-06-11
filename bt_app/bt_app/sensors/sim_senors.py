import json
import threading

import zmq
from loguru import logger

from bt_app.common import (
    Event,
    ZMQ_ULTRASONIC_LIDAR_ENDPOINT,
    ZMQ_ULTRASONIC_LIDAR_TOPIC,
)


class SimSensors:
    """Subscribe to simulated sensor data and expose it through events."""

    def __init__(
        self,
        *,
        lidar_endpoint=ZMQ_ULTRASONIC_LIDAR_ENDPOINT,
        lidar_topic=ZMQ_ULTRASONIC_LIDAR_TOPIC,
        context=None,
        poll_timeout_ms=50,
    ):
        self.lidar_endpoint = lidar_endpoint
        self.lidar_topic = lidar_topic
        self.zmq_context = context or zmq.Context.instance()
        self.poll_timeout_ms = poll_timeout_ms

        self.on_lidar_range = Event()
        self._stop_event = threading.Event()
        self._thread = None
        self._socket = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._receive_loop,
            name="sim-sensors-zmq",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout=2.0):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if not self._thread.is_alive():
                self._thread = None

    def _receive_loop(self):
        socket = self.zmq_context.socket(zmq.SUB)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.RCVHWM, 1)
        socket.setsockopt(zmq.SUBSCRIBE, self.lidar_topic)
        socket.connect(self.lidar_endpoint)
        self._socket = socket

        poller = zmq.Poller()
        poller.register(socket, zmq.POLLIN)

        logger.info(
            "Sim sensors subscribed to lidar {} on topic {}",
            self.lidar_endpoint,
            self.lidar_topic.decode("utf-8", errors="replace"),
        )

        try:
            while not self._stop_event.is_set():
                if not poller.poll(self.poll_timeout_ms):
                    continue

                metadata, measurement = self._recv_latest_lidar(socket)
                if measurement is None:
                    continue
                self.on_lidar_range.emit(measurement.get("range"), metadata)
        finally:
            self._close_socket()

    def _recv_latest_lidar(self, socket):
        metadata = None
        measurement = None

        while True:
            try:
                _topic, metadata_bytes, measurement_bytes = socket.recv_multipart(
                    flags=zmq.NOBLOCK
                )
            except zmq.Again:
                break
            except zmq.ZMQError:
                raise

            metadata = json.loads(metadata_bytes.decode("utf-8"))
            measurement = json.loads(measurement_bytes.decode("utf-8"))

        return metadata, measurement

    def _close_socket(self):
        socket = self._socket
        self._socket = None
        if socket is not None:
            socket.close(linger=0)
