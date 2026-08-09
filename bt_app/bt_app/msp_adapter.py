from bt_app.msp import BetaflightMspClient, SerialMspTransport, TcpMspTransport
from bt_app.msp.command_dispatcher import (
    MspCommandDispatcher,
    MspCommandExecutionError,
)
from bt_app.vehicle_config import VehicleConfig, DroneSink
from loguru import logger as log

class MSPAdapter:
    def __init__(self, config: VehicleConfig)->None:
        self.dispatcher = None
        self.msp = None
        if config.drone_sink == DroneSink.ETHERNET.value:
            transport = TcpMspTransport(config.drone_eth_host, config.drone_eth_port)
        elif config.drone_sink == DroneSink.SERIAL.value:
            transport = SerialMspTransport(config.drone_serial_port)
        else:
            raise ValueError(f"Unsupported drone sink: {config.drone_sink}")
        self.msp = BetaflightMspClient(transport)

        self.dispatcher = MspCommandDispatcher(
            self.msp,
            on_error=self._handle_dispatcher_error,
        )

    @staticmethod
    def _handle_dispatcher_error(exc: MspCommandExecutionError) -> None:
        log.error("MSP dispatcher error: {}", exc)

    def raise_if_failed(self) -> None:
        """Raise a fatal error reported by the dispatcher worker."""
        self.dispatcher.raise_if_failed()

    def get_rc(self):
        """
        read current drone rc
        use for switch between external pilot to machine
        see example and scenario in documents
        """
        return self.dispatcher.last_rc

    def get_altitude(self):
        """
        {'altitude_m': 0.25, 'vertical_speed_m_s': 0.0}
        """
        if not self.dispatcher.last_altitude: return 0
        return self.dispatcher.last_altitude["altitude_m"]
    
    def get_state(self):
        """
        Dispatcher last state: {
        'cycle_time_us': 109, 
        'i2c_errors': 0, 
        'sensors_mask': 35, 
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
        # GLIDE closes its velocity loop on MSP_ALTITUDE.vario.  Poll at 20 Hz
        # so each controller update is based on sufficiently fresh velocity.
        self.dispatcher.schedule_altitude(interval_s=0.05)
        self.dispatcher.schedule_battery(interval_s=2.0)
        self.dispatcher.schedule_attitude(interval_s=0.5)
        self.dispatcher.schedule_rc(interval_s=1.0)
        
        self.dispatcher.start()

    def stop(self, timeout: float | None = 2.0) -> None:
        """Stop scheduled MSP work before closing the transport."""
        try:
            self.dispatcher.stop(timeout=timeout)
        finally:
            self.msp.close()
