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
                self.assertEqual(self.controller.decode_native(native), {**{k: settings[k] for k in ["ammo", "invincible", "oxygen"]}, "drone": False, "weapon_enabled": False, "weapon_id": panel.weapons.DEFAULT_ITEM, "sushi_live": False, "swim_live": False, "backpack_live": False})
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
            self.assertEqual(state, dict(ammo=ammo, invincible=invincible, oxygen=oxygen, drone=True, weapon_enabled=False, weapon_id=panel.weapons.DEFAULT_ITEM, sushi_live=False, swim_live=False, backpack_live=False))
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

    def test_sushi_live_with_other_features_and_restore(self):
        s = panel.sushi_speed
        original = self.controller.native_original
        self.assertEqual(original[s.OFFSET:s.OFFSET + s.LENGTH], s.ORIGINAL)
        base = dict(ammo=True, invincible=True, oxygen=True, drone=True, speed=3.5, weapon_enabled=True)
        without, _ = self.controller.build(base)
        native, _ = self.controller.build({**base, "sushi_live": True})
        state = self.controller.decode_native(native)
        self.assertTrue(state["sushi_live"] and state["weapon_enabled"] and state["drone"] and state["oxygen"])
        self.assertFalse(self.controller.decode_native(without)["sushi_live"])
        changed = {i for i in range(len(native)) if native[i] != without[i]}
        allowed = set(range(s.OFFSET, s.OFFSET + s.LENGTH)) | set(range(s.PDATA_END_OFFSET, s.PDATA_END_OFFSET + 4))
        self.assertTrue(changed and changed <= allowed)
        with patch.object(panel, "game_running", return_value=False):
            self.assertTrue(self.controller.apply({**base, "sushi_live": True})["sushi_live"])
            self.controller.apply(dict(ammo=False, invincible=False, oxygen=False, speed=1))
        self.assertEqual(self.native.read_bytes(), original)

    def test_live_multipliers_with_other_features_and_restore(self):
        live = panel.live
        original = self.controller.native_original
        base = dict(ammo=True, invincible=False, oxygen=True, drone=True, speed=1, weapon_enabled=True, sushi_live=True)
        without, _ = self.controller.build(base)
        for features in ({"swim_live"}, {"backpack_live"}, {"swim_live", "backpack_live"}):
            native, _ = self.controller.build({**base, **{f: True for f in features}})
            state = self.controller.decode_native(native)
            for feature in panel.LIVE_FEATURES:
                self.assertEqual(state[feature], feature in features)
            self.assertTrue(state["sushi_live"] and state["weapon_enabled"] and state["drone"] and state["oxygen"])
            changed = {i for i in range(len(native)) if native[i] != without[i]}
            allowed = {rva - live.IL2CPP_DELTA + k for f in features for rva, before, _ in live.FEATURES[f] for k in range(len(before))}
            self.assertTrue(changed and changed <= allowed)
        with patch.object(panel, "game_running", return_value=False):
            state = self.controller.apply({**base, "swim_live": True, "backpack_live": True})
            self.assertTrue(state["swim_live"] and state["backpack_live"] and state["sushi_live"])
            self.controller.apply(dict(ammo=False, invincible=False, oxygen=False, speed=1))
        self.assertEqual(self.native.read_bytes(), original)
        self.assertEqual(self.bundle.read_bytes(), self.controller.bundle_original)

    def test_live_hook_sites_are_original_and_caves_are_padding(self):
        """Every hook site holds its expected instruction; every routine lands in int3 padding outside .pdata."""
        import bisect, struct
        live = panel.live
        data = self.controller.native_original
        pdata_raw, pdata_size = 0x7C69C00, 0x4D29A4
        entries = sorted(e for e in (struct.unpack_from("<III", data, pdata_raw + i * 12) for i in range(pdata_size // 12)) if e[0])
        begins = [e[0] for e in entries]
        for feature, regions in live.FEATURES.items():
            for rva, before, after in regions:
                self.assertEqual(data[rva - live.IL2CPP_DELTA:rva - live.IL2CPP_DELTA + len(before)], before)
                if before == bytes([live.CC]) * len(before):
                    index = bisect.bisect_right(begins, rva) - 1
                    self.assertLessEqual(entries[index][1], rva)                        # after the previous function's unwind range
                    following = begins[index + 1]
                    self.assertLessEqual(rva + len(after), following)                  # before the next function
                    self.assertEqual(data[rva - live.IL2CPP_DELTA:following - live.IL2CPP_DELTA],
                                     bytes([live.CC]) * (following - rva))           # all padding up to it

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
