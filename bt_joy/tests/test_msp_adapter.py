import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class _Logger:
    def info(self, *_args, **_kwargs) -> None:
        pass

    def warning(self, *_args, **_kwargs) -> None:
        pass

    def debug(self, *_args, **_kwargs) -> None:
        pass


sys.modules.setdefault("loguru", SimpleNamespace(logger=_Logger()))

from bt_joy.server.adapters.msp import MspOutputAdapter, _read_altitude, _read_rc
import bt_joy.server.adapters.msp as msp_adapter
from bt_joy.server.config import MspServerConfig
from bt_joy.server.msp import MspAltitude


class _Transport:
    def __enter__(self):
        return self

    def __exit__(self, *_exc: object) -> None:
        pass


class _Dispatcher:
    def __init__(self) -> None:
        self.rc_commands = []
        self.rc_reads = []
        self.altitude_reads = []
        self.msp = SimpleNamespace(
            read_rc=lambda timeout: self.rc_reads.pop(0),
            read_altitude=lambda timeout: self.altitude_reads.pop(0),
        )

    def set_rc(self, channels, rate_hz: float) -> None:
        self.rc_commands.append((list(channels), rate_hz))

    def record_rc(self, channels) -> None:
        self.recorded_rc = list(channels)

    def record_altitude(self, altitude) -> None:
        self.recorded_altitude = altitude


class MspOutputAdapterTest(unittest.TestCase):
    def test_write_channels_submits_rc_to_dispatcher(self) -> None:
        dispatcher = _Dispatcher()
        adapter = MspOutputAdapter(_Transport(), MspServerConfig(rc_rate_hz=25.0))
        adapter.dispatcher = dispatcher

        adapter.write_channels([1000, 1500, 1100, 1500, 1000, 1000, 1000, 1000], 7, 1234)

        self.assertEqual(
            dispatcher.rc_commands,
            [([1000, 1500, 1100, 1500, 1000, 1000, 1000, 1000], 25.0)],
        )

    def test_enter_failsafe_submits_failsafe_channels(self) -> None:
        dispatcher = _Dispatcher()
        config = MspServerConfig(
            rc_rate_hz=20.0,
            failsafe_channels=(1500, 1500, 900, 1500, 1000, 1000, 1000, 1000),
        )
        adapter = MspOutputAdapter(_Transport(), config)
        adapter.dispatcher = dispatcher

        with patch.object(msp_adapter, "logger", _Logger()):
            adapter.enter_failsafe("joystick data stale")

        self.assertEqual(
            dispatcher.rc_commands,
            [([1500, 1500, 900, 1500, 1000, 1000, 1000, 1000], 20.0)],
        )

    def test_read_rc_records_latest_channels(self) -> None:
        dispatcher = _Dispatcher()
        dispatcher.rc_reads.append([1000, 1500, 2000, 1500])

        with patch.object(msp_adapter, "logger", _Logger()):
            _read_rc(dispatcher, timeout=0.05)

        self.assertEqual(dispatcher.recorded_rc, [1000, 1500, 2000, 1500])

    def test_read_altitude_records_latest_altitude(self) -> None:
        dispatcher = _Dispatcher()
        altitude = MspAltitude(altitude_m=12.3, vertical_speed_m_s=-0.4)
        dispatcher.altitude_reads.append(altitude)

        with patch.object(msp_adapter, "logger", _Logger()):
            _read_altitude(dispatcher, timeout=0.05)

        self.assertEqual(dispatcher.recorded_altitude, altitude)


if __name__ == "__main__":
    unittest.main()
