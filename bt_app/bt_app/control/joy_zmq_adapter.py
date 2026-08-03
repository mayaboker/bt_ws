"""
listen to zmq traffic from joy publisher
- joystick channel
- failsafe

The last RC data saved
The listener run in a separate thread and update vehicle state when failsafe is detected or cancel
"""

from __future__ import annotations
import threading
import msgpack
import zmq
from threading import Thread
import time
from typing import Any
from loguru import logger as log
import queue
from bt_app.common import Event
from bt_app.parameters.generated import ParameterKey

DEFAULT_SERVER_PUB_ENDPOINT = "ipc:///tmp/bt_joy_server_pub.ipc"
DEFAULT_EXTERNAL_PUB_ENDPOINT = "ipc:///tmp/bt_joy_external_pub.ipc"
SUB_STATE_TOPIC = "joystick.state"
SUB_FAILSAFE_TOPIC = "joystick.failsafe"
DEFAULT_SUBSCRIBE_TOPICS = (SUB_STATE_TOPIC, SUB_FAILSAFE_TOPIC)
DEFAULT_PUBLISH_TOPIC = "bt_joy.external"
DEFAULT_PUBLISH_RATE_HZ = 1.0
DEFAULT_MESSAGE = "hello from zmq mock"
FPS = 50.0
NAME = "joy_zmq_adapter"
DEFAULT_SERVER_TIMEOUT_S = 1.0
POLL_TIMEOUT_MS = int(1000 / FPS)

class JoyZmqAdapter:
    name = NAME

    def __init__(self, params):
        self._thread: Thread | None = None
        self._stop_event = threading.Event()
        self.last_rc_channels = []
        self.__event_queue = queue.Queue()
        self.on_failsafe_enter = Event()
        self.on_failsafe_exit = Event()
        self.on_interrupt = Event()
        self.__interrupt_mask = []
        self.server_timeout_s = self._load_server_timeout_s(params)
        parameter_event = getattr(params, "on_parameter_changed", None)
        if parameter_event is not None:
            parameter_event.subscribe(self.on_parameter_changed)
        self._server_seen = False
        self._server_timed_out = False
        self._last_message_at: float | None = None

    def _load_server_timeout_s(self, params) -> float:
        try:
            return params.get(ParameterKey.JOY_TIMEOUT)
        except (AttributeError, KeyError):
            return params.declare(
                ParameterKey.JOY_TIMEOUT,
                DEFAULT_SERVER_TIMEOUT_S,
                {"min": 0.1, "max": 10.0},
                "float",
            )

    def on_parameter_changed(self, name: str, value: Any) -> None:
        if name == ParameterKey.JOY_TIMEOUT:
            self.server_timeout_s = float(value)

    def __check_for_interrupt(self, current):
        """
        check if some input channel config as interrupt is triggered, if so emit the event
        """
        
        if not self.__interrupt_mask or not self.last_rc_channels: return


        for i, name in self.__interrupt_mask:
            try:
                if self.last_rc_channels[i] != current[i]:
                    self.on_interrupt.emit(name, current[i])
            except Exception as e:
                log.error("failed to emit interrupt event index={} name={} error={}".format(i, name, e))
                


    def register_interrupt(self, button_index, interrupt_name):
        """
        register a button index as interrupt, when the button value change, the event will be emitted
        """
        self.__interrupt_mask.append((button_index, interrupt_name))

    def put_event(self, key, value):
        #TODO: think about time stamp
        self.__event_queue.put((key, value))

    def update(self):
        return self.last_rc_channels.copy()

    #region encoding/decoding helpers
    def encode_payload(self, msgpack_module: object, payload: dict[str, object]) -> bytes:
        return msgpack_module.packb(payload, use_bin_type=True)  # type: ignore[attr-defined]


    def decode_payload(self, msgpack_module: object, payload: bytes) -> Any:
        return msgpack_module.unpackb(payload, raw=False)  # type: ignore[attr-defined]
    #endregion

    def now_us(self) -> int:
        return time.time_ns() // 1000

    #region public
    def start(self) -> None:
        self._stop_event.clear()
        self._thread = Thread(target=self._run, daemon=True, name=self.name)
        self._thread.start()

    def stop(self, timeout: float | None = 2.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if not self._thread.is_alive():
                self._thread = None
        
    #endregion
    def make_external_event(self, sequence: int, timestamp_us: int) -> dict[str, object]:
        return {
            "type": "mock_external_event",
            "sequence": sequence,
            "timestamp_us": timestamp_us,
            "message": DEFAULT_MESSAGE,
        }

    def _mark_valid_message(self, now: float, emit_recovery: bool = True) -> None:
        was_timed_out = self._server_timed_out
        self._server_seen = True
        self._last_message_at = now
        self._server_timed_out = False
        if was_timed_out and emit_recovery:
            log.warning("Joystick server messages resumed")
            self.on_failsafe_exit.emit()

    def _check_server_timeout(self, now: float) -> None:
        if (
            not self._server_seen
            or self._server_timed_out
            or self._last_message_at is None
        ):
            return

        elapsed_s = now - self._last_message_at
        if elapsed_s < self.server_timeout_s:
            return

        self._server_timed_out = True
        log.warning(
            "Joystick server timeout: no message for {:.3f}s, threshold {:.3f}s",
            elapsed_s,
            self.server_timeout_s,
        )
        self.on_failsafe_enter.emit()

    def _handle_message(self, topic: str, payload: Any, now: float) -> None:
        if topic == SUB_STATE_TOPIC:
            if not isinstance(payload, dict) or "channels" not in payload:
                log.warning("invalid joystick state payload: {}", payload)
                return
            current = payload["channels"]
            if not isinstance(current, list):
                log.warning("invalid joystick channels payload: {}", current)
                return

            self._mark_valid_message(now)
            self.__check_for_interrupt(current)
            self.last_rc_channels = current.copy()
            return

        if topic == SUB_FAILSAFE_TOPIC:
            if not isinstance(payload, dict):
                log.warning("invalid joystick failsafe payload: {}", payload)
                return

            failsafe_active = payload.get("active", True)
            self._mark_valid_message(now, emit_recovery=False)
            if failsafe_active:
                self.on_failsafe_enter.emit()
            else:
                self.on_failsafe_exit.emit()

    def _run(self) -> None:
        publish_period_s = 1.0 / DEFAULT_PUBLISH_RATE_HZ if DEFAULT_PUBLISH_RATE_HZ > 0 else 0.0
        context = zmq.Context.instance()
        sub_socket = context.socket(zmq.SUB)
        pub_socket = context.socket(zmq.PUB)
        sub_socket.setsockopt(zmq.LINGER, 0)
        pub_socket.setsockopt(zmq.LINGER, 0)
        pub_socket.setsockopt(zmq.SNDHWM, 1)
        poller = zmq.Poller()
        poller_registered = False
        sequence = 0
        next_publish_at = time.monotonic()
        try:
            sub_socket.connect(DEFAULT_SERVER_PUB_ENDPOINT)
            for topic in DEFAULT_SUBSCRIBE_TOPICS:
                sub_socket.setsockopt_string(zmq.SUBSCRIBE, topic)
            poller.register(sub_socket, zmq.POLLIN)
            poller_registered = True

            # pub_socket.bind(args.external_pub_endpoint)
            log.info(f"subscribed {DEFAULT_SERVER_PUB_ENDPOINT} topics={','.join(DEFAULT_SUBSCRIBE_TOPICS)}")
            log.info(f"publishing {DEFAULT_EXTERNAL_PUB_ENDPOINT} topic={DEFAULT_PUBLISH_TOPIC} rate={DEFAULT_PUBLISH_RATE_HZ}Hz")

            while not self._stop_event.is_set():
                events = dict(poller.poll(POLL_TIMEOUT_MS))
                current_time = time.monotonic()

                if sub_socket in events:
                    try:
                        parts = sub_socket.recv_multipart(flags=zmq.NOBLOCK)
                    except zmq.Again:
                        parts = []
                    except zmq.ZMQError as exc:
                        log.warning("failed to receive joystick zmq message: {}", exc)
                        parts = []

                    if len(parts) != 2:
                        if parts:
                            log.warning("invalid joystick zmq multipart size: {}", len(parts))
                    else:
                        topic_bytes, payload_bytes = parts
                        try:
                            topic = topic_bytes.decode("utf-8")
                            payload = self.decode_payload(msgpack, payload_bytes)
                        except (UnicodeDecodeError, msgpack.UnpackException, ValueError) as exc:
                            log.warning("invalid joystick zmq payload: {}", exc)
                        else:
                            self._handle_message(topic, payload, current_time)

                self._check_server_timeout(current_time)

                # region publish external event
                if current_time >= next_publish_at:
                    event = self.make_external_event(sequence, self.now_us())
                    try:
                        pub_socket.send_multipart(
                            [
                                DEFAULT_PUBLISH_TOPIC.encode("utf-8"),
                                self.encode_payload(msgpack, event),
                            ],
                            flags=zmq.DONTWAIT,
                        )
                        sequence += 1
                    except zmq.ZMQError as exc:
                        log.warning("failed to publish joystick external event: {}", exc)
                    next_publish_at = current_time + publish_period_s
                # endregion
        except KeyboardInterrupt:
            log.error("exit")
            return 0
        finally:
            if poller_registered:
                poller.unregister(sub_socket)
            sub_socket.close()
            pub_socket.close()


# require every plugin file to expose a registration function
def register():
    return JoyZmqAdapter
