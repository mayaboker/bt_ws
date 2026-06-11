import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bt_joy.server.msp import MspAltitude, MspStatus
from bt_joy.server.state import RcChannel


class _Logger:
    def warning(self, *_args, **_kwargs) -> None:
        pass


sys.modules.setdefault("loguru", SimpleNamespace(logger=_Logger()))

from bt_joy.server.command_dispatcher import MspCommandDispatcher, RawRcCommand


class _MspClient:
    def __init__(self) -> None:
        self.raw_rc = []

    def send_raw_rc(self, channels) -> None:
        self.raw_rc.append(list(channels))


class CommandDispatcherTest(unittest.TestCase):
    def test_raw_rc_command_normalizes_and_sends_channels(self) -> None:
        msp = _MspClient()
        dispatcher = MspCommandDispatcher(msp)

        result = RawRcCommand([1000, 2000, 3000]).execute(dispatcher)

        self.assertEqual(result, [1000, 2000, 3000, 1500, 1500, 1500, 1500, 1500])
        self.assertEqual(msp.raw_rc, [[1000, 2000, 3000, 1500, 1500, 1500, 1500, 1500]])
        self.assertEqual(dispatcher.snapshot().commanded_channel(RcChannel.THROTTLE), 3000)

    def test_replaces_older_rc_command_with_latest(self) -> None:
        msp = _MspClient()
        dispatcher = MspCommandDispatcher(msp)

        dispatcher.submit(RawRcCommand([1000, 1500, 1000, 1500, 1000, 1000, 1000, 1000]))
        dispatcher.submit(RawRcCommand([1500, 1500, 1100, 1500, 1000, 1000, 1000, 1000]))

        item = dispatcher._pop_ready_command()
        self.assertIsNotNone(item)
        _run_at, _sequence, _token, command = item
        command.execute(dispatcher)

        self.assertEqual(msp.raw_rc, [[1500, 1500, 1100, 1500, 1000, 1000, 1000, 1000]])

    def test_snapshot_includes_latest_status_rc_and_altitude(self) -> None:
        dispatcher = MspCommandDispatcher(_MspClient())
        status = MspStatus(
            cycle_time_us=250,
            i2c_errors=0,
            sensors_mask=1,
            box_mode_flags=2,
        )
        altitude = MspAltitude(altitude_m=1.2, vertical_speed_m_s=0.3)

        with patch("bt_joy.server.state.time.monotonic", side_effect=[10.0, 11.0, 12.0]):
            dispatcher.record_status(status)
            dispatcher.record_rc([1000, 1500, 2000])
            dispatcher.record_altitude(altitude)

        snapshot = dispatcher.snapshot()

        self.assertEqual(snapshot.status, status)
        self.assertEqual(snapshot.status_at, 10.0)
        self.assertEqual(snapshot.fc_rc_channels, (1000, 1500, 2000))
        self.assertEqual(snapshot.fc_rc_channels_at, 11.0)
        self.assertEqual(snapshot.altitude, altitude)
        self.assertEqual(snapshot.altitude_at, 12.0)


if __name__ == "__main__":
    unittest.main()
