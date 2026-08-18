import pytest

from bt_app.common import InternalJoystick, RobotState
from bt_app.msp.bt_v2 import RC_MID, RC_MIN
from bt_app.context import Context
from bt_app.parameters.generated import ParameterKey
from bt_app.services import ManualLandService


class FakeEvent:
    def __init__(self):
        self.callback = None

    def subscribe(self, callback):
        self.callback = callback

    def emit(self, name, value):
        self.callback(name, value)


class FakeParameters:
    def __init__(self):
        self.on_parameter_changed = FakeEvent()
        self.values = {
            ParameterKey.MI_LAND_CONFIRM: 2.0,
            ParameterKey.FS_LAND_ALT: 0.15,
            ParameterKey.FS_LAND_VSPEED: 0.1,
        }

    def get(self, name):
        return self.values[name]


class FakeDetector:
    def __init__(self, result=False):
        self.result = result
        self.updates = []
        self.reset_calls = 0
        self.confirm_s = 2.0
        self.land_altitude_m = 0.15
        self.land_vertical_speed_m_s = 0.1

    def update(self, altitude, vertical_speed):
        self.updates.append((altitude, vertical_speed))
        return self.result

    def reset(self):
        self.reset_calls += 1


def make_context():
    context = Context()
    context.state = RobotState.MANUAL
    context.drone_alt = 0.1
    context.drone_vertical_speed = 0.02
    context.manual_land_confirmed = False
    context.request_rc = InternalJoystick(
        roll=RC_MID,
        pitch=RC_MID,
        throttle=RC_MIN,
        yaw=RC_MID,
        manual=RC_MID,
    )
    return context


def test_update_sets_context_from_detector_result():
    context = make_context()
    detector = FakeDetector(result=True)
    service = ManualLandService(
        context=context,
        parameters=FakeParameters(),
        detector=detector,
    )

    assert service.update() is None

    assert context.manual_land_confirmed is True
    assert detector.updates == [(0.1, 0.02)]


@pytest.mark.parametrize(
    "deactivate",
    [
        lambda context: setattr(context, "state", RobotState.ALT_HOLD),
        lambda context: setattr(
            context, "request_rc", context.request_rc._replace(manual=RC_MIN)
        ),
        lambda context: setattr(
            context, "request_rc", context.request_rc._replace(throttle=RC_MID)
        ),
    ],
)
def test_inactive_or_malformed_input_resets(deactivate):
    context = make_context()
    context.manual_land_confirmed = True
    detector = FakeDetector(result=True)
    service = ManualLandService(
        context=context,
        parameters=FakeParameters(),
        detector=detector,
    )
    deactivate(context)

    service.update()

    assert context.manual_land_confirmed is False
    assert detector.reset_calls == 1
    assert detector.updates == []


def test_reset_clears_detector_and_context():
    context = make_context()
    context.manual_land_confirmed = True
    detector = FakeDetector()
    service = ManualLandService(
        context=context,
        parameters=FakeParameters(),
        detector=detector,
    )

    service.reset()

    assert context.manual_land_confirmed is False
    assert detector.reset_calls == 1


@pytest.mark.parametrize(
    ("name", "value", "attribute"),
    [
        (ParameterKey.MI_LAND_CONFIRM, 3.0, "confirm_s"),
        (ParameterKey.FS_LAND_ALT, 0.25, "land_altitude_m"),
        (ParameterKey.FS_LAND_VSPEED, 0.2, "land_vertical_speed_m_s"),
    ],
)
def test_parameter_changes_update_detector(name, value, attribute):
    context = make_context()
    parameters = FakeParameters()
    detector = FakeDetector()
    ManualLandService(
        context=context,
        parameters=parameters,
        detector=detector,
    )

    parameters.on_parameter_changed.emit(name, value)

    assert getattr(detector, attribute) == value
