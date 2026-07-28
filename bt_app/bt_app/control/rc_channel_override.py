from collections.abc import Callable
import threading
from loguru import logger as log

from bt_joy.server.mavlink import (
    CommunicationResumedEvent,
    CommunicationTimeoutStage,
    MavlinkServerConfig,
    MavlinkServerListener,
    NoCommunicationEvent,
    RcChannelsOverrideEvent,
)




class MavlinkListenerService:
    def __init__(
        self,
        config: MavlinkServerConfig,
        on_rc: Callable[[RcChannelsOverrideEvent], None],
        on_timeout: Callable[[NoCommunicationEvent], None],
        on_resume: Callable[[CommunicationResumedEvent], None],
    ) -> None:
        self.listener = MavlinkServerListener(
            config=config,
            on_rc_channels_override=on_rc,
            on_no_communication=on_timeout,
            on_communication_resumed=on_resume,
        )
        self.thread = threading.Thread(
            target=self.listener.run_forever,
            name="bt-joy-mavlink-listener",
            daemon=False,
        )

    def start(self) -> None:
        if self.thread.is_alive():
            return
        self.thread.start()
        log.info("Start mavlink rc_channel_override")

    def stop(self, timeout: float = 2.0) -> None:
        self.listener.stop()
        self.thread.join(timeout)
        if self.thread.is_alive():
            self.listener.close()
            self.thread.join(timeout)