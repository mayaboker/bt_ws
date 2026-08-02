import pytest

from bt_app.msp.alt_hold_test import (
    AUX1_ARM,
    AUX2_ANGLE,
    AUX3_ALT_HOLD,
    RC_MAX,
    RC_MID,
    RC_MIN,
    THROTTLE,
    AltHoldFlightTest,
    AltHoldTestConfig,
    FlightPhase,
)


def make_config(**overrides):
    values = {
        "prearm_duration_s": 1.0,
        "arm_duration_s": 1.0,
        "hold_duration_s": 2.0,
        "disarm_duration_s": 0.5,
        "target_settle_s": 0.5,
        "landed_settle_s": 0.5,
        "telemetry_loss_grace_s": 1.0,
        "takeoff_timeout_s": 10.0,
    }
    values.update(overrides)
    return AltHoldTestConfig(**values)


def advance_to_takeoff(controller):
    controller.channels(1.0)
    assert controller.phase is FlightPhase.ARM
    controller.channels(2.0)
    assert controller.phase is FlightPhase.TAKEOFF


def test_channel_mapping_for_prearm_arm_and_takeoff():
    controller = AltHoldFlightTest(make_config(), 0.0, 0.0)

    prearm = controller.channels(0.0)
    assert prearm == (1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000)

    armed = controller.channels(1.0)
    assert armed[THROTTLE] == RC_MIN
    assert armed[AUX1_ARM] == RC_MAX
    assert armed[AUX2_ANGLE] == RC_MAX
    assert armed[AUX3_ALT_HOLD] == RC_MIN

    takeoff = controller.channels(2.0)
    assert takeoff[THROTTLE] > RC_MID
    assert takeoff[AUX1_ARM] == RC_MAX
    assert takeoff[AUX2_ANGLE] == RC_MAX
    assert takeoff[AUX3_ALT_HOLD] == RC_MIN


def test_aux3_activates_only_after_target_settles():
    controller = AltHoldFlightTest(make_config(), 0.0, 0.0)
    advance_to_takeoff(controller)

    controller.update_telemetry(3.7, 0.1, 2.1)
    first_near_target = controller.channels(2.1)
    assert first_near_target[AUX3_ALT_HOLD] == RC_MIN

    controller.update_telemetry(3.9, 0.0, 2.5)
    not_settled = controller.channels(2.5)
    assert not_settled[AUX3_ALT_HOLD] == RC_MIN

    controller.update_telemetry(4.0, 0.0, 2.6)
    holding = controller.channels(2.6)
    assert controller.phase is FlightPhase.HOLD
    assert holding[THROTTLE] == RC_MID
    assert holding[AUX1_ARM] == RC_MAX
    assert holding[AUX2_ANGLE] == RC_MAX
    assert holding[AUX3_ALT_HOLD] == RC_MAX


def test_hold_duration_then_landing_and_disarm():
    controller = AltHoldFlightTest(make_config(), 0.0, 0.0)
    advance_to_takeoff(controller)
    controller.update_telemetry(4.0, 0.0, 2.1)
    controller.channels(2.1)
    controller.update_telemetry(4.0, 0.0, 2.6)
    controller.channels(2.6)
    assert controller.phase is FlightPhase.HOLD

    landing = controller.channels(4.61)
    assert controller.phase is FlightPhase.LAND
    assert landing[AUX1_ARM] == RC_MAX
    assert landing[AUX2_ANGLE] == RC_MAX
    assert landing[AUX3_ALT_HOLD] == RC_MIN
    assert landing[THROTTLE] < RC_MID

    controller.update_telemetry(0.1, 0.1, 4.7)
    controller.channels(4.7)
    controller.update_telemetry(0.1, 0.0, 5.21)
    disarmed = controller.channels(5.21)
    assert controller.phase is FlightPhase.DISARM
    assert disarmed[AUX1_ARM] == RC_MIN
    assert disarmed[THROTTLE] == RC_MIN

    controller.channels(5.71)
    assert controller.phase is FlightPhase.COMPLETE


@pytest.mark.parametrize(
    ("config", "now", "altitude"),
    [
        (make_config(max_altitude_m=5.0), 2.1, 5.0),
        (make_config(takeoff_timeout_s=1.0), 3.0, 2.0),
    ],
)
def test_takeoff_guards_start_controlled_landing(config, now, altitude):
    controller = AltHoldFlightTest(config, 0.0, 0.0)
    advance_to_takeoff(controller)
    controller.update_telemetry(altitude, 0.0, now)

    channels = controller.channels(now)

    assert controller.phase is FlightPhase.LAND
    assert channels[AUX1_ARM] == RC_MAX
    assert channels[AUX2_ANGLE] == RC_MAX
    assert channels[AUX3_ALT_HOLD] == RC_MIN


def test_telemetry_loss_uses_neutral_alt_hold_and_never_disarms():
    controller = AltHoldFlightTest(make_config(), 0.0, 0.0)
    advance_to_takeoff(controller)

    controller.mark_telemetry_failure(2.1)
    grace_channels = controller.channels(2.1)
    assert controller.phase is FlightPhase.TAKEOFF
    assert grace_channels[THROTTLE] == RC_MID
    assert grace_channels[AUX1_ARM] == RC_MAX
    assert grace_channels[AUX2_ANGLE] == RC_MAX
    assert grace_channels[AUX3_ALT_HOLD] == RC_MAX

    controller.mark_telemetry_failure(3.1)
    failsafe_channels = controller.channels(30.0)
    assert controller.phase is FlightPhase.TELEMETRY_FAILSAFE
    assert failsafe_channels[AUX1_ARM] == RC_MAX
    assert failsafe_channels[AUX3_ALT_HOLD] == RC_MAX


def test_telemetry_recovery_from_failsafe_starts_landing():
    controller = AltHoldFlightTest(make_config(), 0.0, 0.0)
    advance_to_takeoff(controller)
    controller.mark_telemetry_failure(2.1)
    controller.mark_telemetry_failure(3.1)
    assert controller.phase is FlightPhase.TELEMETRY_FAILSAFE

    controller.update_telemetry(3.0, 0.0, 3.2)
    channels = controller.channels(3.2)

    assert controller.phase is FlightPhase.LAND
    assert channels[AUX1_ARM] == RC_MAX
    assert channels[AUX2_ANGLE] == RC_MAX
    assert channels[AUX3_ALT_HOLD] == RC_MIN


def test_telemetry_loss_before_takeoff_refuses_to_arm_blindly():
    controller = AltHoldFlightTest(make_config(), 0.0, 0.0)

    with pytest.raises(RuntimeError, match="before takeoff"):
        controller.mark_telemetry_failure(0.1)


def test_invalid_max_altitude_is_rejected():
    with pytest.raises(ValueError, match="above target"):
        AltHoldFlightTest(
            make_config(max_altitude_m=4.0),
            start_time=0.0,
            initial_altitude_m=0.0,
        )
