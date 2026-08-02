import shlex
import signal

import pytest

from bt_app.context import Context
from bt_app.errors import AppExitCode
from bt_app.main import _run_application, main
from bt_app.vehicle_config import VehicleConfig


@pytest.fixture(autouse=True)
def reset_singletons():
    Context._instance = None
    Context._initialized = False
    VehicleConfig._instance = None
    VehicleConfig._initialized = False
    yield
    Context._instance = None
    Context._initialized = False
    VehicleConfig._instance = None
    VehicleConfig._initialized = False


def _write_vehicle_config(tmp_path, parameters_path):
    config_path = tmp_path / "vehicle_config.yaml"
    config_path.write_text(
        f"config_name: {str(parameters_path)!r}\n",
        encoding="utf-8",
    )
    return config_path


def test_alias_prints_run_alias_and_bashrc_append_command(capsys):
    main(["alias"], standalone_mode=False)

    assert capsys.readouterr().out == (
        "For current shell:\n"
        "alias start_bt_app='uv run bt-app run'\n"
        "For persistent shell (~/.bashrc):\n"
        "echo 'alias start_bt_app='\"'\"'uv run bt-app run'\"'\"'' >> ~/.bashrc\n"
    )


def test_alias_includes_config_path(capsys):
    main(["alias", "-c", "config/vehicle_config.yaml"], standalone_mode=False)

    assert capsys.readouterr().out == (
        "For current shell:\n"
        "alias start_bt_app='uv run bt-app run -c config/vehicle_config.yaml'\n"
        "For persistent shell (~/.bashrc):\n"
        "echo 'alias start_bt_app='\"'\"'uv run bt-app run -c config/vehicle_config.yaml'\"'\"'' >> ~/.bashrc\n"
    )


def test_alias_quotes_config_path_with_spaces(capsys):
    main(["alias", "-c", "configs/vehicle app.yaml"], standalone_mode=False)

    current_title, alias_line, persistent_title, append_line = (
        capsys.readouterr().out.splitlines()
    )
    assert current_title == "For current shell:"
    assert alias_line == (
        "alias start_bt_app='uv run bt-app run -c "
        "'\"'\"'configs/vehicle app.yaml'\"'\"''"
    )
    assert persistent_title == "For persistent shell (~/.bashrc):"
    assert append_line.startswith("echo ")
    assert append_line.endswith(" >> ~/.bashrc")
    assert shlex.split(append_line.removeprefix("echo ").removesuffix(" >> ~/.bashrc")) == [
        alias_line
    ]


def test_alias_does_not_validate_config(capsys):
    main(["alias", "-c", "missing.yaml"], standalone_mode=False)

    output = capsys.readouterr().out
    assert "missing.yaml" in output
    assert "Vehicle config not found" not in output


def test_run_missing_parameters_file_exits_cleanly_non_standalone(tmp_path):
    parameters_path = tmp_path / "missing_parameters.yaml"
    config_path = _write_vehicle_config(tmp_path, parameters_path)

    with pytest.raises(RuntimeError) as exc_info:
        main(["run", "-c", str(config_path)], standalone_mode=False)

    assert str(exc_info.value) == f"Parameters config not found: {parameters_path}"
    assert not isinstance(exc_info.value.__cause__, FileNotFoundError)


def test_run_missing_vehicle_config_exits_cleanly_non_standalone(tmp_path):
    config_path = tmp_path / "missing_vehicle_config.yaml"

    with pytest.raises(RuntimeError) as exc_info:
        main(["run", "-c", str(config_path)], standalone_mode=False)

    assert str(exc_info.value) == f"Vehicle config not found: {config_path}"


def test_run_missing_vehicle_config_exits_one_in_standalone_mode(tmp_path):
    config_path = tmp_path / "missing_vehicle_config.yaml"

    with pytest.raises(SystemExit) as exc_info:
        main(["run", "-c", str(config_path)], standalone_mode=True)

    assert exc_info.value.code == AppExitCode.STARTUP_ERROR


def test_run_missing_serial_port_exits_cleanly_non_standalone(tmp_path):
    serial_path = tmp_path / "missing_ttyUSB0"
    config_path = tmp_path / "vehicle_config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "drone_sink: 1",
                f"drone_serial_port: {str(serial_path)!r}",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError) as exc_info:
        main(["run", "-c", str(config_path)], standalone_mode=False)

    assert str(exc_info.value) == f"Serial port not found: {serial_path}"


def test_run_missing_serial_port_exits_three_in_standalone_mode(tmp_path):
    serial_path = tmp_path / "missing_ttyUSB0"
    config_path = tmp_path / "vehicle_config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "drone_sink: 1",
                f"drone_serial_port: {str(serial_path)!r}",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        main(["run", "-c", str(config_path)], standalone_mode=True)

    assert exc_info.value.code == AppExitCode.SERIAL_PORT_NOT_FOUND


def test_run_missing_parameters_file_exits_one_in_standalone_mode(tmp_path):
    parameters_path = tmp_path / "missing_parameters.yaml"
    config_path = _write_vehicle_config(tmp_path, parameters_path)

    with pytest.raises(SystemExit) as exc_info:
        main(["run", "-c", str(config_path)], standalone_mode=True)

    assert exc_info.value.code == AppExitCode.STARTUP_ERROR


def test_run_invalid_parameters_file_exits_cleanly_non_standalone(tmp_path):
    parameters_path = tmp_path / "parameters.yaml"
    parameters_path.write_text("parameters: [\n", encoding="utf-8")
    config_path = _write_vehicle_config(tmp_path, parameters_path)

    with pytest.raises(RuntimeError, match="Failed to load parameters from"):
        main(["run", "-c", str(config_path)], standalone_mode=False)


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_run_application_converts_signal_to_stop_request_and_restores_handlers(
    monkeypatch,
    signum,
):
    installed_handlers = {}
    restored_handlers = {}
    previous_handlers = {
        signal.SIGINT: object(),
        signal.SIGTERM: object(),
    }

    def fake_getsignal(requested_signum):
        return previous_handlers[requested_signum]

    def fake_signal(requested_signum, handler):
        if callable(handler):
            installed_handlers[requested_signum] = handler
        else:
            restored_handlers[requested_signum] = handler

    class FakeApp:
        def __init__(self):
            self.stop_requests = []

        def request_stop(self, requested_signum):
            self.stop_requests.append(requested_signum)

        def run(self):
            installed_handlers[signum](signum, None)

    monkeypatch.setattr(signal, "getsignal", fake_getsignal)
    monkeypatch.setattr(signal, "signal", fake_signal)
    app = FakeApp()

    _run_application(app)

    assert app.stop_requests == [signum]
    assert restored_handlers == previous_handlers
