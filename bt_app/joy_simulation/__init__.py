

from bt_app.msp.bt_v2 import (
    RC_MAX,
    RC_MID,
    RC_MIN
)

from bt_app.common import (
    InternalJoy)

def rc_channels(
    *,
    throttle: int = RC_MIN,
    armed: bool = False,
    manual: bool = False,
    auto_takeoff: bool = False,
    tracker_mode: bool = False,
    payload: bool = False
) -> tuple[int, ...]:
    """Build the eight application joystick channels."""

    channels = [RC_MIN] * len(InternalJoy)
    channels[InternalJoy.ROLL] = RC_MID
    channels[InternalJoy.PITCH] = RC_MID
    channels[InternalJoy.THROTTLE] = throttle
    channels[InternalJoy.YAW] = RC_MID
    channels[InternalJoy.ARM] = RC_MAX if armed else RC_MIN
    channels[InternalJoy.MANUAL] = RC_MIN if manual else RC_MAX
    channels[InternalJoy.PAYLOAD] = RC_MAX if payload else RC_MIN
    channels[InternalJoy.AUTO_TAKE_OFF] = RC_MAX if auto_takeoff else RC_MIN
    channels[InternalJoy.TRACKER_MODE] = RC_MAX if tracker_mode else RC_MIN

    return tuple(channels)