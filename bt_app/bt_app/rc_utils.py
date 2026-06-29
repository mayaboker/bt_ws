from loguru import logger as log
from bt_app.context import Context
from bt_app.common import RobotState, AETR1234

from bt_app.vehicle_config import VehicleConfig

def matching(ctx: Context, rc_channels, config: VehicleConfig):
    
    
    if config.has_external_pilot and ctx.state == RobotState.MANUAL.value:
        """
        aux3 config as MSP_OVERRIDE, the value is force to be pilot control value
        """
        rc_channels[AETR1234.AUX3] = ctx.drone_rc[AETR1234.AUX3]

    if ctx.state == RobotState.MANUAL.value:
        if not ctx.take_control and rc_channels[AETR1234.THROTTLE] < ctx.drone_rc[AETR1234.THROTTLE]:
            rc_channels[AETR1234.THROTTLE] = ctx.drone_rc[AETR1234.THROTTLE]
        else:
            ctx.take_control = True
        return rc_channels
    
    
    
    return rc_channels
        