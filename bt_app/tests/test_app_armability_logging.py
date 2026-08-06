from types import SimpleNamespace

import bt_app.app as app_module
from bt_app.app import App


class CapturingLog:
    def __init__(self):
        self.messages = []

    def warning(self, message, *args):
        self.messages.append(("warning", message.format(*args)))

    def success(self, message, *args):
        self.messages.append(("success", message.format(*args)))


def test_armability_logs_only_on_readiness_transitions(monkeypatch) -> None:
    captured = CapturingLog()
    monkeypatch.setattr(app_module, "log", captured)
    app = App.__new__(App)
    app.ctx = SimpleNamespace(
        armable=False,
        arming_disable_flags=["RX_FAILSAFE", "CALIBRATING"],
    )
    app._last_logged_armable = None

    app._log_armability_transition()
    app._log_armability_transition()
    app.ctx.arming_disable_flags = ["RX_FAILSAFE"]
    app._log_armability_transition()

    app.ctx.armable = True
    app.ctx.arming_disable_flags = []
    app._log_armability_transition()
    app._log_armability_transition()

    app.ctx.armable = False
    app.ctx.arming_disable_flags = ["FAILSAFE"]
    app._log_armability_transition()

    assert captured.messages == [
        ("warning", "Vehicle is not ready to arm: RX_FAILSAFE, CALIBRATING"),
        ("success", "Vehicle is ready to arm"),
        ("warning", "Vehicle is not ready to arm: FAILSAFE"),
    ]
