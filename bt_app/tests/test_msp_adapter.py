import bt_app.msp_adapter as msp_adapter_module
from bt_app.msp_adapter import MSPAdapter
from bt_app.vehicle_config import DroneSink, VehicleConfig


class FakeMspClient:
    def __init__(self, transport):
        self.transport = transport
        self.opened = False
        self.closed = False

    def open(self):
        self.opened = True

    def close(self):
        self.closed = True


class FakeTransport:
    def __init__(self, host, port):
        self.host = host
        self.port = port


class FakeSerialTransport:
    def __init__(self, device):
        self.device = device


class FakeDispatcher:
    def __init__(self, msp, on_error=None):
        self.msp = msp
        self.on_error = on_error
        self.scheduled = []
        self.started = False
        self.stopped = False
        self.stop_timeout = None

    def schedule_state(self, interval_s):
        self.scheduled.append(("state", interval_s))

    def schedule_altitude(self, interval_s):
        self.scheduled.append(("altitude", interval_s))

    def schedule_battery(self, interval_s):
        self.scheduled.append(("battery", interval_s))

    def schedule_rc(self, interval_s):
        self.scheduled.append(("rc", interval_s))

    def start(self):
        self.started = True

    def stop(self, timeout=2.0):
        self.stopped = True
        self.stop_timeout = timeout


def test_msp_adapter_schedules_battery_at_0_5_hz(monkeypatch):
    monkeypatch.setattr(msp_adapter_module, "BetaflightMspClient", FakeMspClient)
    monkeypatch.setattr(msp_adapter_module, "TcpMspTransport", FakeTransport)
    monkeypatch.setattr(msp_adapter_module, "MspCommandDispatcher", FakeDispatcher)
    config = VehicleConfig()
    config.drone_sink = DroneSink.ETHERNET.value

    adapter = MSPAdapter(config)
    adapter.start()

    assert adapter.msp.opened
    assert ("battery", 2.0) in adapter.dispatcher.scheduled
    assert adapter.dispatcher.started


def test_msp_adapter_uses_serial_transport(monkeypatch):
    monkeypatch.setattr(msp_adapter_module, "BetaflightMspClient", FakeMspClient)
    monkeypatch.setattr(msp_adapter_module, "SerialMspTransport", FakeSerialTransport)
    monkeypatch.setattr(msp_adapter_module, "MspCommandDispatcher", FakeDispatcher)
    config = VehicleConfig()
    config.drone_sink = DroneSink.SERIAL.value
    config.drone_serial_port = "/dev/ttyACM0"

    adapter = MSPAdapter(config)

    assert adapter.msp.transport.device == "/dev/ttyACM0"


def test_msp_adapter_stops_dispatcher_before_closing_client(monkeypatch):
    events = []

    class OrderedMspClient(FakeMspClient):
        def close(self):
            events.append("client")
            super().close()

    class OrderedDispatcher(FakeDispatcher):
        def stop(self, timeout=2.0):
            events.append("dispatcher")
            super().stop(timeout=timeout)

    monkeypatch.setattr(msp_adapter_module, "BetaflightMspClient", OrderedMspClient)
    monkeypatch.setattr(msp_adapter_module, "TcpMspTransport", FakeTransport)
    monkeypatch.setattr(msp_adapter_module, "MspCommandDispatcher", OrderedDispatcher)
    config = VehicleConfig()
    config.drone_sink = DroneSink.ETHERNET.value
    adapter = MSPAdapter(config)

    adapter.stop(timeout=0.5)

    assert events == ["dispatcher", "client"]
    assert adapter.dispatcher.stop_timeout == 0.5
    assert adapter.msp.closed
