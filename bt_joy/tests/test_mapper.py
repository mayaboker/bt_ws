import unittest

from bt_joy.client.config import ChannelConfig
from bt_joy.client.joystick import JoystickState
from bt_joy.client.mapper import map_channels


class MapperTest(unittest.TestCase):
    def test_maps_axis_button_and_constant_channels(self) -> None:
        state = JoystickState(axes=[0, 32767], buttons=[0, 1])
        channels = (
            ChannelConfig(name="roll", source="axis", index=0),
            ChannelConfig(name="pitch", source="axis", index=1),
            ChannelConfig(name="arm", source="button", index=1, off=1000, on=2000),
            ChannelConfig(name="aux", source="constant", value=1500),
        )

        self.assertEqual(map_channels(state, channels), [1500, 2000, 2000, 1500])

    def test_applies_axis_inversion_and_deadband(self) -> None:
        state = JoystickState(axes=[100], buttons=[])
        channels = (
            ChannelConfig(
                name="yaw",
                source="axis",
                index=0,
                deadband=0.03,
                invert=True,
            ),
        )

        self.assertEqual(map_channels(state, channels), [1500])


if __name__ == "__main__":
    unittest.main()
