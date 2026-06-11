import unittest
from pathlib import Path
from unittest.mock import patch

from bt_joy.client.joystick import (
    JoystickNameMismatchError,
    JoystickOpenError,
    JoystickReadError,
    JoystickReader,
)


class JoystickReaderTest(unittest.TestCase):
    def test_open_raises_clear_error_when_device_is_missing(self) -> None:
        reader = JoystickReader(Path("/dev/input/missing-js"))

        with patch("bt_joy.client.joystick.os.open", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(JoystickOpenError, "joystick device not found"):
                reader.open()

    def test_open_raises_clear_error_when_permission_denied(self) -> None:
        reader = JoystickReader(Path("/dev/input/js0"))

        with patch("bt_joy.client.joystick.os.open", side_effect=PermissionError):
            with self.assertRaisesRegex(JoystickOpenError, "permission denied"):
                reader.open()

    def test_open_raises_when_expected_name_does_not_match(self) -> None:
        reader = JoystickReader(Path("/dev/input/js0"), expected_name="Expected Controller")

        with patch("bt_joy.client.joystick.os.open", return_value=10):
            with patch("bt_joy.client.joystick.os.close"):
                with patch("bt_joy.client.joystick.read_joystick_name", return_value="Other Controller"):
                    with self.assertRaisesRegex(JoystickNameMismatchError, "joystick name mismatch"):
                        reader.open()

    def test_open_stores_joystick_name(self) -> None:
        reader = JoystickReader(Path("/dev/input/js0"), expected_name="Expected Controller")

        with patch("bt_joy.client.joystick.os.open", return_value=10):
            with patch("bt_joy.client.joystick.os.close"):
                with patch("bt_joy.client.joystick.read_joystick_name", return_value="Expected Controller"):
                    reader.open()

        self.assertEqual(reader.name, "Expected Controller")

    def test_open_raises_clear_error_when_name_read_fails(self) -> None:
        reader = JoystickReader(Path("/dev/input/js0"))

        with patch("bt_joy.client.joystick.os.open", return_value=10):
            with patch("bt_joy.client.joystick.os.close"):
                with patch("bt_joy.client.joystick.read_joystick_name", side_effect=OSError("gone")):
                    with self.assertRaisesRegex(JoystickOpenError, "failed to read joystick name"):
                        reader.open()

    def test_poll_raises_clear_error_when_select_fails(self) -> None:
        reader = JoystickReader(Path("/dev/input/js0"))
        reader._fd = 10

        with patch("bt_joy.client.joystick.select.select", side_effect=OSError("gone")):
            with self.assertRaisesRegex(JoystickReadError, "failed to poll joystick device"):
                reader.poll()

    def test_poll_raises_clear_error_when_read_fails(self) -> None:
        reader = JoystickReader(Path("/dev/input/js0"))
        reader._fd = 10

        with patch("bt_joy.client.joystick.select.select", return_value=([10], [], [])):
            with patch("bt_joy.client.joystick.os.read", side_effect=OSError("gone")):
                with self.assertRaisesRegex(JoystickReadError, "failed to read joystick device"):
                    reader.poll()

    def test_close_ignores_os_error(self) -> None:
        reader = JoystickReader(Path("/dev/input/js0"))
        reader._fd = 10

        with patch("bt_joy.client.joystick.os.close", side_effect=OSError("bad fd")):
            reader.close()

        self.assertIsNone(reader._fd)


if __name__ == "__main__":
    unittest.main()
