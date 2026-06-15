import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import yaml


class _Logger:
    def remove(self) -> None:
        pass

    def add(self, *_args, **_kwargs) -> None:
        pass

    def info(self, *_args, **_kwargs) -> None:
        pass

    def error(self, *_args, **_kwargs) -> None:
        pass

    def warning(self, *_args, **_kwargs) -> None:
        pass

    def debug(self, *_args, **_kwargs) -> None:
        pass


sys.modules.setdefault("loguru", SimpleNamespace(logger=_Logger()))

from click.testing import CliRunner

import bt_joy.server.joy_server as joy_server
import bt_joy.server.cli as server_cli
import bt_joy.server.adapters.msp as msp_adapter
from bt_joy.server.adapters.msp import StartupProbeError, _read_startup_info
from bt_joy.server.joy_server import ServerCliArgs, ServerConfigError


server_main = server_cli.main


class _RefusedTransport:
    def __enter__(self):
        raise ConnectionRefusedError(111, "Connection refused")

    def __exit__(self, *_exc: object) -> None:
        pass


class _StartupClient:
    def __init__(self, api_failures: int = 0) -> None:
        self.api_failures = api_failures
        self.api_reads = 0

    def read_api_version(self, timeout: float):
        self.api_reads += 1
        if self.api_reads <= self.api_failures:
            raise TimeoutError("api timeout")
        return "1.48 protocol=0"

    def read_fc_variant(self, timeout: float):
        return "BTFL"

    def read_fc_version(self, timeout: float):
        return "4.5.2"

    def read_board_info(self, timeout: float):
        raise TimeoutError("board timeout")

    def read_build_info(self, timeout: float):
        raise TimeoutError("build timeout")

    def read_status(self, timeout: float):
        raise TimeoutError("status timeout")


def make_server_args(**overrides) -> ServerCliArgs:
    values = {
        "config": None,
        "adapter": None,
        "listen_host": None,
        "listen_port": None,
        "output_kind": None,
        "tcp_host": None,
        "tcp_port": None,
        "serial_device": None,
        "baudrate": None,
        "rc_rate_hz": None,
        "status_interval": None,
        "status_timeout": None,
        "rc_read_interval": None,
        "rc_read_timeout": None,
        "altitude_interval": None,
        "altitude_timeout": None,
        "udp_timeout": None,
        "failsafe_joystick_timeout": None,
        "print_config": True,
        "log_level": None,
    }
    values.update(overrides)
    return ServerCliArgs(**values)


class ServerMainTest(unittest.TestCase):
    def test_help_includes_print_config_example(self) -> None:
        result = CliRunner().invoke(server_main, ["--help"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn(
            "joy-server --adapter crossfire --print-config > crossfire-server.yaml",
            result.output,
        )

    def test_startup_probe_retries_required_reads(self) -> None:
        client = _StartupClient(api_failures=2)

        with patch("bt_joy.server.adapters.msp.time.sleep") as sleep, patch.object(
            msp_adapter,
            "logger",
            _Logger(),
        ):
            _read_startup_info(client, timeout=0.1, attempts=3, interval_s=0.25)

        self.assertEqual(client.api_reads, 3)
        self.assertEqual(sleep.call_count, 2)
        sleep.assert_called_with(0.25)

    def test_startup_probe_fails_after_required_read_attempts(self) -> None:
        client = _StartupClient(api_failures=3)

        with patch("bt_joy.server.adapters.msp.time.sleep") as sleep, patch.object(
            msp_adapter,
            "logger",
            _Logger(),
        ):
            with self.assertRaisesRegex(
                StartupProbeError,
                "MSP_API_VERSION read failed after 3 attempts",
            ):
                _read_startup_info(client, timeout=0.1, attempts=3, interval_s=0.25)

        self.assertEqual(client.api_reads, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_connection_refused_exits_with_click_error(self) -> None:
        with patch(
            "bt_joy.server.joy_server._make_transport",
            return_value=_RefusedTransport(),
        ), patch.object(joy_server, "logger", _Logger()):
            result = CliRunner().invoke(server_main, [])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Error: MSP output connection refused: tcp://127.0.0.1:5761", result.output)
        self.assertNotIn("Traceback", result.output)

    def test_print_config_outputs_effective_yaml_and_does_not_open_transport(self) -> None:
        with patch("bt_joy.server.joy_server._make_transport") as make_transport:
            result = CliRunner().invoke(
                server_main,
                [
                    "--output",
                    "serial",
                    "--serial-device",
                    "/dev/ttyUSB0",
                    "--baudrate",
                    "115200",
                    "--listen-port",
                    "9001",
                    "--print-config",
                ],
            )

        self.assertEqual(result.exit_code, 0)
        make_transport.assert_not_called()
        data = yaml.safe_load(result.output)
        self.assertEqual(data["output"], "serial")
        self.assertEqual(data["serial_device"], "/dev/ttyUSB0")
        self.assertEqual(data["baudrate"], 115200)
        self.assertEqual(data["listen_port"], 9001)
        self.assertEqual(data["adapter"], "msp")

    def test_print_config_outputs_crossfire_adapter(self) -> None:
        result = CliRunner().invoke(
            server_main,
            [
                "--adapter",
                "crossfire",
                "--listen-port",
                "9002",
                "--print-config",
            ],
        )

        self.assertEqual(result.exit_code, 0)
        data = yaml.safe_load(result.output)
        self.assertEqual(data["adapter"], "crossfire")
        self.assertEqual(data["listen_port"], 9002)

    def test_programmatic_main_returns_effective_config(self) -> None:
        config = joy_server.main(
            make_server_args(
                output_kind="serial",
                serial_device="/dev/ttyUSB0",
                baudrate=115200,
                listen_port=9001,
            )
        )

        self.assertIsNotNone(config)
        self.assertEqual(config.output, "serial")
        self.assertEqual(str(config.serial_device), "/dev/ttyUSB0")
        self.assertEqual(config.baudrate, 115200)
        self.assertEqual(config.listen_port, 9001)

    def test_programmatic_main_uses_plain_config_errors(self) -> None:
        with self.assertRaisesRegex(
            ServerConfigError,
            "--serial-device is required when --output serial",
        ):
            joy_server.main(make_server_args(output_kind="serial", print_config=False))

    def test_crossfire_adapter_runs_without_msp_transport(self) -> None:
        class _StopAdapter:
            def __enter__(self):
                return self

            def __exit__(self, *_exc: object) -> None:
                pass

            def startup_check(self) -> None:
                pass

            def write_channels(self, channels, sequence, timestamp_us) -> None:
                pass

            def enter_failsafe(self, reason: str) -> None:
                pass

            def exit_failsafe(self) -> None:
                pass

            def tick(self) -> None:
                pass

        with patch(
            "bt_joy.server.joy_server.CrossfireOutputAdapter",
            return_value=_StopAdapter(),
        ) as crossfire_adapter, patch(
            "bt_joy.server.joy_server.run_udp_server",
            side_effect=KeyboardInterrupt,
        ) as run_udp_server, patch(
            "bt_joy.server.joy_server._make_transport",
        ) as make_transport, patch.object(joy_server, "logger", _Logger()):
            result = CliRunner().invoke(server_main, ["--adapter", "crossfire"])

        self.assertNotEqual(result.exit_code, 0)
        crossfire_adapter.assert_called_once_with()
        make_transport.assert_not_called()
        run_udp_server.assert_called_once()


if __name__ == "__main__":
    unittest.main()
