"""Checks that do not need game files, a display, or game-folder writes."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from control_panel import Controller, Panel, atomic_write
from dave_profile import PATCHES, find_game
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

    def test_empty_game_folder_rejected_before_file_access(self):
        for value in ["", "  "]:
            with self.assertRaises(ValueError):
                Controller(value)

    def test_patch_ranges_are_valid_and_disjoint(self):
        ranges = []
        for feature, offset, before, after in PATCHES:
            self.assertEqual(len(before), len(after), feature)
            self.assertNotEqual(before, after, feature)
            ranges.append((offset, offset + len(before)))
        ranges.sort()
        for (_, end), (start, _) in zip(ranges, ranges[1:]):
            self.assertLessEqual(end, start)


class AtomicWriteTests(unittest.TestCase):
    def test_replaces_content_and_leaves_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "file.bin"
            path.write_bytes(b"old content that is longer")
            atomic_write(path, b"new")
            self.assertEqual(path.read_bytes(), b"new")
            self.assertEqual([p.name for p in Path(folder).iterdir()], ["file.bin"])

    def test_failed_replace_keeps_original(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "file.bin"
            path.write_bytes(b"old")
            with patch("control_panel.os.replace", side_effect=PermissionError("locked")):
                with self.assertRaises(PermissionError):
                    atomic_write(path, b"new")
            self.assertEqual(path.read_bytes(), b"old")
            self.assertEqual([p.name for p in Path(folder).iterdir()], ["file.bin"])


class FindGameTests(unittest.TestCase):
    def make_library(self, library, installdir="Dave the Diver"):
        (library / "steamapps").mkdir(parents=True, exist_ok=True)
        (library / "steamapps/appmanifest_1868140.acf").write_text(
            f'"AppState"\n{{\n\t"appid"\t\t"1868140"\n\t"installdir"\t\t"{installdir}"\n}}\n', "utf8")
        game = library / "steamapps/common" / installdir
        game.mkdir(parents=True, exist_ok=True)
        (game / "GameAssembly.dll").write_bytes(b"")
        return game

    def test_finds_game_in_secondary_library(self):
        with tempfile.TemporaryDirectory() as folder:
            steam, library = Path(folder) / "Steam", Path(folder) / "My \"Lib\""
            (steam / "steamapps").mkdir(parents=True)
            escaped = str(library).replace("\\", "\\\\").replace('"', '\\"')
            (steam / "steamapps/libraryfolders.vdf").write_text(
                f'"libraryfolders"\n{{\n\t"1"\n\t{{\n\t\t"path"\t\t"{escaped}"\n\t}}\n}}\n', "utf8")
            game = self.make_library(library)
            self.assertEqual(find_game([steam]), game)

    def test_missing_or_unsafe_installation_returns_none(self):
        with tempfile.TemporaryDirectory() as folder:
            steam = Path(folder) / "Steam"
            self.assertIsNone(find_game([steam]))
            self.make_library(steam, installdir="..")
            self.assertIsNone(find_game([steam]))


if __name__ == "__main__":
    unittest.main()
