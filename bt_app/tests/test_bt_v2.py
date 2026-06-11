from bt_app.msp.bt_v2 import RCChannel, RCChannel_alias


def test_rc_channel_count_is_8():
    assert len(RCChannel) == 8


def test_rc_channel_alias_count_is_8():
    assert len(RCChannel_alias) == 8
