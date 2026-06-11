import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bt_joy.protocol import pack_frame, pack_keepalive_request, unpack_keepalive_response

sys.modules.setdefault("loguru", SimpleNamespace(logger=SimpleNamespace()))

from bt_joy.server.controller import JoystickController
from bt_joy.server.udp_server import FailsafeMonitor, handle_keepalive_packet, parse_joystick_packet


class _Adapter:
    def __init__(self) -> None:
        self.writes = []
        self.failsafe_entries = []
        self.failsafe_exits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_exc: object) -> None:
        pass

    def startup_check(self) -> None:
        pass

    def write_channels(self, channels, sequence, timestamp_us) -> None:
        self.writes.append((channels, sequence, timestamp_us))

    def enter_failsafe(self, reason: str) -> None:
        self.failsafe_entries.append(reason)

    def exit_failsafe(self) -> None:
        self.failsafe_exits += 1

    def tick(self) -> None:
        pass


class _UdpSocket:
    def __init__(self) -> None:
        self.sent = []

    def sendto(self, payload: bytes, address: tuple[str, int]) -> None:
        self.sent.append((payload, address))


class UdpServerTest(unittest.TestCase):
    def test_parse_joystick_packet_returns_frame(self) -> None:
        payload = pack_frame([1000, 1500, 2000], sequence=7, timestamp=123456)

        with patch("bt_joy.server.udp_server.logger"):
            frame = parse_joystick_packet(payload, ("127.0.0.1", 9000))

        self.assertIsNotNone(frame)
        self.assertEqual(frame.channels, (1000, 1500, 2000))
        self.assertEqual(frame.sequence, 7)
        self.assertEqual(frame.timestamp_us, 123456)
        self.assertEqual(frame.source, ("127.0.0.1", 9000))

    def test_handle_joystick_packet_ignores_invalid_payload(self) -> None:
        with patch("bt_joy.server.udp_server.logger"):
            frame = parse_joystick_packet(b"bad", ("127.0.0.1", 9000))

        self.assertIsNone(frame)

    def test_controller_writes_parsed_channels_to_adapter(self) -> None:
        adapter = _Adapter()
        controller = JoystickController(adapter)
        with patch("bt_joy.server.udp_server.logger"):
            frame = parse_joystick_packet(
                pack_frame([1000, 1500, 2000], sequence=7, timestamp=123456),
                ("127.0.0.1", 9000),
            )

        self.assertIsNotNone(frame)
        handled = controller.handle_frame(frame)

        self.assertTrue(handled)
        self.assertEqual(adapter.writes, [([1000, 1500, 2000], 7, 123456)])

    def test_handle_keepalive_packet_sends_response(self) -> None:
        udp_socket = _UdpSocket()
        payload = pack_keepalive_request(sequence=9, timestamp=1000)

        with patch("bt_joy.server.udp_server.logger"):
            handled = handle_keepalive_packet(udp_socket, payload, ("127.0.0.1", 9000))

        self.assertTrue(handled)
        self.assertEqual(len(udp_socket.sent), 1)
        response, address = udp_socket.sent[0]
        sequence, client_sent_at, server_received_at, delay_us = unpack_keepalive_response(response)
        self.assertEqual(address, ("127.0.0.1", 9000))
        self.assertEqual(sequence, 9)
        self.assertEqual(client_sent_at, 1000)
        self.assertGreaterEqual(server_received_at, 1000)
        self.assertGreaterEqual(delay_us, 0)

    def test_failsafe_monitor_enters_when_joystick_data_is_stale(self) -> None:
        adapter = _Adapter()
        monitor = FailsafeMonitor(
            joystick_timeout=1.0,
            last_joystick_at=10.0,
        )

        with patch("bt_joy.server.udp_server.time.monotonic", return_value=11.1):
            monitor.evaluate(JoystickController(adapter))

        self.assertTrue(monitor.in_failsafe)
        self.assertEqual(len(adapter.failsafe_entries), 1)
        self.assertIn("joystick data stale", adapter.failsafe_entries[0])

    def test_failsafe_monitor_exits_after_data_recovers(self) -> None:
        adapter = _Adapter()
        monitor = FailsafeMonitor(
            joystick_timeout=1.0,
            last_joystick_at=10.0,
            in_failsafe=True,
        )

        with patch("bt_joy.server.udp_server.time.monotonic", return_value=10.5):
            monitor.record_joystick()
            monitor.evaluate(JoystickController(adapter))

        self.assertFalse(monitor.in_failsafe)
        self.assertEqual(adapter.failsafe_exits, 1)


if __name__ == "__main__":
    unittest.main()
