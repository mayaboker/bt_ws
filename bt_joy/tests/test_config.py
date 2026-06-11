import unittest

from bt_joy.client.config import parse_config as parse_client_config
from bt_joy.client.config import parse_mapping as parse_client_mapping
from bt_joy.server.config import parse_config as parse_server_config


class ConfigTest(unittest.TestCase):
    def test_client_config_parses_keepalive_options(self) -> None:
        config = parse_client_config(
            {
                "expected_name": "Xbox Wireless Controller",
                "mapping": "xbox.yaml",
                "keepalive_interval": 2.5,
                "keepalive_timeout": 0.75,
                "joystick_reconnect_interval": 0.5,
                "keepalive_rtt_warning": {
                    "enabled": True,
                    "threshold_ms": 80.0,
                    "window_s": 8.0,
                    "count": 4,
                    "cooldown_s": 12.0,
                },
                "channels": [{"name": "aux", "source": "constant", "value": 1500}],
            }
        )

        self.assertEqual(config.expected_name, "Xbox Wireless Controller")
        self.assertEqual(config.mapping, "xbox.yaml")
        self.assertEqual(config.keepalive_interval, 2.5)
        self.assertEqual(config.keepalive_timeout, 0.75)
        self.assertEqual(config.joystick_reconnect_interval, 0.5)
        self.assertTrue(config.keepalive_rtt_warning.enabled)
        self.assertEqual(config.keepalive_rtt_warning.threshold_ms, 80.0)
        self.assertEqual(config.keepalive_rtt_warning.window_s, 8.0)
        self.assertEqual(config.keepalive_rtt_warning.count, 4)
        self.assertEqual(config.keepalive_rtt_warning.cooldown_s, 12.0)

    def test_client_config_rejects_invalid_keepalive_rtt_warning_mapping(self) -> None:
        with self.assertRaises(ValueError):
            parse_client_config({"keepalive_rtt_warning": "enabled"})

    def test_client_mapping_parses_channels(self) -> None:
        channels = parse_client_mapping(
            {"channels": [{"name": "aux", "source": "constant", "value": 1500}]}
        )

        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0].name, "aux")
        self.assertEqual(channels[0].value, 1500)

    def test_client_mapping_rejects_invalid_channels(self) -> None:
        with self.assertRaises(ValueError):
            parse_client_mapping({"channels": "aux"})

    def test_server_config_parses_serial_output(self) -> None:
        config = parse_server_config(
            {
                "listen_host": "127.0.0.1",
                "listen_port": 9100,
                "output": "serial",
                "serial_device": "/dev/ttyUSB0",
                "baudrate": 230400,
                "rc_rate_hz": 25.0,
                "failsafe_channels": [1500, 1500, 900, 1500, 1000, 1000, 1000, 1000],
                "status_interval": 1.0,
                "rc_read_interval": 0.1,
                "rc_read_timeout": 0.03,
                "altitude_interval": 0.2,
                "altitude_timeout": 0.04,
                "startup_probe_attempts": 5,
                "startup_probe_interval": 0.25,
                "failsafe_joystick_timeout": 0.5,
                "takeoff_automation": {
                    "enabled": True,
                    "require_manual_arm": True,
                    "trigger_channel": "aux4",
                    "arm_channel": "aux1",
                    "trigger_on": 1700,
                    "arm_on": 1900,
                    "target_altitude_m": 4.5,
                    "target_tolerance_m": 0.3,
                    "throttle_base": 1320,
                    "throttle_min": 1050,
                    "throttle_max": 1750,
                    "pid_kp": 75.0,
                    "pid_ki": 12.0,
                    "pid_kd": 25.0,
                    "pid_integral_limit": 8.0,
                },
            }
        )

        self.assertEqual(config.listen_host, "127.0.0.1")
        self.assertEqual(config.adapter, "msp")
        self.assertEqual(config.listen_port, 9100)
        self.assertEqual(config.output, "serial")
        self.assertEqual(str(config.serial_device), "/dev/ttyUSB0")
        self.assertEqual(config.baudrate, 230400)
        self.assertEqual(config.rc_rate_hz, 25.0)
        self.assertEqual(config.failsafe_channels, (1500, 1500, 900, 1500, 1000, 1000, 1000, 1000))
        self.assertEqual(config.status_interval, 1.0)
        self.assertEqual(config.rc_read_interval, 0.1)
        self.assertEqual(config.rc_read_timeout, 0.03)
        self.assertEqual(config.altitude_interval, 0.2)
        self.assertEqual(config.altitude_timeout, 0.04)
        self.assertEqual(config.startup_probe_attempts, 5)
        self.assertEqual(config.startup_probe_interval, 0.25)
        self.assertEqual(config.failsafe_joystick_timeout, 0.5)
        self.assertTrue(config.takeoff_automation.enabled)
        self.assertTrue(config.takeoff_automation.require_manual_arm)
        self.assertEqual(config.takeoff_automation.trigger_channel, "aux4")
        self.assertEqual(config.takeoff_automation.arm_channel, "aux1")
        self.assertEqual(config.takeoff_automation.trigger_on, 1700)
        self.assertEqual(config.takeoff_automation.arm_on, 1900)
        self.assertEqual(config.takeoff_automation.target_altitude_m, 4.5)
        self.assertEqual(config.takeoff_automation.target_tolerance_m, 0.3)
        self.assertEqual(config.takeoff_automation.throttle_base, 1320)
        self.assertEqual(config.takeoff_automation.throttle_min, 1050)
        self.assertEqual(config.takeoff_automation.throttle_max, 1750)
        self.assertEqual(config.takeoff_automation.pid_kp, 75.0)
        self.assertEqual(config.takeoff_automation.pid_ki, 12.0)
        self.assertEqual(config.takeoff_automation.pid_kd, 25.0)
        self.assertEqual(config.takeoff_automation.pid_integral_limit, 8.0)

    def test_server_config_rejects_invalid_output(self) -> None:
        with self.assertRaises(ValueError):
            parse_server_config({"output": "bluetooth"})

    def test_server_config_parses_crossfire_adapter(self) -> None:
        config = parse_server_config({"adapter": "crossfire", "listen_port": 9101})

        self.assertEqual(config.adapter, "crossfire")
        self.assertEqual(config.listen_port, 9101)

    def test_server_config_rejects_invalid_adapter(self) -> None:
        with self.assertRaises(ValueError):
            parse_server_config({"adapter": "sbus"})


if __name__ == "__main__":
    unittest.main()
