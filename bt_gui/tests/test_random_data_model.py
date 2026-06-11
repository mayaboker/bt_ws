import unittest

from bt_gui.models import RandomDataModel

from mock_data import make_random_values


class TestRandomDataModel(unittest.TestCase):
    def test_model_stores_mock_values(self) -> None:
        model = RandomDataModel()
        values = make_random_values()

        model.set_values(values)

        self.assertEqual(model.values(), values)

    def test_model_emits_mock_values(self) -> None:
        model = RandomDataModel()
        emitted: list[tuple[str, str, str]] = []

        model.values_changed.subscribe(emitted.append)
        model.set_values(make_random_values())

        self.assertEqual(emitted, [make_random_values()])


if __name__ == "__main__":
    unittest.main()
