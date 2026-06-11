import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.modules.setdefault("loguru", SimpleNamespace(logger=SimpleNamespace()))

from bt_joy.server.config import TakeoffAutomationConfig
from bt_joy.server.controller import JoystickController, JoystickFrame
from bt_joy.server.msp import MspAltitude
from bt_joy.server.state import RcChannel


class _Adapter:
    def __init__(self) -> None:
        self.writes = []
        self.failsafe_entries = []
        self.failsafe_exits = 0
        self.ticks = 0

    def write_channels(self, channels, sequence, timestamp_us) -> None:
        self.writes.append((channels, sequence, timestamp_us))

    def enter_failsafe(self, reason: str) -> None:
        self.failsafe_entries.append(reason)

    def exit_failsafe(self) -> None:
        self.failsafe_exits += 1

    def tick(self) -> None:
        self.ticks += 1


class ControllerTest(unittest.TestCase):
    def test_handle_frame_passes_through_and_updates_manual_output_state(self) -> None:
        adapter = _Adapter()
        controller = JoystickController(adapter)
        frame = JoystickFrame(
            channels=(1500, 1500, 1234, 1500),
            sequence=9,
            timestamp_us=123456,
            source=("127.0.0.1", 9000),
        )

        with patch("bt_joy.server.state.time.monotonic", side_effect=[10.0, 11.0]):
            handled = controller.handle_frame(frame)

        self.assertTrue(handled)
        self.assertEqual(adapter.writes, [([1500, 1500, 1234, 1500], 9, 123456)])
        snapshot = controller.state_store.snapshot()
        self.assertEqual(snapshot.manual_throttle, 1234)
        self.assertEqual(snapshot.manual_channels_at, 10.0)
        self.assertEqual(snapshot.output_channel(RcChannel.THROTTLE), 1234)
        self.assertEqual(snapshot.output_channels_at, 11.0)

    def test_delegates_failsafe_and_tick_to_adapter(self) -> None:
        adapter = _Adapter()
        controller = JoystickController(adapter)

        controller.enter_failsafe("stale")
        controller.exit_failsafe()
        controller.tick()

        self.assertEqual(adapter.failsafe_entries, ["stale"])
        self.assertEqual(adapter.failsafe_exits, 1)
        self.assertEqual(adapter.ticks, 1)

    def test_aux4_takeoff_automation_arms_and_climbs(self) -> None:
        adapter = _Adapter()
        controller = JoystickController(
            adapter,
            takeoff_automation_config=TakeoffAutomationConfig(
                enabled=True,
                target_altitude_m=5.0,
                throttle_base=1200,
                throttle_min=1000,
                throttle_max=1800,
                pid_kp=50.0,
                pid_ki=0.0,
                pid_kd=0.0,
            ),
        )
        controller.state_store.update_altitude(MspAltitude(altitude_m=0.0, vertical_speed_m_s=0.0))
        frame = JoystickFrame(
            channels=(1500, 1500, 1200, 1500, 1000, 1000, 1000, 2000),
            sequence=1,
            timestamp_us=100,
            source=("127.0.0.1", 9000),
        )

        with patch("bt_joy.server.automation.logger") as logger, patch(
            "bt_joy.server.automation.time.monotonic",
            return_value=10.0,
        ):
            handled = controller.handle_frame(frame)

        self.assertTrue(handled)
        logger.warning.assert_called_once_with(
            "takeoff automation entered automatic control mode altitude_m={:.2f} "
            "target_altitude_m={:.2f} manual_throttle={} pid_throttle={}",
            0.0,
            5.0,
            1200,
            1450,
        )
        self.assertEqual(
            adapter.writes,
            [([1500, 1500, 1450, 1500, 2000, 1000, 1000, 2000], 1, 100)],
        )
        snapshot = controller.state_store.snapshot()
        self.assertEqual(snapshot.manual_channel(RcChannel.AUX1), 1000)
        self.assertEqual(snapshot.output_channel(RcChannel.AUX1), 2000)
        self.assertEqual(snapshot.output_throttle, 1450)

    def test_takeoff_automation_uses_pid_floor_until_aux4_release(self) -> None:
        adapter = _Adapter()
        controller = JoystickController(
            adapter,
            takeoff_automation_config=TakeoffAutomationConfig(
                enabled=True,
                target_altitude_m=5.0,
                throttle_base=1300,
                throttle_min=1000,
                throttle_max=1800,
                pid_kp=100.0,
                pid_ki=0.0,
                pid_kd=0.0,
            ),
        )
        controller.state_store.update_altitude(MspAltitude(altitude_m=4.0, vertical_speed_m_s=0.0))

        with patch("bt_joy.server.automation.logger"), patch("bt_joy.server.automation.time.monotonic", return_value=10.0):
            controller.handle_frame(
                JoystickFrame(
                    channels=(1500, 1500, 1200, 1500, 1000, 1000, 1000, 2000),
                    sequence=1,
                    timestamp_us=100,
                    source=("127.0.0.1", 9000),
                )
            )
            controller.state_store.update_altitude(MspAltitude(altitude_m=5.0, vertical_speed_m_s=0.0))
            controller.handle_frame(
                JoystickFrame(
                    channels=(1500, 1500, 1550, 1500, 1000, 1000, 1000, 2000),
                    sequence=2,
                    timestamp_us=200,
                    source=("127.0.0.1", 9000),
                )
            )
            controller.handle_frame(
                JoystickFrame(
                    channels=(1500, 1500, 1100, 1500, 1000, 1000, 1000, 1000),
                    sequence=3,
                    timestamp_us=300,
                    source=("127.0.0.1", 9000),
                )
            )

        self.assertEqual(adapter.writes[0], ([1500, 1500, 1400, 1500, 2000, 1000, 1000, 2000], 1, 100))
        self.assertEqual(adapter.writes[1], ([1500, 1500, 1550, 1500, 2000, 1000, 1000, 2000], 2, 200))
        self.assertEqual(adapter.writes[2], ([1500, 1500, 1100, 1500, 1000, 1000, 1000, 1000], 3, 300))

    def test_takeoff_automation_logs_automatic_control_entry_once(self) -> None:
        adapter = _Adapter()
        controller = JoystickController(
            adapter,
            takeoff_automation_config=TakeoffAutomationConfig(
                enabled=True,
                target_altitude_m=5.0,
                throttle_base=1300,
                pid_kp=100.0,
                pid_ki=0.0,
                pid_kd=0.0,
            ),
        )
        controller.state_store.update_altitude(MspAltitude(altitude_m=4.0, vertical_speed_m_s=0.0))

        with patch("bt_joy.server.automation.logger") as logger, patch(
            "bt_joy.server.automation.time.monotonic",
            return_value=10.0,
        ):
            controller.handle_frame(
                JoystickFrame(
                    channels=(1500, 1500, 1200, 1500, 1000, 1000, 1000, 2000),
                    sequence=1,
                    timestamp_us=100,
                    source=("127.0.0.1", 9000),
                )
            )
            controller.handle_frame(
                JoystickFrame(
                    channels=(1500, 1500, 1200, 1500, 1000, 1000, 1000, 2000),
                    sequence=2,
                    timestamp_us=200,
                    source=("127.0.0.1", 9000),
                )
            )

        automatic_control_logs = [
            call
            for call in logger.warning.call_args_list
            if call.args[0].startswith("takeoff automation entered automatic control mode")
        ]
        self.assertEqual(len(automatic_control_logs), 1)

    def test_takeoff_automation_waits_for_altitude_before_arming(self) -> None:
        adapter = _Adapter()
        controller = JoystickController(
            adapter,
            takeoff_automation_config=TakeoffAutomationConfig(enabled=True),
        )

        with patch("bt_joy.server.automation.logger"):
            controller.handle_frame(
                JoystickFrame(
                    channels=(1500, 1500, 1200, 1500, 1000, 1000, 1000, 2000),
                    sequence=1,
                    timestamp_us=100,
                    source=("127.0.0.1", 9000),
                )
            )

        self.assertEqual(
            adapter.writes,
            [([1500, 1500, 1200, 1500, 1000, 1000, 1000, 2000], 1, 100)],
        )

    def test_takeoff_automation_can_require_manual_arm(self) -> None:
        adapter = _Adapter()
        controller = JoystickController(
            adapter,
            takeoff_automation_config=TakeoffAutomationConfig(
                enabled=True,
                require_manual_arm=True,
                target_altitude_m=5.0,
            ),
        )

        with patch("bt_joy.server.automation.logger"):
            controller.handle_frame(
                JoystickFrame(
                    channels=(1500, 1500, 1200, 1500, 1000, 1000, 1000, 2000),
                    sequence=1,
                    timestamp_us=100,
                    source=("127.0.0.1", 9000),
                )
            )

        self.assertEqual(
            adapter.writes,
            [([1500, 1500, 1200, 1500, 1000, 1000, 1000, 2000], 1, 100)],
        )


if __name__ == "__main__":
    unittest.main()
