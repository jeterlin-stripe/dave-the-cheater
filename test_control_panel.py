import itertools
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import control_panel as panel
from inspect_dave import bundle_files


class ControlsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = [panel.HERE / "resources-upgrade/original/GameAssembly.dll", panel.HERE / "swim-1.5x/original" / panel.BUNDLE_NAME]
        if not all(path.is_file() for path in required):
            raise unittest.SkipTest("Prepare local original game backups first for file-integration tests.")
        cls.scratch = tempfile.TemporaryDirectory(prefix="dave-controls-")
        cls.game = Path(cls.scratch.name)
        cls.native = cls.game / "GameAssembly.dll"
        cls.bundle = cls.game / "DaveTheDiver_Data/StreamingAssets/aa/StandaloneWindows64" / panel.BUNDLE_NAME
        cls.bundle.parent.mkdir(parents=True)
        cls.controller = panel.Controller(cls.game)

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def setUp(self):
        self.native.write_bytes(self.controller.native_original)
        self.bundle.write_bytes(self.controller.bundle_original)

    def test_switch_combinations_and_speed(self):
        for ammo, invincible, oxygen in itertools.product([False, True], repeat=3):
            for factor in [0.1, 3.5, 20]:
                settings = dict(ammo=ammo, invincible=invincible, oxygen=oxygen, speed=factor)
                native, bundle = self.controller.build(settings)
                self.assertEqual(self.controller.decode_native(native), {**{k: settings[k] for k in ["ammo", "invincible", "oxygen"]}, "drone": False, "weapon_enabled": False, "weapon_id": panel.weapons.DEFAULT_ITEM})
                self.bundle.write_bytes(bundle)
                self.assertAlmostEqual(self.controller.decode_bundle()[0], factor, places=5)

    def test_bad_multiplier(self):
        for factor in [float("nan"), float("inf"), 0, -1, 21, "oops"]:
            with self.assertRaises((ValueError, TypeError)):
                self.controller.build(dict(ammo=True, invincible=True, oxygen=True, speed=factor))

    def test_drone_toggle_preserves_other_options(self):
        for ammo, invincible, oxygen in itertools.product([False, True], repeat=3):
            settings = dict(ammo=ammo, invincible=invincible, oxygen=oxygen, speed=3.5, drone=False)
            off, _ = self.controller.build(settings)
            on, _ = self.controller.build({**settings, "drone": True})
            allowed = {j for feature, offset, before, after in panel.PATCHES if feature == "drone" for j in range(offset, offset + len(before))}
            expected = bytearray(off)
            for feature, offset, before, after in panel.PATCHES:
                if feature == "drone":
                    self.assertEqual(off[offset:offset + len(before)], before)
                    expected[offset:offset + len(after)] = after
            self.assertEqual(on, bytes(expected))
            state = self.controller.decode_native(on)
            self.assertEqual(state, dict(ammo=ammo, invincible=invincible, oxygen=oxygen, drone=True, weapon_enabled=False, weapon_id=panel.weapons.DEFAULT_ITEM))
        with patch.object(panel, "game_running", return_value=False):
            self.controller.apply(dict(ammo=True, invincible=True, oxygen=True, speed=3.5, drone=True))
            self.assertTrue(self.controller.read()[0]["drone"])
            self.controller.apply(dict(ammo=True, invincible=True, oxygen=True, speed=3.5, drone=False))
            self.assertFalse(self.controller.read()[0]["drone"])

    def test_unknown_version_rejected(self):
        data = bytearray(self.controller.native_original)
        data[1000] ^= 1
        with self.assertRaises(ValueError):
            self.controller.decode_native(data)

    def test_running_game_blocks_write(self):
        with patch.object(panel, "game_running", return_value=True):
            with self.assertRaises(ValueError):
                self.controller.apply(dict(ammo=True, invincible=True, oxygen=True, speed=3.5))
        self.assertEqual(self.native.read_bytes(), self.controller.native_original)

    def test_apply_then_full_restore(self):
        with patch.object(panel, "game_running", return_value=False):
            state = self.controller.apply(dict(ammo=True, invincible=True, oxygen=True, speed=3.5))
            self.assertTrue(state["ammo"] and state["invincible"] and state["oxygen"])
            self.assertAlmostEqual(state["speed"], 3.5, places=5)
            self.controller.apply(dict(ammo=False, invincible=False, oxygen=False, speed=1))
        self.assertEqual(self.native.read_bytes(), self.controller.native_original)
        self.assertEqual(self.bundle.read_bytes(), self.controller.bundle_original)

    def test_weapon_adapter_enable_disable_and_restore(self):
        original = self.controller.native_original
        w = panel.weapons
        self.assertEqual(original[w.SWITCH_OFFSET:w.SWITCH_OFFSET + len(w.ORIGINAL_HEAD)], w.ORIGINAL_HEAD)
        self.assertEqual(original[w.LEGACY_OFFSET:w.LEGACY_OFFSET + len(w.LEGACY_ORIGINAL)], w.LEGACY_ORIGINAL)
        with patch.object(panel, "game_running", return_value=False):
            state = self.controller.apply(dict(ammo=True, invincible=True, oxygen=True, drone=True, speed=3.5, weapon_enabled=True, weapon_id=3010002))
            self.assertTrue(state["weapon_enabled"])
            self.assertEqual(self.native.read_bytes()[w.SWITCH_OFFSET:w.SWITCH_OFFSET + w.SWITCH_LENGTH], w.adapter())
            self.assertEqual(self.native.read_bytes()[w.LEGACY_OFFSET:w.LEGACY_OFFSET + len(w.LEGACY_ORIGINAL)], w.LEGACY_ORIGINAL)
            self.controller.apply(dict(ammo=False, invincible=False, oxygen=False, drone=False, speed=1, weapon_enabled=False))
        self.assertEqual(self.native.read_bytes(), original)
        self.assertEqual(self.bundle.read_bytes(), self.controller.bundle_original)

    def test_legacy_install_is_read_and_migrated(self):
        w = panel.weapons
        legacy = bytearray(self.controller.native_original)
        legacy[w.LEGACY_OFFSET:w.LEGACY_OFFSET + len(w.LEGACY_ORIGINAL)] = w.legacy_adapter(3010081)
        self.native.write_bytes(bytes(legacy))
        state = self.controller.decode_native(bytes(legacy))
        self.assertTrue(state["weapon_enabled"])
        with patch.object(panel, "game_running", return_value=False):
            self.controller.apply(dict(ammo=False, invincible=False, oxygen=False, drone=False, speed=1, weapon_enabled=True, weapon_id=3010081))
        data = self.native.read_bytes()
        self.assertEqual(data[w.LEGACY_OFFSET:w.LEGACY_OFFSET + len(w.LEGACY_ORIGINAL)], w.LEGACY_ORIGINAL)
        self.assertEqual(data[w.SWITCH_OFFSET:w.SWITCH_OFFSET + w.SWITCH_LENGTH], w.adapter())

    def test_v2_install_is_read_and_migrated(self):
        w = panel.weapons
        v2 = bytearray(self.controller.native_original)
        v2[w.SWITCH_OFFSET:w.SWITCH_OFFSET + w.SWITCH_LENGTH] = w.v2_adapter(3010081)
        self.native.write_bytes(bytes(v2))
        self.assertTrue(self.controller.decode_native(bytes(v2))["weapon_enabled"])
        with patch.object(panel, "game_running", return_value=False):
            self.controller.apply(dict(ammo=False, invincible=False, oxygen=False, drone=False, speed=1, weapon_enabled=True))
        self.assertEqual(self.native.read_bytes()[w.SWITCH_OFFSET:w.SWITCH_OFFSET + w.SWITCH_LENGTH], w.adapter())
        with patch.object(panel, "game_running", return_value=False):
            self.controller.apply(dict(ammo=False, invincible=False, oxygen=False, drone=False, speed=1, weapon_enabled=False))
        self.assertEqual(self.native.read_bytes(), self.controller.native_original)

    def test_second_write_failure_rolls_back_first(self):
        real_open = Path.open
        def guarded_open(path, *args, **kwargs):
            if path == self.bundle and args and args[0] == "r+b":
                raise PermissionError("Simulated locked bundle")
            return real_open(path, *args, **kwargs)
        with patch.object(panel, "game_running", return_value=False), patch.object(Path, "open", guarded_open):
            with self.assertRaises(OSError):
                self.controller.apply(dict(ammo=True, invincible=True, oxygen=True, speed=3.5))
        self.assertEqual(self.native.read_bytes(), self.controller.native_original)
        self.assertEqual(self.bundle.read_bytes(), self.controller.bundle_original)


if __name__ == "__main__":
    unittest.main()
