import tempfile
import textwrap
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

sys.modules.setdefault("loguru", SimpleNamespace(logger=SimpleNamespace()))

from bt_joy.client.main import _load_config, _resolve_mapping_path
from bt_joy.client.main import main as client_main


class ClientMainTest(unittest.TestCase):
    def test_help_includes_host_and_mapping_example(self) -> None:
        from click.testing import CliRunner

        result = CliRunner().invoke(client_main, ["--help"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn(
            "bt-joy --config /etc/bt-joy/client.yaml --mapping ./xbox.yaml --host 192.168.1.50",
            result.output,
        )
        self.assertIn(
            "bt-joy --host 192.168.1.50 --port 9000 --print-config > client.yaml",
            result.output,
        )

    def test_load_config_loads_mapping_from_config_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            config_path = base / "client.yaml"
            mapping_path = base / "mapping.yaml"
            config_path.write_text(
                textwrap.dedent(
                    """
                    mapping: mapping.yaml
                    channels:
                      - name: legacy
                        source: constant
                        value: 1000
                    """
                ),
                encoding="utf-8",
            )
            mapping_path.write_text(
                textwrap.dedent(
                    """
                    channels:
                      - name: mapped
                        source: constant
                        value: 1500
                    """
                ),
                encoding="utf-8",
            )

            config, loaded_config_path, loaded_mapping_path = _load_config(str(config_path), None)

        self.assertEqual(loaded_config_path, str(config_path.resolve()))
        self.assertEqual(loaded_mapping_path, str(mapping_path.resolve()))
        self.assertEqual(len(config.channels), 1)
        self.assertEqual(config.channels[0].name, "mapped")

    def test_load_config_uses_mapping_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            config_path = base / "client.yaml"
            configured_mapping_path = base / "configured.yaml"
            override_mapping_path = base / "override.yaml"
            config_path.write_text("mapping: configured.yaml\n", encoding="utf-8")
            configured_mapping_path.write_text(
                "channels:\n  - name: configured\n    source: constant\n    value: 1000\n",
                encoding="utf-8",
            )
            override_mapping_path.write_text(
                "channels:\n  - name: override\n    source: constant\n    value: 1600\n",
                encoding="utf-8",
            )

            config, _loaded_config_path, loaded_mapping_path = _load_config(
                str(config_path),
                str(override_mapping_path),
            )

        self.assertEqual(loaded_mapping_path, str(override_mapping_path.resolve()))
        self.assertEqual(config.channels[0].name, "override")

    def test_resolve_mapping_path_uses_config_directory(self) -> None:
        config_path = Path("/tmp/bt-joy/client.yaml")

        mapping_path = _resolve_mapping_path(None, "mapping.yaml", config_path)

        self.assertEqual(mapping_path, Path("/tmp/bt-joy/mapping.yaml"))

    def test_print_config_outputs_effective_yaml_and_does_not_run(self) -> None:
        from click.testing import CliRunner

        with patch("bt_joy.client.main.run") as run:
            result = CliRunner().invoke(
                client_main,
                [
                    "--host",
                    "192.168.1.50",
                    "--port",
                    "9001",
                    "--poll-hz",
                    "25",
                    "--print-config",
                ],
            )

        self.assertEqual(result.exit_code, 0)
        run.assert_not_called()
        data = yaml.safe_load(result.output)
        self.assertEqual(data["udp"]["host"], "192.168.1.50")
        self.assertEqual(data["udp"]["port"], 9001)
        self.assertEqual(data["poll_hz"], 25.0)
        self.assertIn("joystick_reconnect_interval", data)
        self.assertIn("mapping", data)

    def test_calibration_calls_calibrator_and_does_not_run(self) -> None:
        from click.testing import CliRunner

        with patch("bt_joy.client.main.run") as run:
            with patch(
                "bt_joy.client.main.run_calibration",
                return_value=(Path("output/joy/My Joystick.yaml"), Path("output/joy/My Joystick_mapping.yaml")),
            ) as run_calibration:
                result = CliRunner().invoke(client_main, ["--calibration"])

        self.assertEqual(result.exit_code, 0)
        run.assert_not_called()
        run_calibration.assert_called_once()
        self.assertIn("Wrote output/joy/My Joystick.yaml", result.output)
        self.assertIn("Wrote output/joy/My Joystick_mapping.yaml", result.output)

    def test_calibration_receives_device_override(self) -> None:
        from click.testing import CliRunner

        with patch(
            "bt_joy.client.main.run_calibration",
            return_value=(Path("output/joy/My Joystick.yaml"), Path("output/joy/My Joystick_mapping.yaml")),
        ) as run_calibration:
            result = CliRunner().invoke(
                client_main,
                ["--calibration", "--device", "/dev/input/js-test"],
            )

        self.assertEqual(result.exit_code, 0)
        joy_config = run_calibration.call_args.args[0]
        self.assertEqual(joy_config.device, "/dev/input/js-test")


if __name__ == "__main__":
    unittest.main()
