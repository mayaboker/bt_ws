import pytest

from bt_app.context import Context
from bt_app.main import main
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


def test_run_missing_parameters_file_exits_cleanly_non_standalone(tmp_path):
    parameters_path = tmp_path / "missing_parameters.yaml"
    config_path = _write_vehicle_config(tmp_path, parameters_path)

    with pytest.raises(RuntimeError) as exc_info:
        main(["run", "-c", str(config_path)], standalone_mode=False)

    assert str(exc_info.value) == f"Parameters config not found: {parameters_path}"
    assert not isinstance(exc_info.value.__cause__, FileNotFoundError)


def test_run_missing_parameters_file_exits_one_in_standalone_mode(tmp_path):
    parameters_path = tmp_path / "missing_parameters.yaml"
    config_path = _write_vehicle_config(tmp_path, parameters_path)

    with pytest.raises(SystemExit) as exc_info:
        main(["run", "-c", str(config_path)], standalone_mode=True)

    assert exc_info.value.code == 1


def test_run_invalid_parameters_file_exits_cleanly_non_standalone(tmp_path):
    parameters_path = tmp_path / "parameters.yaml"
    parameters_path.write_text("parameters: [\n", encoding="utf-8")
    config_path = _write_vehicle_config(tmp_path, parameters_path)

    with pytest.raises(RuntimeError, match="Failed to load parameters from"):
        main(["run", "-c", str(config_path)], standalone_mode=False)
