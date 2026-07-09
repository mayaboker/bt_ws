import bt_app.msp_adapter as msp_adapter_module
from bt_app.msp_adapter import MSPAdapter
from bt_app.vehicle_config import DroneSink, VehicleConfig


class FakeMspClient:
    def __init__(self, transport):
        self.transport = transport
        self.opened = False

    def open(self):
        self.opened = True


class FakeTransport:
    def __init__(self, host, port):
        self.host = host
        self.port = port


class FakeDispatcher:
    def __init__(self, msp, on_error=None):
        self.msp = msp
        self.on_error = on_error
        self.scheduled = []
        self.started = False

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
