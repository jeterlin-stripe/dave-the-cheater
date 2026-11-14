"""Checks that do not need game files, a display, or game-folder writes."""
import unittest
from control_panel import Controller, Panel
from gui_language import TRANSLATIONS, translate


class SourceTests(unittest.TestCase):
    def test_translations(self):
        for source, english in TRANSLATIONS.items():
            self.assertEqual(translate(source, "en"), english)
            self.assertEqual(translate(source, "zh-TW"), source)

    def test_invalid_speed_before_file_access(self):
        controller = Controller.__new__(Controller)
        for value in [0, -1, 21, float("nan"), float("inf"), "invalid"]:
            with self.assertRaises(ValueError):
                controller.build({"speed": value})

    def test_validation_error_translation(self):
        source = Panel.error_source(ValueError("could not convert string to float: 'abc'"))
        self.assertEqual(translate(source, "en"), "Enter a speed multiplier between 0.1 and 20.")


if __name__ == "__main__":
    unittest.main()
