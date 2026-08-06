from __future__ import annotations

from pathlib import Path
import re
import struct

import pytest
import yaml
from pymavlink import mavutil

from bt_app.app import App
from bt_app.control.land_detector import LandDetector
from bt_app.parameters.generated import ALL_PARAMETER_KEYS
from bt_app.parameters.mavlink import MavlinkParameterProtocol
from bt_app.parameters.service import ParameterService
from bt_app.parameters.storage import ParameterStorage


def make_service(path: str | Path = "bt_app/parameters.yaml") -> ParameterService:
    return ParameterService(ParameterStorage.from_yaml(path))


def make_protocol(
    service: ParameterService,
    *,
    armed: bool = False,
) -> tuple[MavlinkParameterProtocol, object]:
    mav = mavutil.mavlink.MAVLink(None)
    protocol = MavlinkParameterProtocol(
        service=service,
        mav=mav,
        system_id=1,
        component_id=1,
        gcs_addr=("127.0.0.1", 14550),
        is_armed=lambda: armed,
    )
    return protocol, mav


def encode_int32(value: int) -> float:
    return struct.unpack("<f", struct.pack("<i", value))[0]


def decode_int32(value: float) -> int:
    return struct.unpack("<i", struct.pack("<f", value))[0]


def test_canonical_parameter_registry_has_34_mavlink_names():
    service = make_service()

    assert len(ALL_PARAMETER_KEYS) == 34
    assert tuple(name for name, _, _ in service.snapshot()) == ALL_PARAMETER_KEYS
    assert all(
        re.fullmatch(r"[A-Z][A-Z0-9_]{0,15}", name) for name in ALL_PARAMETER_KEYS
    )


def test_old_dotted_parameter_name_is_rejected(tmp_path):
    path = tmp_path / "parameters.yaml"
    path.write_text(
        yaml.safe_dump({"parameters": {"hover.kp": {"type": "float", "default": 1.0}}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="uppercase MAVLink ID"):
        ParameterStorage.from_yaml(path)


def test_rejected_set_does_not_emit_change():
    service = make_service()
    changes = []
    service.on_parameter_changed.subscribe(
        lambda name, value: changes.append((name, value))
    )

    with pytest.raises(ValueError):
        service.set("HOV_BASELINE", 999)

    assert service.get("HOV_BASELINE") == 1660
    assert changes == []


def test_callback_failure_does_not_block_other_subscribers():
    service = make_service()
    changes = []

    def fail(_name, _value):
        raise RuntimeError("subscriber failed")

    service.on_parameter_changed.subscribe(fail)
    service.on_parameter_changed.subscribe(
        lambda name, value: changes.append((name, value))
    )

    service.set("HOV_BASELINE", 1400)

    assert changes == [("HOV_BASELINE", 1400)]


@pytest.mark.parametrize(
    ("name", "value", "attribute"),
    [
        ("MI_LAND_CONFIRM", 3.0, "confirm_s"),
        ("FS_LAND_ALT", 0.25, "land_altitude_m"),
        ("FS_LAND_VSPEED", 0.2, "land_vertical_speed_m_s"),
    ],
)
def test_manual_land_detector_parameter_changes_apply_live(name, value, attribute):
    app = App.__new__(App)
    app.manual_land_detector = LandDetector(
        confirm_s=2.0,
        land_altitude_m=0.15,
        land_vertical_speed_m_s=0.1,
    )

    app._on_application_parameter_changed(name, value)

    assert getattr(app.manual_land_detector, attribute) == value


def test_list_read_and_int_set_use_canonical_names():
    service = make_service()
    protocol, mav = make_protocol(service)
    source = ("127.0.0.1", 40000)

    responses = protocol.handle(mav.param_request_list_encode(1, 1), source)

    assert len(responses) == 34
    assert responses[0].message.param_id == "FS_HOLD_TIME"
    assert responses[-1].delay_s == pytest.approx(0.66)

    request = mav.param_set_encode(
        1,
        1,
        b"HOV_BASELINE",
        encode_int32(1400),
        mavutil.mavlink.MAV_PARAM_TYPE_INT32,
    )
    set_responses = protocol.handle(request, source)

    assert service.get("HOV_BASELINE") == 1400
    assert {response.destination for response in set_responses} == {
        source,
        ("127.0.0.1", 14550),
    }
    assert decode_int32(set_responses[0].message.param_value) == 1400


def test_invalid_set_echoes_current_value_without_mutating():
    service = make_service()
    protocol, mav = make_protocol(service)
    request = mav.param_set_encode(
        1,
        1,
        b"HOV_BASELINE",
        encode_int32(999),
        mavutil.mavlink.MAV_PARAM_TYPE_INT32,
    )

    responses = protocol.handle(request, ("127.0.0.1", 40000))

    assert service.get("HOV_BASELINE") == 1660
    assert decode_int32(responses[0].message.param_value) == 1660


def test_explicit_save_is_denied_armed_and_persists_disarmed(tmp_path):
    path = tmp_path / "parameters.yaml"
    path.write_text(
        Path("bt_app/parameters.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    service = make_service(path)
    service.set("HOV_BASELINE", 1400)
    source = ("127.0.0.1", 40000)

    armed_protocol, mav = make_protocol(service, armed=True)
    command = mav.command_long_encode(
        1,
        1,
        mavutil.mavlink.MAV_CMD_PREFLIGHT_STORAGE,
        0,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
    )
    denied = armed_protocol.handle(command, source)
    assert denied[0].message.result == mavutil.mavlink.MAV_RESULT_DENIED

    disarmed_protocol, _ = make_protocol(service, armed=False)
    accepted = disarmed_protocol.handle(command, source)
    assert accepted[0].message.result == mavutil.mavlink.MAV_RESULT_ACCEPTED
    assert ParameterStorage.from_yaml(path).get("HOV_BASELINE") == 1400
