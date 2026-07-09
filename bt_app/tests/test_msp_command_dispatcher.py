from bt_app.msp.command_dispatcher import MspCommandDispatcher, ReadBatteryCommand


class FakeMsp:
    def __init__(self):
        self.battery = {
            "cell_count": 4,
            "voltage_mv": 16100,
            "current_ca": 1234,
        }

    def read_battery_state(self):
        return self.battery


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
