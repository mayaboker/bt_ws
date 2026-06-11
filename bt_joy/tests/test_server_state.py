import unittest
from unittest.mock import patch

from bt_joy.server.msp import MspAltitude, MspStatus
from bt_joy.server.state import RcChannel, ServerStateStore


class ServerStateStoreTest(unittest.TestCase):
    def test_snapshot_returns_named_channel_values(self) -> None:
        store = ServerStateStore()
        status = MspStatus(
            cycle_time_us=250,
            i2c_errors=0,
            sensors_mask=1,
            box_mode_flags=2,
        )
        altitude = MspAltitude(altitude_m=12.34, vertical_speed_m_s=-0.5)

        with patch("bt_joy.server.state.time.monotonic", side_effect=[10.0, 11.0, 12.0, 13.0]):
            store.update_commanded_channels([1500, 1500, 1234, 1500])
            store.update_fc_rc_channels([1500, 1500, 1200, 1500])
            store.update_status(status)
            store.update_altitude(altitude)

        snapshot = store.snapshot()

        self.assertEqual(snapshot.commanded_channel(RcChannel.THROTTLE), 1234)
        self.assertEqual(snapshot.commanded_throttle, 1234)
        self.assertEqual(snapshot.commanded_channels_at, 10.0)
        self.assertEqual(snapshot.fc_rc_channel(RcChannel.THROTTLE), 1200)
        self.assertEqual(snapshot.fc_rc_throttle, 1200)
        self.assertEqual(snapshot.fc_rc_channels_at, 11.0)
        self.assertEqual(snapshot.status, status)
        self.assertEqual(snapshot.status_at, 12.0)
        self.assertEqual(snapshot.altitude, altitude)
        self.assertEqual(snapshot.altitude_at, 13.0)

    def test_named_channel_returns_none_when_missing(self) -> None:
        snapshot = ServerStateStore().snapshot()

        self.assertIsNone(snapshot.commanded_channel(RcChannel.THROTTLE))
        self.assertIsNone(snapshot.fc_rc_channel(RcChannel.THROTTLE))


if __name__ == "__main__":
    unittest.main()
