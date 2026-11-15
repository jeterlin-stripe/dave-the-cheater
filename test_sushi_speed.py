import struct
import unittest
from unittest.mock import patch

import sushi_speed as s
import weapon_selector as w
from test_weapon_selector import BASE, SimulatedKernel


class SushiSpeedTests(unittest.TestCase):
    def test_layout_and_branch_targets(self):
        code = s.patched()
        self.assertEqual(len(code), s.LENGTH)
        self.assertEqual(code[:4], s.ORIGINAL[:4])  # same prologue as the function's unwind info

        def short(at):
            return at + 2 + struct.unpack_from("<b", code, at + 1)[0]
        self.assertEqual(code[0x0B:0x0E], bytes.fromhex("83f8ff"))
        self.assertEqual(short(0x0E), 0x4B)        # no move type -> return 0
        for at in (0x17, 0x20, 0x25):              # null/range checks -> throw
            self.assertEqual(short(at), 0x31)
        self.assertEqual(code[0x2F], 0x75)         # last null check skips over the throw
        self.assertEqual(short(0x2F), 0x36)
        self.assertEqual(code[0x31], 0xE8)
        self.assertEqual(s.GETTER_RVA + 0x36 + struct.unpack_from("<i", code, 0x32)[0], s.THROW_RVA)
        self.assertEqual(code[0x3B:0x3F], bytes.fromhex("f30f100d"))
        self.assertEqual(s.GETTER_RVA + 0x43 + struct.unpack_from("<i", code, 0x3F)[0], s.SLOT_RVA)
        self.assertEqual(code[0x4B:], bytes.fromhex("4883c428c3"))

    def test_original_throw_target_is_reused(self):
        self.assertEqual(s.ORIGINAL[0x47], 0xE8)
        self.assertEqual(s.GETTER_RVA + 0x4C + struct.unpack_from("<i", s.ORIGINAL, 0x48)[0], s.THROW_RVA)

    def test_slot_is_separate_unused_rw_slack(self):
        self.assertLessEqual(w.DATA_END_RVA, s.SLOT_RVA)
        self.assertLessEqual(s.SLOT_RVA + 4, w.NEXT_SECTION_RVA)
        self.assertEqual(s.SLOT_RVA % 4, 0)
        self.assertFalse(s.SLOT_RVA < w.PENDING_RVA + 4 and w.PENDING_RVA < s.SLOT_RVA + 4)
        self.assertEqual(s.PDATA_END_PATCHED, 0xC26300)  # next function start

    def test_slot_values(self):
        self.assertEqual(s.slot_value(1), bytes(4))  # zeroed slack = 1x
        self.assertEqual(struct.unpack("<f", s.slot_value(2.5))[0], 1.5)
        self.assertAlmostEqual(struct.unpack("<f", s.slot_value(0.1))[0], -0.9, places=6)
        for factor in (0, 0.09, 10.5, -1, float("inf"), float("nan"), "fast", None):
            with self.assertRaises(ValueError):
                s.slot_value(factor)

    def test_install_detection(self):
        self.assertFalse(s.is_installed(s.ORIGINAL))
        self.assertTrue(s.is_installed(s.patched()))
        tampered = bytearray(s.patched()); tampered[0x10] ^= 1
        with self.assertRaises(ValueError):
            s.is_installed(bytes(tampered))

    def test_apply_and_normalize(self):
        data = bytearray(s.PDATA_END_OFFSET + 16)
        data[s.OFFSET:s.OFFSET + s.LENGTH] = s.ORIGINAL
        struct.pack_into("<I", data, s.PDATA_END_OFFSET, s.PDATA_END_ORIGINAL)
        original = bytes(data)
        s.apply(data, False)
        self.assertEqual(bytes(data), original)
        s.apply(data, True)
        self.assertEqual(struct.unpack_from("<I", data, s.PDATA_END_OFFSET)[0], s.PDATA_END_PATCHED)
        with self.assertRaises(ValueError):
            s.apply(data, True)  # never stacks on an already-patched body
        self.assertTrue(s.normalize(data))
        self.assertEqual(bytes(data), original)
        # Body and unwind end must agree.
        data[s.OFFSET:s.OFFSET + s.LENGTH] = s.patched()
        with self.assertRaises(ValueError):
            s.normalize(data)

    def kernel(self, site):
        api = SimulatedKernel("C:/Games/Dave")
        api.regions = {BASE + s.GETTER_RVA: bytearray(site), BASE + s.SLOT_RVA: bytearray(4)}
        return api

    def test_simulated_live_write(self):
        api = self.kernel(s.patched())
        with patch.object(w.ctypes, "WinDLL", return_value=api):
            self.assertEqual(s.set_live(api.game, 2), 2.0)
        self.assertEqual(api.writes, [(BASE + s.SLOT_RVA, 4)])
        self.assertEqual(struct.unpack("<f", api.regions[BASE + s.SLOT_RVA])[0], 1.0)
        self.assertEqual(bytes(api.regions[BASE + s.GETTER_RVA]), s.patched())

    def test_simulated_unpatched_or_unknown_game_blocks_writes(self):
        tampered = bytearray(s.patched()); tampered[5] ^= 1
        for site in (s.ORIGINAL, bytes(tampered)):
            api = self.kernel(site)
            with patch.object(w.ctypes, "WinDLL", return_value=api):
                with self.assertRaises(ValueError):
                    s.set_live(api.game, 2)
            self.assertEqual(api.writes, [])

    def test_invalid_factor_before_process_access(self):
        with patch.object(w.ctypes, "WinDLL") as api:
            with self.assertRaises(ValueError):
                s.set_live("unused", 50)
            api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
