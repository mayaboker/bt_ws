import pytest

from bt_app.common import InternalJoystick, TrackerMode
from bt_app.msp.bt_v2 import RC_MAX, RC_MID, RC_MIN


def valid_channels() -> list[int]:
    return [
        RC_MID,
        RC_MID,
        RC_MIN,
        RC_MID,
        RC_MIN,
        RC_MIN,
        RC_MIN,
        *([0] * 11),
    ]


def test_defaults_are_safe_and_center_attitude_axes():
    joystick = InternalJoystick()

    assert joystick.roll == RC_MID
    assert joystick.pitch == RC_MID
    assert joystick.throttle == RC_MIN
    assert joystick.yaw == RC_MID
    assert joystick.arm == RC_MIN
    assert joystick.manual == RC_MIN
    assert joystick.auto_takeoff == RC_MIN
    assert joystick.tracker_mode == TrackerMode.DISABLED
    assert joystick.tracker_enable == RC_MIN
    assert len(joystick) == 18


def test_from_channels_preserves_active_values_and_normalizes_reserved_zeros():
    channels = valid_channels()
    channels[0] = 1600
    channels[4] = RC_MAX

    joystick = InternalJoystick.from_channels(channels)

    assert joystick.roll == 1600
    assert joystick.arm == RC_MAX
    assert joystick.tracker_mode == TrackerMode.DISABLED
    assert joystick.tracker_enable == RC_MIN
    assert joystick.reserved_18 == RC_MIN


@pytest.mark.parametrize("channel_count", [0, 7, 17, 19])
def test_from_channels_requires_exactly_18_channels(channel_count):
    with pytest.raises(ValueError, match="exactly 18"):
        InternalJoystick.from_channels([RC_MIN] * channel_count)


@pytest.mark.parametrize(
    ("index", "value"),
    [
        (0, 0),
        (2, 999),
        (6, 2001),
        (7, 999),
        (17, 65534),
    ],
)
def test_from_channels_rejects_invalid_pwm_values(index, value):
    channels = valid_channels()
    channels[index] = value

    with pytest.raises(ValueError, match=f"channel {index + 1}"):
        InternalJoystick.from_channels(channels)


def test_position_predicates_use_existing_switch_and_throttle_rules():
    joystick = InternalJoystick(
        throttle=1049,
        arm=RC_MAX,
        manual=RC_MIN,
        auto_takeoff=RC_MAX,
    )

    assert joystick.is_throttle_low()
    assert joystick.is_armed()
    assert joystick.is_manual()
    assert joystick.is_auto_takeoff()


@pytest.mark.parametrize(
    ("raw_value", "expected", "selected"),
    [
        (RC_MIN, TrackerMode.DISABLED, False),
        (RC_MID, TrackerMode.TRACKER1, True),
        (RC_MAX, TrackerMode.TRACKER2, True),
    ],
)
def test_tracker_mode_positions(raw_value, expected, selected):
    joystick = InternalJoystick(tracker_mode=raw_value)

    assert joystick.selected_tracker_mode() == expected
    assert joystick.is_tracker_selected() is selected


def test_unknown_tracker_mode_is_not_selected():
    joystick = InternalJoystick(tracker_mode=1400)

    assert joystick.selected_tracker_mode() is None
    assert not joystick.is_tracker_selected()


def test_tracker_enable_requires_high_position():
    assert not InternalJoystick(tracker_enable=RC_MIN).is_tracker_enable_high()
    assert InternalJoystick(tracker_enable=RC_MAX).is_tracker_enable_high()


def test_named_tuple_is_immutable():
    joystick = InternalJoystick()

    with pytest.raises(AttributeError):
        joystick.throttle = RC_MAX
