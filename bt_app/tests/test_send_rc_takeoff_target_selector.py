import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

EXAMPLE_DIR = Path(__file__).parents[1] / "example"
sys.path.insert(0, str(EXAMPLE_DIR))
SCRIPT_PATH = EXAMPLE_DIR / "send_rc_takeoff_target_selector.py"
SPEC = spec_from_file_location("send_rc_takeoff_target_selector", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
selector_script = module_from_spec(SPEC)
sys.modules[SPEC.name] = selector_script
SPEC.loader.exec_module(selector_script)


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("left", (selector_script.RC_MIN, selector_script.RC_MIN)),
        ("center", (selector_script.RC_MID, selector_script.RC_MIN)),
        ("right", (selector_script.RC_MAX, selector_script.RC_MIN)),
    ],
)
def test_named_target_gestures(target, expected):
    assert selector_script.target_gesture(target) == expected


def test_explicit_rc_values_override_named_target():
    assert selector_script.target_gesture(
        "left", roll_override=1800, pitch_override=1200
    ) == (1800, 1200)


def test_cli_exposes_named_target_choices():
    help_text = selector_script.build_parser().format_help()
    assert "--target {left,center,right}" in help_text
