import threading

import pytest

from bt_app.msp.command_dispatcher import (
    MspCommandDispatcher,
    MspCommandExecutionError,
    ReadAttitudeCommand,
    ReadBatteryCommand,
)


class FakeMsp:
    def __init__(self):
        self.battery = {
            "cell_count": 4,
            "voltage_mv": 16100,
            "current_ca": 1234,
        }

    def read_battery_state(self):
        return self.battery

    def read_attitude(self):
        return {"roll_deg": 1.5, "pitch_deg": -2.5, "heading_deg": 90}


def test_read_attitude_command_updates_latest_attitude():
    callback_results = []
    dispatcher = MspCommandDispatcher(
        FakeMsp(),
        on_attitude=callback_results.append,
    )

    result = ReadAttitudeCommand().execute(dispatcher)

    assert result == {"roll_deg": 1.5, "pitch_deg": -2.5, "heading_deg": 90}
    assert dispatcher.last_attitude == result
    assert callback_results == [result]


def test_read_battery_command_updates_last_battery_and_callback():
    callback_results = []
    dispatcher = MspCommandDispatcher(
        FakeMsp(),
        on_battery=lambda battery: callback_results.append(battery),
    )

    result = ReadBatteryCommand().execute(dispatcher)

    assert result == dispatcher.last_battery
    assert result == {
        "cell_count": 4,
        "voltage_mv": 16100,
        "current_ca": 1234,
    }
    assert callback_results == [result]


def test_schedule_battery_uses_0_5_hz_default():
    dispatcher = MspCommandDispatcher(FakeMsp())

    dispatcher.schedule_battery()

    assert len(dispatcher._queue) == 1
    _run_at, _sequence, _token, command = dispatcher._queue[0]
    assert command.repeat_interval_s == 2.0
    assert isinstance(command.command, ReadBatteryCommand)


def test_rc_failure_stops_dispatcher_and_surfaces_worker_error():
    attempted = threading.Event()
    errors = []

    class FailingMsp(FakeMsp):
        def send_raw_rc(self, _channels):
            attempted.set()
            raise ConnectionError("FCU disconnected")

    dispatcher = MspCommandDispatcher(FailingMsp(), on_error=errors.append)
    dispatcher.set_rc((1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000))
    dispatcher.start()

    assert attempted.wait(1.0)
    dispatcher.stop()

    with pytest.raises(MspCommandExecutionError) as exc_info:
        dispatcher.raise_if_failed()

    assert exc_info.value.command_name == "RawRcCommand"
    assert exc_info.value.command_key == "rc"
    assert isinstance(exc_info.value.__cause__, ConnectionError)
    assert errors == [exc_info.value]
    assert dispatcher._queue == []


def test_telemetry_failure_is_reported_but_remains_nonfatal():
    attempted = threading.Event()
    errors = []

    class FailingMsp(FakeMsp):
        def read_state(self):
            attempted.set()
            raise TimeoutError("state timeout")

    dispatcher = MspCommandDispatcher(FailingMsp(), on_error=errors.append)
    dispatcher.schedule_state(interval_s=0.01)
    dispatcher.start()

    assert attempted.wait(1.0)
    dispatcher.stop()

    dispatcher.raise_if_failed()
    assert errors
    assert errors[0].command_key == "state"
    assert isinstance(errors[0].cause, TimeoutError)
