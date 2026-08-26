from __future__ import annotations

import pathlib
import time
from collections.abc import Callable

from loguru import logger as log

from bt_app.context import Context
from bt_app.control import MavlinkListenerError, MavlinkListenerService
from bt_app.errors import AppExitCode, AppStartupError
from bt_app.mavlink_wrapper import MavlinkService
from bt_app.msp import MspTransportDependencyError
from bt_app.msp_adapter import MSPAdapter
from bt_app.parameters import Parameters
from bt_app.rc_state_recorder import NullRcStateRecorder, RcStateRecorder
from bt_app.services import ManualLandService, TargetSelectorPublisher, TrackerResultStore
from bt_app.vehicle_config import DroneSink, VehicleConfig
from bt_app.visual_bridge import VisualBridgeManager
from bt_joy.server.mavlink import (
    CommunicationResumedEvent,
    MavlinkServerConfig,
    NoCommunicationEvent,
    RcChannelsOverrideEvent,
)

FCU_CONNECT_ATTEMPTS = 3
FCU_CONNECT_RETRY_DELAY_S = 1.0


class AppServices:
    """Construct, start, and stop the application's external services."""

    def __init__(
        self,
        *,
        config: VehicleConfig,
        parameters: Parameters,
        visual_bridge: VisualBridgeManager,
        drone: MSPAdapter,
        joystick: MavlinkListenerService,
        mavlink: MavlinkService,
        rc_recorder: RcStateRecorder | NullRcStateRecorder,
        manual_land: ManualLandService,
        tracker_results: TrackerResultStore,
        target_selector: TargetSelectorPublisher,
    ) -> None:
        self.config = config
        self.parameters = parameters
        self.visual_bridge = visual_bridge
        self.drone = drone
        self.joystick = joystick
        self.mavlink = mavlink
        self.rc_recorder = rc_recorder
        self.manual_land = manual_land
        self.tracker_results = tracker_results
        self.target_selector = target_selector
        self._started: list[tuple[str, object]] = []

    @classmethod
    def build(
        cls,
        *,
        config: VehicleConfig,
        context: Context,
        on_rc: Callable[[RcChannelsOverrideEvent], None],
        on_timeout: Callable[[NoCommunicationEvent], None],
        on_resume: Callable[[CommunicationResumedEvent], None],
        on_failure: Callable[[MavlinkListenerError], None],
    ) -> "AppServices":
        parameters = cls._load_parameters(config.config_name)
        visual_bridge = VisualBridgeManager(config.visual_zmq_endpoint)
        tracker_results = TrackerResultStore()
        visual_bridge.subscribe(tracker_results.process_tracker_result)
        drone = MSPAdapter(config)
        joystick = MavlinkListenerService(
            config=MavlinkServerConfig(
                connection="udpin:0.0.0.0:14560",
                source_system=254,
                source_component=0,
                heartbeat_rate_hz=1.0,
                communication_timeout_stage1_s=1.0,
                communication_timeout_stage2_s=5.0,
                receive_timeout_s=0.05,
                channel_count=18,
            ),
            on_rc=on_rc,
            on_timeout=on_timeout,
            on_resume=on_resume,
            on_failure=on_failure,
        )
        mavlink = MavlinkService(
            context=context,
            parameter_service=parameters.service,
            qopenhd_addr=(config.gcs_ip, config.gcs_port),
        )
        recorder = (
            RcStateRecorder(
                config.rc_record_path,
                flush_interval_s=config.rc_record_flush_interval_s,
                queue_size=config.rc_record_queue_size,
            )
            if config.rc_record_enabled
            else NullRcStateRecorder()
        )
        manual_land = ManualLandService(
            context=context,
            parameters=parameters,
        )
        target_selector = TargetSelectorPublisher(config.selector_zmq_endpoint)
        return cls(
            config=config,
            parameters=parameters,
            visual_bridge=visual_bridge,
            drone=drone,
            joystick=joystick,
            mavlink=mavlink,
            rc_recorder=recorder,
            manual_land=manual_land,
            tracker_results=tracker_results,
            target_selector=target_selector,
        )

    @staticmethod
    def _load_parameters(config_name: str) -> Parameters:
        path = pathlib.Path(config_name)
        if not path.is_absolute():
            path = pathlib.Path.cwd().joinpath(path)
        if not path.exists():
            raise AppStartupError(f"Parameters config not found: {path}")
        log.info("load parameters from: {}", path)
        try:
            return Parameters(yaml_path=path)
        except Exception as exc:
            raise AppStartupError(
                f"Failed to load parameters from {path}: {exc}"
            ) from exc

    def start_all(self) -> None:
        try:
            self._start("visual bridge manager", self.visual_bridge)
            self._start_drone()
            self._start("joystick listener", self.joystick)
            self._start("MAVLink service", self.mavlink)
            self._start("RC state recorder", self.rc_recorder)
            self._start("target selector publisher", self.target_selector)
        except BaseException:
            self.stop_all()
            raise

    def _start(self, name: str, service: object) -> None:
        try:
            service.start()
        except Exception as exc:
            self._stop_resource(name, service)
            if isinstance(exc, AppStartupError):
                raise
            raise AppStartupError(f"Unable to start {name}: {exc}") from exc
        self._started.append((name, service))

    def _start_drone(self) -> None:
        transport_name, endpoint = self._fcu_connection_description()
        for attempt in range(1, FCU_CONNECT_ATTEMPTS + 1):
            try:
                self.drone.start()
                self._started.append(("MSP adapter", self.drone))
                return
            except OSError as exc:
                self.drone.msp.close()
                reason = self._connection_failure_reason(exc)
                if attempt == FCU_CONNECT_ATTEMPTS:
                    raise AppStartupError(
                        f"Unable to connect to FCU over {transport_name} at "
                        f"{endpoint} after {FCU_CONNECT_ATTEMPTS} attempts: "
                        f"{reason}",
                        exit_code=AppExitCode.FCU_CONNECTION_FAILED,
                    ) from exc
                log.warning(
                    "FCU connection failed transport={} endpoint={} "
                    "attempt={}/{} reason={}",
                    transport_name,
                    endpoint,
                    attempt,
                    FCU_CONNECT_ATTEMPTS,
                    reason,
                )
                time.sleep(FCU_CONNECT_RETRY_DELAY_S)
            except MspTransportDependencyError as exc:
                raise AppStartupError(
                    f"Unable to initialize FCU {transport_name} transport at "
                    f"{endpoint}: {exc}",
                    exit_code=AppExitCode.FCU_CONNECTION_FAILED,
                ) from exc

    def stop_all(self) -> None:
        started = {id(service) for _, service in self._started}
        resources = (
            ("MSP adapter", self.drone),
            ("visual bridge manager", self.visual_bridge),
            ("joystick listener", self.joystick),
            ("MAVLink service", self.mavlink),
            ("RC state recorder", self.rc_recorder),
            ("target selector publisher", getattr(self, "target_selector", None)),
            ("parameter service", self.parameters),
        )
        for name, service in resources:
            if id(service) in started or name == "parameter service":
                self._stop_resource(name, service)
        self._started.clear()

    @staticmethod
    def _stop_resource(name: str, service: object) -> None:
        stop = getattr(service, "stop", None)
        if stop is None:
            return
        try:
            stop()
        except Exception as exc:
            log.exception("Failed to stop {}: {}", name, exc)

    def _fcu_connection_description(self) -> tuple[str, str]:
        if self.config.drone_sink == DroneSink.SERIAL.value:
            return "serial", f"{self.config.drone_serial_port}@115200"
        return "TCP", f"{self.config.drone_eth_host}:{self.config.drone_eth_port}"

    @staticmethod
    def _connection_failure_reason(exc: OSError) -> str:
        if isinstance(exc, ConnectionRefusedError):
            return "connection refused"
        if isinstance(exc, TimeoutError):
            return "connection timed out"
        if isinstance(exc, PermissionError):
            return "permission denied"
        return str(exc) or exc.__class__.__name__
