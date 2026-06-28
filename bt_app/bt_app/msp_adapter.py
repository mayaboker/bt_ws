from bt_app.msp import BetaflightMspClient, TcpMspTransport
from bt_app.msp.command_dispatcher import MspCommandDispatcher
from bt_app.vehicle_config import VehicleConfig, DroneSink
from loguru import logger as log

class MSPAdapter:
    def __init__(self, config: VehicleConfig)->None:
        self.dispatcher = None
        self.msp = None
        if config.drone_sink == DroneSink.ETHERNET.value:
            transport = TcpMspTransport(config.drone_eth_host, config.drone_eth_port)
        else:
            raise NotImplementedError("Serial transport not implemented yet")
        self.msp = BetaflightMspClient(transport)

        self.dispatcher = MspCommandDispatcher(
            self.msp,
            on_error=lambda exc: log.error(f"MSP dispatcher error: {exc}"),
        )

    def get_state(self):
        """
        Dispatcher last state: {'cycle_time_us': 109, 'i2c_errors': 0, 'sensors_mask': 35, 
        'sensors_mask_hex': '0x0023',
          'box_mode_flags': 0,
            'box_mode_flags_hex': '0x00000000', 'pid_profile': 0, 'pid_profile_count': 4, 
            'rate_profile': 0, 'cpu_load_raw': 0, 'flight_mode_byte_count': 0, 
            'arming_disable_flag_count': 29, 'arming_disable_mask': 4, 
            'arming_disable_mask_hex': '0x00000004', 
            'arming_disable_flags': ['RX_FAILSAFE'], 'arming_disabled': True, 'armable': False, 'calibrating': False, 
            'failsafe': True, 'throttle_blocking_arm': False, 'arm_switch_blocking_arm': False, 'not_disarmed': False}
        """
        return self.dispatcher.last_state

    def start(self):
        self.msp.open()       
        self.dispatcher.schedule_state(interval_s=1.0)
        self.dispatcher.schedule_altitude(interval_s=0.1)
        self.dispatcher.start()

