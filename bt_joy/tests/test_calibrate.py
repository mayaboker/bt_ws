import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from bt_joy.client.calibrate import CalibrationError
from bt_joy.client.calibrate import detect_changed_input, is_valid_config_prefix, run_calibration
from bt_joy.client.config import JoyConfig, UdpConfig
from bt_joy.client.joystick import JoystickState


class FakeJoystickReader:
    states: list[JoystickState] = []
    instances: list["FakeJoystickReader"] = []

    def __init__(
        self,
        device: str,
        axis_count: int = 7,
        button_count: int = 16,
    ) -> None:
        self.device = device
        self.axis_count = axis_count
        self.button_count = button_count
        self.name = "My Joystick"
        self.polls = list(self.states)
        self.instances.append(self)

    def __enter__(self) -> "FakeJoystickReader":
        return self

    def __exit__(self, *_exc: object) -> None:
        pass

    def poll(self) -> JoystickState:
        return self.polls.pop(0)


class CalibrateTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeJoystickReader.states = []
        FakeJoystickReader.instances = []

    def test_detect_changed_axis(self) -> None:
        detected = detect_changed_input(
            JoystickState(axes=[0, -32767], buttons=[]),
            JoystickState(axes=[0, 32767], buttons=[]),
        )

        self.assertEqual(detected, ("axis", 1, -32767, 32767))

    def test_detect_changed_button(self) -> None:
        detected = detect_changed_input(
            JoystickState(axes=[0], buttons=[0, 0]),
            JoystickState(axes=[0], buttons=[0, 1]),
        )

        self.assertEqual(detected, ("button", 1))

    def test_detect_rejects_no_change(self) -> None:
        with self.assertRaisesRegex(CalibrationError, "no joystick input changed"):
            detect_changed_input(
                JoystickState(axes=[0], buttons=[0]),
                JoystickState(axes=[0], buttons=[0]),
            )

    def test_detect_rejects_ambiguous_equal_axis_change(self) -> None:
        with self.assertRaisesRegex(CalibrationError, "multiple axis inputs changed"):
            detect_changed_input(
                JoystickState(axes=[0, 0], buttons=[]),
                JoystickState(axes=[2000, 2000], buttons=[]),
            )

    def test_config_prefix_validation_rejects_spaces_and_illegal_characters(self) -> None:
        self.assertTrue(is_valid_config_prefix("beta_fpv-1.0"))
        self.assertFalse(is_valid_config_prefix(""))
        self.assertFalse(is_valid_config_prefix("beta fpv"))
        self.assertFalse(is_valid_config_prefix("beta/fpv"))
        self.assertFalse(is_valid_config_prefix("beta:fpv"))

    def test_run_calibration_writes_client_and_mapping_yaml(self) -> None:
        FakeJoystickReader.states = [
            JoystickState(axes=[-32767, 0, 0, 0], buttons=[0, 0]),
            JoystickState(axes=[32767, 0, 0, 0], buttons=[0, 0]),
            JoystickState(axes=[0, -32767, 0, 0], buttons=[0, 0]),
            JoystickState(axes=[0, 32767, 0, 0], buttons=[0, 0]),
            JoystickState(axes=[0, 0, -32767, 0], buttons=[0, 0]),
            JoystickState(axes=[0, 0, 32767, 0], buttons=[0, 0]),
            JoystickState(axes=[0, 0, 0, -32767], buttons=[0, 0]),
            JoystickState(axes=[0, 0, 0, 32767], buttons=[0, 0]),
            JoystickState(axes=[0, 0, 0, 0], buttons=[0, 0]),
            JoystickState(axes=[0, 0, 0, 0], buttons=[1, 0]),
            JoystickState(axes=[0, 0, 0, 0], buttons=[0, 0]),
            JoystickState(axes=[0, 0, 0, 0], buttons=[0, 1]),
        ]
        prompts = []
        messages = []
        config_names = iter(["bad name", "bad/name", "beta_fpv"])

        def input_func(prompt: str) -> str:
            prompts.append(prompt)
            if prompt == "Enter config file name: ":
                return next(config_names)
            return ""

        with tempfile.TemporaryDirectory() as temp_dir:
            config = JoyConfig(
                device="/dev/input/js-test",
                expected_name="Old Joystick",
                mapping="old_mapping.yaml",
                poll_hz=25.0,
                axes=4,
                buttons=2,
                udp=UdpConfig(host="192.168.1.10", port=9001),
            )
            with patch("bt_joy.client.calibrate.JoystickReader", FakeJoystickReader):
                client_path, mapping_path = run_calibration(
                    config,
                    Path(temp_dir),
                    input_func,
                    messages.append,
                )

            client_data = yaml.safe_load(client_path.read_text(encoding="utf-8"))
            mapping_data = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))

        self.assertEqual(FakeJoystickReader.instances[0].device, "/dev/input/js-test")
        self.assertEqual(FakeJoystickReader.instances[0].axis_count, 4)
        self.assertEqual(FakeJoystickReader.instances[0].button_count, 2)
        self.assertEqual(client_data["expected_name"], "My Joystick")
        self.assertEqual(client_path.name, "beta_fpv.yaml")
        self.assertEqual(mapping_path.name, "beta_fpv_mapping.yaml")
        self.assertEqual(client_data["mapping"], "beta_fpv_mapping.yaml")
        self.assertEqual(client_data["poll_hz"], 25.0)
        self.assertEqual(client_data["udp"]["host"], "192.168.1.10")
        self.assertEqual(client_data["udp"]["port"], 9001)
        self.assertEqual([channel["name"] for channel in mapping_data["channels"]], [
            "roll",
            "pitch",
            "throttle",
            "yaw",
            "arm",
            "aux2",
        ])
        self.assertEqual(mapping_data["channels"][0]["source"], "axis")
        self.assertEqual(mapping_data["channels"][0]["index"], 0)
        self.assertEqual(mapping_data["channels"][0]["deadband"], 0.03)
        self.assertEqual(mapping_data["channels"][4]["source"], "button")
        self.assertEqual(mapping_data["channels"][4]["index"], 0)
        self.assertEqual(prompts[:3], ["Enter config file name: "] * 3)
        self.assertIn("Put roll in minimum position", prompts[3])
        self.assertEqual(len(messages), 8)
        self.assertIn("Invalid config file name", messages[0])
        self.assertIn("Invalid config file name", messages[1])
        self.assertIn("Calibrating roll", messages[2])
        self.assertIn("\033[96m", messages[2])


if __name__ == "__main__":
    unittest.main()
