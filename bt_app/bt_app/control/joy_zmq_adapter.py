"""
listen to zmq traffic from joy publisher
- joystick channel
- failsafe

The last RC data saved
The listener run in a separate thread and update vehicle state when failsafe is detected or cancel
"""

from __future__ import annotations

import msgpack
import zmq
import json
from threading import Thread
import time
from typing import Any
from loguru import logger as log


DEFAULT_SERVER_PUB_ENDPOINT = "ipc:///tmp/bt_joy_server_pub.ipc"
DEFAULT_EXTERNAL_PUB_ENDPOINT = "ipc:///tmp/bt_joy_external_pub.ipc"
SUB_STATE_TOPIC = "joystick.state"
DEFAULT_SUBSCRIBE_TOPICS = (SUB_STATE_TOPIC, "joystick.failsafe")
DEFAULT_PUBLISH_TOPIC = "bt_joy.external"
DEFAULT_PUBLISH_RATE_HZ = 1.0
DEFAULT_MESSAGE = "hello from zmq mock"
FPS = 50.0
NAME = "joy_zmq_adapter"

class JoyZmqAdapter:
    name = NAME

    def __init__(self):
        self._thread: Thread | None = None
        self._stop_event = False
        self.last_rc_channels = []
    
    def pull_rc_channels(self):
        return self.last_rc_channels

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
        self._thread = Thread(target=self._run, daemon=True, name=self.name)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event = True
        
    #endregion

    def _run(self) -> None:
    # publish_period_s = 1.0 / args.publish_rate_hz if args.publish_rate_hz > 0 else 0.0
        context = zmq.Context()
        sub_socket = context.socket(zmq.SUB)
        # pub_socket = context.socket(zmq.PUB)
        sequence = 0
        next_publish_at = time.monotonic()

        try:
            sub_socket.connect(DEFAULT_SERVER_PUB_ENDPOINT)
            for topic in DEFAULT_SUBSCRIBE_TOPICS:
                sub_socket.setsockopt_string(zmq.SUBSCRIBE, topic)

            # pub_socket.bind(args.external_pub_endpoint)
            log.info(f"subscribed {DEFAULT_SERVER_PUB_ENDPOINT} topics={','.join(DEFAULT_SUBSCRIBE_TOPICS)}")
            # print(f"publishing {args.external_pub_endpoint} topic={args.publish_topic}")

            while not self._stop_event:
                try:
                    # non-blocking receive with timeout, using not block to later publish state 
                    topic_bytes, payload_bytes = sub_socket.recv_multipart()
                except zmq.Again:
                    time.sleep(1/FPS)
                    log.debug("no message received")
                    continue
                topic = topic_bytes.decode("utf-8")
                payload = self.decode_payload(msgpack, payload_bytes)
                
                if topic == SUB_STATE_TOPIC:
                    self.last_rc_channels = payload["channels"]
                    # print(self.last_rc_channels)

                # region publish external event
                current_time = time.monotonic()
                # if current_time >= next_publish_at:
                #     event = self.make_external_event(sequence, self.now_us())
                #     pub_socket.send_multipart(
                #         [
                #             args.publish_topic.encode("utf-8"),
                #             self.encode_payload(msgpack, event),
                #         ]
                #     )
                #     print(f"{args.publish_topic} {json.dumps(event, sort_keys=True)}")
                #     sequence += 1
                #     next_publish_at = current_time + publish_period_s
                # endregion

            time.sleep(1/FPS)
        except KeyboardInterrupt:
            return 0
        finally:
            sub_socket.close()
            # pub_socket.close()
            context.term()


# require every plugin file to expose a registration function
def register():
    return JoyZmqAdapter