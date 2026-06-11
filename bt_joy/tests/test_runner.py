import unittest
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.modules.setdefault("loguru", SimpleNamespace(logger=SimpleNamespace()))

from bt_joy.client.runner import (
    _KeepaliveRttWarningState,
    _RunnerState,
    _format_mapping_channels,
    _log_expired_keepalives,
    _log_keepalive_responses,
    _run_connected_joystick,
    _send_keepalive_if_due,
    _should_warn_keepalive_round_trip,
)
from bt_joy.client.config import ChannelConfig, JoyConfig
from bt_joy.client.joystick import JoystickReadError, JoystickState
from bt_joy.client.udp import UdpPacket
from bt_joy.protocol import pack_keepalive_response


class RunnerTest(unittest.TestCase):
    def test_keepalive_round_trip_guard_warns_after_repeated_high_rtt(self) -> None:
        state = _KeepaliveRttWarningState()

        self.assertFalse(
            _should_warn_keepalive_round_trip(101_000, now=1.0, state=state)
        )
        self.assertFalse(
            _should_warn_keepalive_round_trip(102_000, now=2.0, state=state)
        )
        self.assertTrue(
            _should_warn_keepalive_round_trip(103_000, now=3.0, state=state)
        )

    def test_keepalive_round_trip_guard_uses_cooldown(self) -> None:
        state = _KeepaliveRttWarningState()

        self.assertTrue(
            _should_warn_keepalive_round_trip(
                101_000,
                now=1.0,
                state=state,
                warning_count=1,
                cooldown_s=10.0,
            )
        )
        self.assertFalse(
            _should_warn_keepalive_round_trip(
                102_000,
                now=5.0,
                state=state,
                warning_count=1,
                cooldown_s=10.0,
            )
        )
        self.assertTrue(
            _should_warn_keepalive_round_trip(
                103_000,
                now=11.0,
                state=state,
                warning_count=1,
                cooldown_s=10.0,
            )
        )

    def test_log_keepalive_responses_warns_when_round_trip_guard_trips(self) -> None:
        client_sent_at = 1_000_000
        packets = [
            UdpPacket(
                pack_keepalive_response(sequence, client_sent_at, client_sent_at + 10_000),
                ("127.0.0.1", 9000),
            )
            for sequence in (1, 2, 3)
        ]
        sender = SimpleNamespace(receive_available=lambda: packets)
        pending = {sequence: (10.0, client_sent_at) for sequence in (1, 2, 3)}

        with patch("bt_joy.client.runner.timestamp_us", return_value=1_200_000):
            with patch("bt_joy.client.runner.time.monotonic", side_effect=[1.0, 2.0, 3.0]):
                with patch("bt_joy.client.runner.logger") as logger:
                    _log_keepalive_responses(
                        sender,
                        pending,
                        _KeepaliveRttWarningState(),
                    )

        self.assertEqual(pending, {})
        self.assertEqual(logger.debug.call_count, 2)
        logger.warning.assert_called_once_with(
            "keepalive seq={} server_delay_ms={:.3f} round_trip_ms={:.3f} server_received_at_us={}",
            3,
            10.0,
            200.0,
            1_010_000,
        )

    def test_log_expired_keepalives_logs_error_and_removes_pending(self) -> None:
        pending = {7: (10.0, 1_000_000)}

        with patch("bt_joy.client.runner.timestamp_us", return_value=1_250_000):
            with patch("bt_joy.client.runner.logger") as logger:
                _log_expired_keepalives(pending, now=10.0)

        self.assertEqual(pending, {})
        logger.error.assert_called_once_with(
            "keepalive seq={} timed out after {:.3f}ms with no server response",
            7,
            250.0,
        )

    def test_log_expired_keepalives_leaves_pending_before_deadline(self) -> None:
        pending = {7: (10.0, 1_000_000)}

        _log_expired_keepalives(pending, now=9.99)

        self.assertEqual(pending, {7: (10.0, 1_000_000)})

    def test_send_keepalive_if_due_sends_and_tracks_pending(self) -> None:
        sender = SimpleNamespace(sent=[], send=lambda payload: sender.sent.append(payload))
        state = _RunnerState(next_keepalive_at=1.0)

        with patch("bt_joy.client.runner.timestamp_us", return_value=1_000_000):
            with patch("bt_joy.client.runner.logger"):
                _send_keepalive_if_due(sender, state, now=1.0, keepalive_interval=2.0, keepalive_timeout=0.5)

        self.assertEqual(len(sender.sent), 1)
        self.assertEqual(state.pending_keepalives, {0: (1.5, 1_000_000)})
        self.assertEqual(state.keepalive_sequence, 1)
        self.assertEqual(state.next_keepalive_at, 3.0)

    def test_keepalive_send_error_is_throttled(self) -> None:
        sender = SimpleNamespace(send=Mock(side_effect=OSError("Network is unreachable")))
        state = _RunnerState(next_keepalive_at=1.0)

        with patch("bt_joy.client.runner.timestamp_us", return_value=1_000_000):
            with patch("bt_joy.client.runner.logger") as logger:
                _send_keepalive_if_due(
                    sender,
                    state,
                    now=1.0,
                    keepalive_interval=1.0,
                    keepalive_timeout=0.5,
                )
                _send_keepalive_if_due(
                    sender,
                    state,
                    now=2.0,
                    keepalive_interval=1.0,
                    keepalive_timeout=0.5,
                )

        self.assertEqual(sender.send.call_count, 2)
        logger.error.assert_called_once_with(
            "keepalive seq={} send failed: {}",
            0,
            sender.send.side_effect,
        )
        self.assertEqual(state.keepalive_sequence, 2)

    def test_connected_joystick_loop_exits_on_read_error_after_sending_frame(self) -> None:
        config = JoyConfig(
            poll_hz=50.0,
            channels=(ChannelConfig(name="throttle", source="constant", value=1000),),
            keepalive_interval=0.0,
        )
        joystick = SimpleNamespace(
            poll=Mock(
                side_effect=[
                    JoystickState(axes=[], buttons=[]),
                    JoystickReadError("gone"),
                ]
            ),
        )
        sender = SimpleNamespace(
            sent=[],
            send=lambda payload: sender.sent.append(payload),
            receive_available=lambda: [],
        )
        state = _RunnerState()

        with patch("bt_joy.client.runner.time.sleep"):
            with self.assertRaises(JoystickReadError):
                _run_connected_joystick(
                    config,
                    joystick,
                    sender,
                    state,
                    ["throttle"],
                    period=0.02,
                    log_mapping=False,
                    keepalive_interval=0.0,
                    keepalive_timeout=1.0,
                )

        self.assertEqual(len(sender.sent), 1)
        self.assertEqual(state.sequence, 1)

    def test_joystick_frame_send_error_is_throttled(self) -> None:
        config = JoyConfig(
            poll_hz=50.0,
            channels=(ChannelConfig(name="throttle", source="constant", value=1000),),
            keepalive_interval=0.0,
        )
        joystick = SimpleNamespace(
            poll=Mock(
                side_effect=[
                    JoystickState(axes=[], buttons=[]),
                    JoystickState(axes=[], buttons=[]),
                    JoystickReadError("stop"),
                ]
            ),
        )
        sender = SimpleNamespace(
            send=Mock(side_effect=OSError("Network is unreachable")),
            receive_available=lambda: [],
        )
        state = _RunnerState()

        with patch("bt_joy.client.runner.time.sleep"):
            with patch("bt_joy.client.runner.logger") as logger:
                with self.assertRaises(JoystickReadError):
                    _run_connected_joystick(
                        config,
                        joystick,
                        sender,
                        state,
                        ["throttle"],
                        period=0.02,
                        log_mapping=False,
                        keepalive_interval=0.0,
                        keepalive_timeout=1.0,
                    )

        self.assertEqual(sender.send.call_count, 2)
        logger.error.assert_called_once_with(
            "joystick frame seq={} send failed: {}",
            0,
            sender.send.side_effect,
        )
        self.assertEqual(state.sequence, 0)

    def test_log_mapping_skips_keepalive_and_udp_send(self) -> None:
        config = JoyConfig(
            poll_hz=50.0,
            channels=(ChannelConfig(name="throttle", source="constant", value=1000),),
            keepalive_interval=1.0,
        )
        joystick = SimpleNamespace(
            poll=Mock(
                side_effect=[
                    JoystickState(axes=[], buttons=[]),
                    JoystickReadError("stop"),
                ]
            ),
        )
        sender = SimpleNamespace(
            send=Mock(),
            receive_available=Mock(return_value=[]),
        )
        state = _RunnerState(next_keepalive_at=0.0)

        with patch("bt_joy.client.runner.time.sleep"):
            with patch("bt_joy.client.runner.logger"):
                with self.assertRaises(JoystickReadError):
                    _run_connected_joystick(
                        config,
                        joystick,
                        sender,
                        state,
                        ["throttle"],
                        period=0.02,
                        log_mapping=True,
                        keepalive_interval=1.0,
                        keepalive_timeout=1.0,
                    )

        sender.send.assert_not_called()
        sender.receive_available.assert_not_called()
        self.assertEqual(state.pending_keepalives, {})

    def test_format_mapping_channels_colors_changed_values(self) -> None:
        formatted = _format_mapping_channels(
            ["roll", "pitch", "throttle"],
            [1500, 1600, 1000],
            [1500, 1500, 1000],
        )

        self.assertEqual(formatted, "roll=1500 <yellow>pitch=1600</yellow> throttle=1000")

    def test_format_mapping_channels_colors_all_values_without_previous(self) -> None:
        formatted = _format_mapping_channels(
            ["roll", "pitch"],
            [1500, 1600],
            None,
        )

        self.assertEqual(formatted, "<yellow>roll=1500</yellow> <yellow>pitch=1600</yellow>")


if __name__ == "__main__":
    unittest.main()
