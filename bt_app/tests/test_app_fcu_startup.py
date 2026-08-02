import pytest

import bt_app.app as app_module
from bt_app.app import App
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

    def __init__(self, config):
        self.config = config
        self.msp = FakeMspClient()
        self.start_count = 0
        self.stop_count = 0

    def start(self):
        self.start_count += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome

    def stop(self):
        self.stop_count += 1
        self.msp.close()


@pytest.fixture(autouse=True)
def reset_vehicle_config():
    VehicleConfig._instance = None
    VehicleConfig._initialized = False
    yield
    VehicleConfig._instance = None
    VehicleConfig._initialized = False


def make_loader_app():
    app = App.__new__(App)
    app.config = VehicleConfig()
    app.config.drone_sink = DroneSink.ETHERNET.value
    app.config.drone_eth_host = "127.0.0.1"
    app.config.drone_eth_port = 5761
    app.drone_adapter = None
    return app


def test_fcu_connection_retries_then_succeeds(monkeypatch):
    FakeAdapter.outcomes = [
        ConnectionRefusedError(111, "Connection refused"),
        TimeoutError("timed out"),
        None,
    ]
    waits = []
    monkeypatch.setattr(app_module, "MSPAdapter", FakeAdapter)
    monkeypatch.setattr(app_module.time, "sleep", waits.append)
    app = make_loader_app()

    app._App__load_drone_interface()

    assert app.drone_adapter.start_count == 3
    assert app.drone_adapter.msp.close_count == 2
    assert waits == [1.0, 1.0]


def test_fcu_connection_failure_becomes_expected_startup_error(monkeypatch):
    errors = [ConnectionRefusedError(111, "Connection refused") for _ in range(3)]
    FakeAdapter.outcomes = errors.copy()
    monkeypatch.setattr(app_module, "MSPAdapter", FakeAdapter)
    monkeypatch.setattr(app_module.time, "sleep", lambda _delay: None)
    app = make_loader_app()

    with pytest.raises(AppStartupError) as exc_info:
        app._App__load_drone_interface()

    assert exc_info.value.exit_code == AppExitCode.FCU_CONNECTION_FAILED
    assert str(exc_info.value) == (
        "Unable to connect to FCU over TCP at 127.0.0.1:5761 after "
        "3 attempts: connection refused"
    )
    assert exc_info.value.__cause__ is errors[-1]
    assert app.drone_adapter.msp.close_count == 3


def test_missing_transport_dependency_fails_without_retry(monkeypatch):
    error = MspTransportDependencyError("pyserial is missing")
    FakeAdapter.outcomes = [error]
    monkeypatch.setattr(app_module, "MSPAdapter", FakeAdapter)
    app = make_loader_app()

    with pytest.raises(AppStartupError) as exc_info:
        app._App__load_drone_interface()

    assert exc_info.value.exit_code == AppExitCode.FCU_CONNECTION_FAILED
    assert "Unable to initialize FCU TCP transport" in str(exc_info.value)
    assert exc_info.value.__cause__ is error
    assert app.drone_adapter.start_count == 1


def test_failed_app_initialization_stops_partial_resources(monkeypatch):
    events = []

    class FakeParams:
        def get(self, _name):
            return 1.0

        def stop(self):
            events.append("parameters")

    class FailingAdapter(FakeAdapter):
        outcomes = [ConnectionRefusedError(111, "Connection refused")]

        def stop(self):
            events.append("msp")
            super().stop()

    monkeypatch.setattr(app_module, "FCU_CONNECT_ATTEMPTS", 1)
    monkeypatch.setattr(app_module, "MSPAdapter", FailingAdapter)
    monkeypatch.setattr(App, "_App__load_parameters", lambda self: FakeParams())
    monkeypatch.setattr(App, "_App__load_manual_land_detector", lambda self: object())
    config = VehicleConfig()

    with pytest.raises(AppStartupError):
        App(config)

    assert events == ["msp", "parameters"]
