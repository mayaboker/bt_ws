from bt_app.common import RobotState
from bt_app.context import Context
from bt_app.control.land_detector import LandDetector
from bt_app.parameters import Parameters
from bt_app.parameters.generated import ParameterKey


class ManualLandService:
    """Evaluate manual landing synchronously from the current app context."""

    def __init__(
        self,
        *,
        context: Context,
        parameters: Parameters,
        detector: LandDetector | None = None,
    ) -> None:
        self._context = context
        self._detector = detector or LandDetector(
            confirm_s=parameters.get(ParameterKey.MI_LAND_CONFIRM),
            land_altitude_m=parameters.get(ParameterKey.FS_LAND_ALT),
            land_vertical_speed_m_s=parameters.get(ParameterKey.FS_LAND_VSPEED),
        )
        parameters.on_parameter_changed.subscribe(self._on_parameter_changed)

    def update(self) -> None:
        if not self._is_detection_requested():
            self.reset()
            return

        self._context.manual_land_confirmed = self._detector.update(
            self._context.drone_alt,
            self._context.drone_vertical_speed,
        )

    def reset(self) -> None:
        self._detector.reset()
        self._context.manual_land_confirmed = False

    def _is_detection_requested(self) -> bool:
        channels = self._context.request_rc
        return (
            self._context.state == RobotState.MANUAL
            and not channels.is_manual()
            and channels.is_throttle_low()
        )

    def _on_parameter_changed(self, name: str, value: object) -> None:
        if name == ParameterKey.MI_LAND_CONFIRM:
            self._detector.confirm_s = float(value)
        elif name == ParameterKey.FS_LAND_ALT:
            self._detector.land_altitude_m = float(value)
        elif name == ParameterKey.FS_LAND_VSPEED:
            self._detector.land_vertical_speed_m_s = float(value)
