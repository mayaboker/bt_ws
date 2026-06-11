"""MSP output adapter for parsed bt_joy channel frames."""

from __future__ import annotations

import time
from typing import Callable, TypeVar

from loguru import logger

from bt_joy.server.command_dispatcher import MspCommandDispatcher
from bt_joy.server.config import MspServerConfig
from bt_joy.server.msp import MspBuildInfo, MspClient
from bt_joy.server.state import ServerStateSnapshot, ServerStateStore

T = TypeVar("T")


class StartupProbeError(RuntimeError):
    pass


class MspOutputAdapter:
    def __init__(self, transport, config: MspServerConfig) -> None:
        self.transport = transport
        self.config = config
        self.client: MspClient | None = None
        self.dispatcher: MspCommandDispatcher | None = None
        self.state_store = ServerStateStore()

    def __enter__(self) -> "MspOutputAdapter":
        self.transport.__enter__()
        self.client = MspClient(self.transport)
        self.dispatcher = MspCommandDispatcher(
            self.client,
            state_store=self.state_store,
            on_error=self._handle_dispatcher_error,
        )
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.dispatcher is not None:
            self.dispatcher.stop()
            self.dispatcher = None
        self.client = None
        self.transport.__exit__(*_exc)

    def startup_check(self) -> None:
        _read_startup_info(
            self._require_client(),
            self.config.status_timeout,
            attempts=self.config.startup_probe_attempts,
            interval_s=self.config.startup_probe_interval,
        )
        self._start_dispatcher()

    def write_channels(
        self,
        channels: list[int],
        sequence: int,
        timestamp_us: int,
    ) -> None:
        del sequence, timestamp_us
        self._require_dispatcher().set_rc(channels, rate_hz=self.config.rc_rate_hz)

    def enter_failsafe(self, reason: str) -> None:
        logger.warning("entering failsafe mode: {}", reason)
        self._require_dispatcher().set_rc(
            self.config.failsafe_channels,
            rate_hz=self.config.rc_rate_hz,
        )

    def exit_failsafe(self) -> None:
        logger.warning("exiting failsafe mode; client data recovered")

    def tick(self) -> None:
        pass

    def snapshot(self) -> ServerStateSnapshot:
        return self.state_store.snapshot()

    def _require_client(self) -> MspClient:
        if self.client is None:
            raise RuntimeError("MSP adapter is not open")
        return self.client

    def _require_dispatcher(self) -> MspCommandDispatcher:
        if self.dispatcher is None:
            raise RuntimeError("MSP dispatcher is not open")
        return self.dispatcher

    def _start_dispatcher(self) -> None:
        dispatcher = self._require_dispatcher()
        dispatcher.start()
        if self.config.status_interval > 0:
            dispatcher.schedule_function(
                lambda command_dispatcher: _read_status(
                    command_dispatcher,
                    self.config.status_timeout,
                ),
                interval_s=self.config.status_interval,
                delay_s=self.config.status_interval,
                key="status",
            )
        if self.config.rc_read_interval > 0:
            dispatcher.schedule_function(
                lambda command_dispatcher: _read_rc(
                    command_dispatcher,
                    self.config.rc_read_timeout,
                ),
                interval_s=self.config.rc_read_interval,
                delay_s=self.config.rc_read_interval,
                key="rc_read",
            )
        if self.config.altitude_interval > 0:
            dispatcher.schedule_function(
                lambda command_dispatcher: _read_altitude(
                    command_dispatcher,
                    self.config.altitude_timeout,
                ),
                interval_s=self.config.altitude_interval,
                delay_s=self.config.altitude_interval,
                key="altitude",
            )

    def _handle_dispatcher_error(self, exc: BaseException) -> None:
        logger.warning("MSP dispatcher command failed: {}", exc)


def _read_startup_info(
    client: MspClient,
    timeout: float,
    attempts: int = 3,
    interval_s: float = 1.0,
) -> None:
    logger.info("reading Betaflight MSP version info before starting joystick forwarding")

    api_version = _read_required_startup_value(
        "MSP_API_VERSION",
        lambda: client.read_api_version(timeout=timeout),
        attempts,
        interval_s,
    )
    logger.info("MSP_API_VERSION {}", api_version)

    fc_variant = _read_required_startup_value(
        "MSP_FC_VARIANT",
        lambda: client.read_fc_variant(timeout=timeout),
        attempts,
        interval_s,
    )
    logger.info("MSP_FC_VARIANT {}", fc_variant)

    fc_version = _read_required_startup_value(
        "MSP_FC_VERSION",
        lambda: client.read_fc_version(timeout=timeout),
        attempts,
        interval_s,
    )
    logger.info("MSP_FC_VERSION {}", fc_version)

    try:
        board_info = client.read_board_info(timeout=timeout)
    except Exception as exc:
        logger.warning("MSP_BOARD_INFO read failed: {}", exc)
    else:
        logger.info(
            "MSP_BOARD_INFO identifier={} hardware_revision={} payload_hex={}",
            board_info.identifier,
            board_info.hardware_revision,
            board_info.raw.hex(),
        )

    try:
        build_info = client.read_build_info(timeout=timeout)
    except Exception as exc:
        logger.warning("MSP_BUILD_INFO read failed: {}", exc)
    else:
        logger.info("MSP_BUILD_INFO {} payload_hex={}", _format_build_info(build_info), build_info.raw.hex())

    _read_status(client, timeout)
    logger.info("MSP startup probe complete; starting joystick forwarding")


def _read_required_startup_value(
    label: str,
    read_value: Callable[[], T],
    attempts: int,
    interval_s: float,
) -> T:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return read_value()
        except Exception as exc:
            last_error = exc
            logger.warning("{} read failed attempt {}/{}: {}", label, attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(interval_s)

    raise StartupProbeError(f"{label} read failed after {attempts} attempts: {last_error}") from last_error


def _format_build_info(build_info: MspBuildInfo) -> str:
    parts = []
    if build_info.date:
        parts.append(build_info.date)
    if build_info.time:
        parts.append(build_info.time)
    if build_info.revision:
        parts.append(f"revision={build_info.revision}")
    return " ".join(parts) if parts else "unparsed"


def _read_status(dispatcher: MspCommandDispatcher | MspClient, timeout: float) -> None:
    client = dispatcher.msp if isinstance(dispatcher, MspCommandDispatcher) else dispatcher
    try:
        status = client.read_status(timeout=timeout)
    except TimeoutError:
        logger.warning("MSP_STATUS_EX timeout after {:.3f}s", timeout)
        return
    except Exception as exc:
        logger.warning("MSP_STATUS_EX read failed: {}", exc)
        return

    if isinstance(dispatcher, MspCommandDispatcher):
        dispatcher.record_status(status)

    logger.debug(
        "MSP_STATUS_EX cycle_time_us={} i2c_errors={} sensors_mask=0x{:04x} "
        "box_mode_flags=0x{:08x} config_profile={} system_load={} "
        "pid_profiles={} control_rate_profile={} arming_disabled_flags=0x{:08x} "
        "arming_disabled={}",
        status.cycle_time_us,
        status.i2c_errors,
        status.sensors_mask,
        status.box_mode_flags,
        status.config_profile,
        status.average_system_load_percent,
        status.pid_profile_count,
        status.control_rate_profile,
        status.arming_disabled_flags or 0,
        ",".join(status.arming_disabled_flag_names) if status.arming_disabled_flag_names else "none",
    )


def _read_rc(dispatcher: MspCommandDispatcher, timeout: float) -> None:
    try:
        channels = dispatcher.msp.read_rc(timeout=timeout)
    except TimeoutError:
        logger.warning("MSP_RC timeout after {:.3f}s", timeout)
        return
    except Exception as exc:
        logger.warning("MSP_RC read failed: {}", exc)
        return

    dispatcher.record_rc(channels)
    logger.debug("MSP_RC channels={}", channels)


def _read_altitude(dispatcher: MspCommandDispatcher, timeout: float) -> None:
    try:
        altitude = dispatcher.msp.read_altitude(timeout=timeout)
    except TimeoutError:
        logger.warning("MSP_ALTITUDE timeout after {:.3f}s", timeout)
        return
    except Exception as exc:
        logger.warning("MSP_ALTITUDE read failed: {}", exc)
        return

    dispatcher.record_altitude(altitude)
    logger.debug(
        "MSP_ALTITUDE altitude_m={:.2f} vertical_speed_m_s={:.2f}",
        altitude.altitude_m,
        altitude.vertical_speed_m_s,
    )
