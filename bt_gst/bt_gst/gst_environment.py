import importlib.util
import os
from pathlib import Path
import gi

from loguru import logger

gst_environment_logger = logger.bind(component="bt_gst.gst_environment")

GST_PLUGIN_PATH = Path(__file__).resolve().parents[1] / "plugins"
PYTHON_PLUGIN_PATH = GST_PLUGIN_PATH / "python"


def configure_gst_plugin_path() -> None:
    plugin_path = str(GST_PLUGIN_PATH)
    existing_path = os.environ.get("GST_PLUGIN_PATH")
    if not existing_path:
        os.environ["GST_PLUGIN_PATH"] = plugin_path
        gst_environment_logger.debug("configured GST_PLUGIN_PATH path={}", plugin_path)
        return

    paths = existing_path.split(os.pathsep)
    if plugin_path not in paths:
        os.environ["GST_PLUGIN_PATH"] = os.pathsep.join([plugin_path, *paths])
        gst_environment_logger.debug(
            "prepended GST_PLUGIN_PATH path={}", os.environ["GST_PLUGIN_PATH"]
        )


def remove_local_python_plugin_paths_from_gst_scan() -> None:
    existing_path = os.environ.get("GST_PLUGIN_PATH")
    if not existing_path:
        return

    local_paths = {str(GST_PLUGIN_PATH), str(PYTHON_PLUGIN_PATH)}
    paths = [
        path
        for path in existing_path.split(os.pathsep)
        if path and path not in local_paths
    ]
    if paths:
        os.environ["GST_PLUGIN_PATH"] = os.pathsep.join(paths)
    else:
        os.environ.pop("GST_PLUGIN_PATH", None)
    gst_environment_logger.debug(
        "removed local Python plugin paths from GST_PLUGIN_PATH path={}",
        os.environ.get("GST_PLUGIN_PATH", ""),
    )


def register_local_python_elements(gst: object) -> None:
    register_python_element(
        gst,
        module_path=PYTHON_PLUGIN_PATH / "gzimagesrc.py",
        module_name="bt_gst_gzimagesrc",
        element_name="gzimagesrc",
        class_name="GazeboImageSrc",
        metadata=(
            "Gazebo Image Source",
            "Source/Video",
            "Reads camera images from a Gazebo Transport topic",
            "Amir",
        ),
        pad_templates=("CAPS_TEMPLATE",),
    )


def register_python_element(
    gst: object,
    *,
    module_path: Path,
    module_name: str,
    element_name: str,
    class_name: str,
    metadata: tuple[str, str, str, str],
    pad_templates: tuple[str, ...] = (),
) -> None:
    if gst.ElementFactory.find(element_name) is not None:
        return

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"GStreamer Python plugin could not be loaded: {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    element_type = getattr(module, class_name)
    element_type.set_metadata(*metadata)
    if _requires_explicit_pad_templates():
        for caps_name in pad_templates:
            element_type.add_pad_template(
                gst.PadTemplate.new(
                    "src",
                    gst.PadDirection.SRC,
                    gst.PadPresence.ALWAYS,
                    getattr(module, caps_name),
                )
            )

    if not gst.Element.register(None, element_name, gst.Rank.NONE, element_type):
        raise RuntimeError(f"GStreamer element could not be registered: {element_name}")
    gst_environment_logger.debug("registered local GStreamer element name={}", element_name)


def _requires_explicit_pad_templates() -> bool:
    return "site-packages" in str(Path(gi.__file__))
