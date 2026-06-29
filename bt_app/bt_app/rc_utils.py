from loguru import logger as log
from bt_app.context import Context
from bt_app.common import RobotState
from bt_app.msgs import RCChannels

def matching(ctx: Context, rc_channels) -> RCChannels:
    if ctx.state == RobotState.MANUAL.value:
        if not ctx.take_control and rc_channels[2] < ctx.drone_rc[2]:
            rc_channels[2] = ctx.drone_rc[2]
        else:
            ctx.take_control = True
        return rc_channels
    
    
    return rc_channels
        