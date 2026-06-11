import importlib.util
from functools import lru_cache
from pathlib import Path

import pytest


PLUGIN_PATH = (
    Path(__file__).resolve().parents[1] / "plugins" / "python" / "gstbtpassthrough.py"
)


@lru_cache
def load_plugin_module():
    pytest.importorskip("gi")
    spec = importlib.util.spec_from_file_location("gstbtpassthrough", PLUGIN_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plugin_exports_tracker_meta_definition() -> None:
    module = load_plugin_module()

    assert module.META_NAME == "bt-tracker-meta"
    assert module.G_TYPE_INT == 24
    assert module.G_TYPE_FLOAT == 56


def test_plugin_exposes_metadata_helpers() -> None:
    module = load_plugin_module()

    assert callable(module.set_meta_int)
    assert callable(module.set_meta_float)
