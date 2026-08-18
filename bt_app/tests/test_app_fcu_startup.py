import pytest

import bt_app.app_services as services_module
from bt_app.app import App, AppLifecycle
from bt_app.app_services import AppServices
from bt_app.errors import AppExitCode, AppStartupError
from bt_app.msp import MspTransportDependencyError
from bt_app.vehicle_config import DroneSink, VehicleConfig


class FakeMspClient:
    def __init__(self):
        self.close_count = 0

    def close(self):
        self.close_count += 1


class FakeAdapter:
    outcomes = []

    def __init__(self):
        self.msp = FakeMspClient()
        self.start_count = 0

    def start(self):
        self.start_count += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome


@pytest.fixture(autouse=True)
def reset_vehicle_config():
    VehicleConfig._instance = None
    VehicleConfig._initialized = False
    yield
    VehicleConfig._instance = None
    VehicleConfig._initialized = False


def make_services(drone=None):
    services = AppServices.__new__(AppServices)
    services.config = VehicleConfig()
    services.config.drone_sink = DroneSink.ETHERNET.value
    services.config.drone_eth_host = "127.0.0.1"
    services.config.drone_eth_port = 5761
    services.drone = drone or FakeAdapter()
    services._started = []
    return services


def test_app_constructor_has_no_external_side_effects(monkeypatch):
    def unexpected_build(**_kwargs):
        raise AssertionError("services built during App construction")

    monkeypatch.setattr(AppServices, "build", unexpected_build)
    app = App(VehicleConfig())

    assert app.services is None


def test_visual_bridge_endpoint_must_not_be_empty():
    app = App(VehicleConfig())
    app.config.visual_zmq_endpoint = ""

    with pytest.raises(AppStartupError, match="endpoint must not be empty"):
        app.start()


def test_startup_notification_failure_rolls_back_services(monkeypatch):
    events = []

    class Parameters:
        class Event:
            def subscribe(self, _callback):
                return None

        on_parameter_changed = Event()

        def get(self, _key):
            return 1.0

    class Mavlink:
        def send_text_to_gcs(self, *_args):
            raise OSError("GCS unavailable")

    class Services:
        parameters = Parameters()
        mavlink = Mavlink()

        def start_all(self):
            events.append("start")

        def stop_all(self):
            events.append("stop")

    monkeypatch.setattr(AppServices, "build", lambda **_kwargs: Services())
    monkeypatch.setattr(App, "_App__load_manual_land_detector", lambda self: object())
    monkeypatch.setattr(App, "_App__load_controllers", lambda self: None)
    app = App(VehicleConfig())

    with pytest.raises(OSError, match="GCS unavailable"):
        app.start()

    assert events == ["start", "stop"]
    assert app._lifecycle == AppLifecycle.FAILED
    with pytest.raises(RuntimeError, match="create a new App instance"):
        app.start()


def test_fcu_connection_retries_then_succeeds(monkeypatch):
    drone = FakeAdapter()
    drone.outcomes = [
        ConnectionRefusedError(111, "Connection refused"),
        TimeoutError("timed out"),
        None,
    ]
    waits = []
    monkeypatch.setattr(services_module.time, "sleep", waits.append)
    services = make_services(drone)

    services._start_drone()

    assert drone.start_count == 3
    assert drone.msp.close_count == 2
    assert waits == [1.0, 1.0]


def test_fcu_connection_failure_becomes_expected_startup_error(monkeypatch):
    errors = [ConnectionRefusedError(111, "Connection refused") for _ in range(3)]
    drone = FakeAdapter()
    drone.outcomes = errors.copy()
    monkeypatch.setattr(services_module.time, "sleep", lambda _delay: None)
    services = make_services(drone)

    with pytest.raises(AppStartupError) as exc_info:
        services._start_drone()

    assert exc_info.value.exit_code == AppExitCode.FCU_CONNECTION_FAILED
    assert str(exc_info.value) == (
        "Unable to connect to FCU over TCP at 127.0.0.1:5761 after "
        "3 attempts: connection refused"
    )
    assert exc_info.value.__cause__ is errors[-1]
    assert drone.msp.close_count == 3


def test_missing_transport_dependency_fails_without_retry():
    error = MspTransportDependencyError("pyserial is missing")
    drone = FakeAdapter()
    drone.outcomes = [error]
    services = make_services(drone)

    with pytest.raises(AppStartupError) as exc_info:
        services._start_drone()

    assert exc_info.value.exit_code == AppExitCode.FCU_CONNECTION_FAILED
    assert "Unable to initialize FCU TCP transport" in str(exc_info.value)
    assert exc_info.value.__cause__ is error
    assert drone.start_count == 1
