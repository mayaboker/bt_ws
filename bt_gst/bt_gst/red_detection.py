from dataclasses import dataclass


RED_DETECTION_META_NAME = "GstRedDetectionMeta"
GST_CLOCK_TIME_NONE = (1 << 64) - 1


@dataclass(frozen=True)
class RedDetection:
    found: bool
    x: int
    y: int
    width: int
    height: int
    pts_ns: int | None


def read_red_detection(buffer: object) -> RedDetection | None:
    meta = buffer.get_custom_meta(RED_DETECTION_META_NAME)
    if meta is None:
        return None

    structure = meta.get_structure()
    pts = int(buffer.pts)
    return RedDetection(
        found=bool(structure.get_value("found")),
        x=int(structure.get_value("x")),
        y=int(structure.get_value("y")),
        width=int(structure.get_value("width")),
        height=int(structure.get_value("height")),
        pts_ns=None if pts == GST_CLOCK_TIME_NONE else pts,
    )
