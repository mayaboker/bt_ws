from dataclasses import FrozenInstanceError

import msgpack
import pytest

from bt_msgs import TargetSelectorCommandMessage, TargetSelectorState


def command(**overrides):
    values = {
        "timestamp_ns": 123,
        "center_x": 0.25,
        "center_y": 0.75,
        "state": TargetSelectorState.SELECTING,
    }
    values.update(overrides)
    return TargetSelectorCommandMessage(**values)


def test_selector_command_round_trip_and_wire_shape():
    message = command()
    assert TargetSelectorCommandMessage.decode(message.encode()) == message
    assert msgpack.unpackb(message.encode(), raw=False) == {
        "timestamp_ns": 123,
        "center_x": 0.25,
        "center_y": 0.75,
        "state": 1,
    }


def test_selector_command_is_frozen_and_slotted():
    message = command()
    assert not hasattr(message, "__dict__")
    with pytest.raises(FrozenInstanceError):
        message.center_x = 0.5


@pytest.mark.parametrize("field", ["timestamp_ns", "center_x", "center_y", "state"])
def test_selector_decode_requires_fields(field):
    wire = msgpack.unpackb(command().encode(), raw=False)
    del wire[field]
    with pytest.raises(ValueError, match=field):
        TargetSelectorCommandMessage.decode(msgpack.packb(wire, use_bin_type=True))


@pytest.mark.parametrize("field,value", [("center_x", -0.1), ("center_y", 1.1)])
def test_selector_rejects_out_of_range_coordinates(field, value):
    with pytest.raises(ValueError, match="between"):
        command(**{field: value})


def test_selector_rejects_unknown_state():
    wire = msgpack.unpackb(command().encode(), raw=False)
    wire["state"] = 99
    with pytest.raises(ValueError, match="valid TargetSelectorState"):
        TargetSelectorCommandMessage.decode(msgpack.packb(wire, use_bin_type=True))
