from bt_app.control.joy_zmq_adapter import JoyZmqAdapter, SUB_FAILSAFE_TOPIC, SUB_STATE_TOPIC
from bt_app.parameters.generated import ParameterKey


class FakeParams:
    def __init__(self, timeout_s=0.5):
        self.timeout_s = timeout_s
        self.declared = []

    def declare(self, name, default, limits=None, value_type=None):
        self.declared.append((name, default, limits, value_type))
        if name == ParameterKey.JOY_TIMEOUT:
            return self.timeout_s
        return default


class ExistingParamStore:
    def __init__(self, timeout_s=0.75):
        self.timeout_s = timeout_s
        self.declare_called = False

    def get(self, name):
        if name == ParameterKey.JOY_TIMEOUT:
            return self.timeout_s
        raise KeyError(name)

    def declare(self, name, default, limits=None, value_type=None):
        self.declare_called = True
        return default


class FakeParameterEvent:
    def __init__(self):
        self.subscribers = []

    def subscribe(self, callback):
        self.subscribers.append(callback)


def test_existing_timeout_parameter_is_read_without_redeclare():
    params = ExistingParamStore()

    adapter = JoyZmqAdapter(params)

    assert adapter.server_timeout_s == 0.75
    assert params.declare_called is False


def test_timeout_parameter_change_applies_live():
    params = ExistingParamStore()
    params.on_parameter_changed = FakeParameterEvent()
    adapter = JoyZmqAdapter(params)

    params.on_parameter_changed.subscribers[0](ParameterKey.JOY_TIMEOUT, 2.5)

    assert adapter.server_timeout_s == 2.5


def test_server_timeout_is_not_reported_before_first_valid_message():
    adapter = JoyZmqAdapter(FakeParams())
    entered = []
    adapter.on_failsafe_enter += lambda: entered.append(True)

    adapter._check_server_timeout(10.0)

    assert entered == []


def test_first_valid_message_starts_timeout_tracking_and_times_out_once():
    adapter = JoyZmqAdapter(FakeParams(timeout_s=0.5))
    entered = []
    adapter.on_failsafe_enter += lambda: entered.append(True)

    adapter._handle_message(SUB_STATE_TOPIC, {"channels": [1500, 1500, 1000]}, 10.0)
    adapter._check_server_timeout(10.49)
    adapter._check_server_timeout(10.50)
    adapter._check_server_timeout(11.00)

    assert adapter.last_rc_channels == [1500, 1500, 1000]
    assert entered == [True]


def test_valid_message_after_timeout_reports_recovery_once():
    adapter = JoyZmqAdapter(FakeParams(timeout_s=0.5))
    entered = []
    exited = []
    adapter.on_failsafe_enter += lambda: entered.append(True)
    adapter.on_failsafe_exit += lambda: exited.append(True)

    adapter._handle_message(SUB_STATE_TOPIC, {"channels": [1500]}, 10.0)
    adapter._check_server_timeout(10.50)
    adapter._handle_message(SUB_STATE_TOPIC, {"channels": [1600]}, 11.0)
    adapter._handle_message(SUB_STATE_TOPIC, {"channels": [1700]}, 11.1)

    assert adapter.last_rc_channels == [1700]
    assert entered == [True]
    assert exited == [True]


def test_timeout_can_recur_after_recovery():
    adapter = JoyZmqAdapter(FakeParams(timeout_s=0.5))
    entered = []
    exited = []
    adapter.on_failsafe_enter += lambda: entered.append(True)
    adapter.on_failsafe_exit += lambda: exited.append(True)

    adapter._handle_message(SUB_STATE_TOPIC, {"channels": [1500]}, 10.0)
    adapter._check_server_timeout(10.50)
    adapter._handle_message(SUB_STATE_TOPIC, {"channels": [1600]}, 11.0)
    adapter._check_server_timeout(11.50)

    assert entered == [True, True]
    assert exited == [True]


def test_explicit_failsafe_messages_still_emit_events():
    adapter = JoyZmqAdapter(FakeParams())
    entered = []
    exited = []
    adapter.on_failsafe_enter += lambda: entered.append(True)
    adapter.on_failsafe_exit += lambda: exited.append(True)

    adapter._handle_message(SUB_FAILSAFE_TOPIC, {"active": True}, 10.0)
    adapter._handle_message(SUB_FAILSAFE_TOPIC, {"active": False}, 10.1)

    assert entered == [True]
    assert exited == [True]


def test_explicit_failsafe_clear_after_timeout_emits_one_exit():
    adapter = JoyZmqAdapter(FakeParams(timeout_s=0.5))
    entered = []
    exited = []
    adapter.on_failsafe_enter += lambda: entered.append(True)
    adapter.on_failsafe_exit += lambda: exited.append(True)

    adapter._handle_message(SUB_STATE_TOPIC, {"channels": [1500]}, 10.0)
    adapter._check_server_timeout(10.50)
    adapter._handle_message(SUB_FAILSAFE_TOPIC, {"active": False}, 11.0)

    assert entered == [True]
    assert exited == [True]


def test_explicit_failsafe_active_after_timeout_does_not_emit_recovery_exit():
    adapter = JoyZmqAdapter(FakeParams(timeout_s=0.5))
    entered = []
    exited = []
    adapter.on_failsafe_enter += lambda: entered.append(True)
    adapter.on_failsafe_exit += lambda: exited.append(True)

    adapter._handle_message(SUB_STATE_TOPIC, {"channels": [1500]}, 10.0)
    adapter._check_server_timeout(10.50)
    adapter._handle_message(SUB_FAILSAFE_TOPIC, {"active": True}, 11.0)

    assert entered == [True, True]
    assert exited == []


def test_invalid_state_payload_does_not_start_timeout_tracking():
    adapter = JoyZmqAdapter(FakeParams(timeout_s=0.5))
    entered = []
    adapter.on_failsafe_enter += lambda: entered.append(True)

    adapter._handle_message(SUB_STATE_TOPIC, {"not_channels": [1500]}, 10.0)
    adapter._check_server_timeout(11.0)

    assert adapter.last_rc_channels == []
    assert entered == []
