import unittest

from garmin_fit.gui_validation import parse_builder_value, parse_repeat_count


class GuiValidationTests(unittest.TestCase):
    def test_invalid_integer_is_reported(self):
        value, error = parse_builder_value("hr_low", "abc", int)
        self.assertIsNone(value)
        self.assertIn("целое число", error)

    def test_heart_rate_range_is_reported(self):
        value, error = parse_builder_value("hr_high", "260", int)
        self.assertIsNone(value)
        self.assertIn("30–250", error)

    def test_distance_must_be_positive(self):
        value, error = parse_builder_value("km", "0", float)
        self.assertIsNone(value)
        self.assertIn("больше нуля", error)

    def test_valid_value_and_optional_empty_value(self):
        self.assertEqual(parse_builder_value("seconds", "300", int), (300, None))
        self.assertEqual(parse_builder_value("km", "", float), (None, None))

    def test_repeat_count_range(self):
        self.assertEqual(parse_repeat_count("6"), (6, None))
        value, error = parse_repeat_count("1")
        self.assertIsNone(value)
        self.assertIn("от 2 до 20", error)
