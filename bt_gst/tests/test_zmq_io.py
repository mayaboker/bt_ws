import sys
import types

import pytest

from bt_gst.main import TrackerMeta
from bt_gst.zmq_io import (
    TRACKER_META_VERSION,
    TrackerMetaPublisher,
    ZmqPublisherError,
    encode_tracker_meta,
)


def test_encode_tracker_meta_uses_msgpack_payload() -> None:
    msgpack = pytest.importorskip("msgpack")

    message = encode_tracker_meta(
        TrackerMeta(dx=1, dy=-2, score=0.75),
        timestamp_ns=123,
    )

    payload = msgpack.unpackb(message, raw=False)
    assert payload == {
        "version": TRACKER_META_VERSION,
        "timestamp_ns": 123,
        "dx": 1,
        "dy": -2,
        "score": 0.75,
    }


def test_tracker_meta_publisher_keeps_latest_queued_message(monkeypatch) -> None:
    publisher = TrackerMetaPublisher()
    values = iter([b"old", b"new"])

    monkeypatch.setattr("bt_gst.zmq_io.encode_tracker_meta", lambda meta: next(values))

    publisher.publish(TrackerMeta(dx=1, dy=1, score=0.1))
    publisher.publish(TrackerMeta(dx=2, dy=2, score=0.2))

    assert publisher._queue.get_nowait() == b"new"


def test_tracker_meta_publisher_start_reports_bind_failure(monkeypatch) -> None:
    class FakeZmqError(RuntimeError):
        pass

    class FakeSocket:
        def setsockopt(self, option: int, value: int) -> None:
            return None

        def bind(self, endpoint: str) -> None:
            raise FakeZmqError("address already in use")

        def close(self, linger: int = 0) -> None:
            return None

    class FakeContext:
        def socket(self, socket_type: int) -> FakeSocket:
            return FakeSocket()

        def term(self) -> None:
            return None

    fake_zmq = types.ModuleType("zmq")
    fake_zmq.PUB = 1
    fake_zmq.SNDHWM = 2
    fake_zmq.LINGER = 3
    fake_zmq.NOBLOCK = 4
    fake_zmq.Again = RuntimeError
    fake_zmq.Context = FakeContext
    monkeypatch.setitem(sys.modules, "msgpack", types.ModuleType("msgpack"))
    monkeypatch.setitem(sys.modules, "zmq", fake_zmq)

    publisher = TrackerMetaPublisher(endpoint="tcp://127.0.0.1:5556")

    with pytest.raises(ZmqPublisherError, match="address already in use"):
        publisher.start()
