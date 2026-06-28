from loguru import logger as log
from bt_app.context import Context
from bt_app.common import RobotState
from bt_app.msgs import RCChannels

def matching(ctx: Context, rc_channels: RCChannels) -> RCChannels:
    if ctx.state == RobotState.MANUAL:
        return rc_channels
    
    
    return rc_channels
        