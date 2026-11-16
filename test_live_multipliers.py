import struct
import unittest
from unittest.mock import patch

import live_multipliers as live
import sushi_speed
import weapon_selector as w
from test_weapon_selector import BASE, SimulatedKernel

# Padding runs (RVA, length) the routines live in, from the supported build.
CAVES = {0x7C00C3: 13, 0x7C4871: 15, 0x1C5C2E1: 15, 0x1C5F5B1: 15, 0x1AA7553: 13, 0x1AA87E1: 15, 0x1A9CF52: 14, 0x1A96FE1: 15}


def follow(rva, code):
    """Targets of the rel32 call/jmp at the start/end and the rip-relative movss load, if any."""
    found = {}
    if code[0] in (0xE8, 0xE9):
        found["branch"] = rva + 5 + struct.unpack_from("<i", code, 1)[0]
    if code[-5] == 0xE9:
        found["branch"] = rva + len(code) + struct.unpack_from("<i", code, len(code) - 4)[0]
    if code[:3] == bytes.fromhex("f30f10") and code[3] & 0xC7 == 0x05:
        found["slot"] = rva + 8 + struct.unpack_from("<i", code, 4)[0]
    return found


class LiveMultiplierTests(unittest.TestCase):
    def test_routines_fit_their_caves_and_do_not_overlap(self):
        ranges = []
        for regions in live.FEATURES.values():
            for rva, before, after in regions:
                self.assertEqual(len(before), len(after))
                if before == bytes([live.CC]) * len(before):
                    self.assertLessEqual(len(after), CAVES[rva])
                ranges.append((rva, rva + len(before)))
        ranges.sort()
        for (a, b), (c, d) in zip(ranges, ranges[1:]):
            self.assertLessEqual(b, c)

    def test_control_flow(self):
        swim = live.FEATURES["swim_live"]
        (site, _, call), (first, _, stage1), (second, _, stage2) = swim
        self.assertEqual(follow(site, call)["branch"], first)
        self.assertEqual(call[5:], bytes.fromhex("0f1f00"))
        self.assertEqual(stage1[:8], bytes.fromhex("f30f108b78030000"))   # original load moved into the routine
        self.assertEqual(follow(first, stage1)["branch"], second)
        self.assertEqual(follow(second, stage2)["slot"], live.SWIM_SLOT_RVA)
        self.assertEqual(stage2[-1], 0xC3)
        backpack = {rva: after for rva, _, after in live.FEATURES["backpack_live"]}
        for site in (0x1C5CBDE, 0x1C5CAB4):                                 # both threshold readers share one routine
            self.assertEqual(follow(site, backpack[site])["branch"], 0x1C5C2E1)
        self.assertEqual(follow(0x1C5C2E1, backpack[0x1C5C2E1])["branch"], 0x1C5F5B1)
        self.assertEqual(follow(0x1C5F5B1, backpack[0x1C5F5B1])["slot"], live.BACKPACK_SLOT_RVA)
        for site, first, second, tail in ((0x1AA2E33, 0x1AA7553, 0x1AA87E1, "f30f584338c3"), (0x1A9EC04, 0x1A9CF52, 0x1A96FE1, "f30f584638c3")):
            self.assertEqual(follow(site, backpack[site])["branch"], first)
            self.assertEqual(follow(first, backpack[first]), {"branch": second, "slot": live.BACKPACK_SLOT_RVA})
            self.assertTrue(backpack[second].endswith(bytes.fromhex(tail)))  # the replaced addss is kept

    def test_slots_are_separate_unused_rw_slack(self):
        slots = [w.PENDING_RVA, sushi_speed.SLOT_RVA, live.SWIM_SLOT_RVA, live.BACKPACK_SLOT_RVA]
        self.assertEqual(len(set(slots)), 4)
        for slot in slots:
            self.assertTrue(w.DATA_END_RVA <= slot and slot + 4 <= w.NEXT_SECTION_RVA and slot % 4 == 0)

    def test_slot_values(self):
        self.assertEqual(live.slot_value(1), bytes(4))
        self.assertEqual(struct.unpack("<f", live.slot_value(3.5))[0], 2.5)
        self.assertEqual(struct.unpack("<f", live.slot_value(live.UNLIMITED, True))[0], live.UNLIMITED_FACTOR - 1)
        for value in (0, 0.09, 20.5, float("nan"), float("inf"), "x", None, live.UNLIMITED):
            with self.assertRaises(ValueError):
                live.slot_value(value)

    def test_apply_normalize_and_partial_install(self):
        size = max(rva for regions in live.FEATURES.values() for rva, _, _ in regions) + 64
        data = bytearray(size)
        for regions in live.FEATURES.values():
            for rva, before, _ in regions:
                data[rva - live.IL2CPP_DELTA:rva - live.IL2CPP_DELTA + len(before)] = before
        original = bytes(data)
        for feature in live.FEATURES:
            live.apply(data, feature, True)
            with self.assertRaises(ValueError):
                live.apply(data, feature, True)   # never stacks
        for feature in live.FEATURES:
            self.assertTrue(live.normalize(data, feature))
        self.assertEqual(bytes(data), original)
        rva, before, after = live.FEATURES["backpack_live"][0]
        data[rva - live.IL2CPP_DELTA:rva - live.IL2CPP_DELTA + len(after)] = after   # only one region installed
        with self.assertRaises(ValueError):
            live.normalize(data, "backpack_live")

    def kernel(self, feature, installed=True):
        rva, before, after = live.SLOT_READERS[feature]
        api = SimulatedKernel("C:/Games/Dave")
        api.regions = {BASE + rva: bytearray(after if installed else before),
                       BASE + live.SWIM_SLOT_RVA: bytearray(4), BASE + live.BACKPACK_SLOT_RVA: bytearray(4)}
        return api

    def test_simulated_live_writes(self):
        api = self.kernel("swim_live")
        with patch.object(w.ctypes, "WinDLL", return_value=api):
            self.assertEqual(live.set_swim(api.game, 3), 3.0)
        self.assertEqual(api.writes, [(BASE + live.SWIM_SLOT_RVA, 4)])
        self.assertEqual(struct.unpack("<f", api.regions[BASE + live.SWIM_SLOT_RVA])[0], 2.0)
        api = self.kernel("backpack_live")
        with patch.object(w.ctypes, "WinDLL", return_value=api):
            self.assertEqual(live.set_backpack(api.game, live.UNLIMITED), live.UNLIMITED)
        self.assertEqual(api.writes, [(BASE + live.BACKPACK_SLOT_RVA, 4)])
        self.assertEqual(struct.unpack("<f", api.regions[BASE + live.BACKPACK_SLOT_RVA])[0], live.UNLIMITED_FACTOR - 1)

    def test_simulated_uninstalled_blocks_writes(self):
        for feature, setter in (("swim_live", live.set_swim), ("backpack_live", live.set_backpack)):
            api = self.kernel(feature, installed=False)
            with patch.object(w.ctypes, "WinDLL", return_value=api):
                with self.assertRaises(ValueError):
                    setter(api.game, 2)
            self.assertEqual(api.writes, [])

    def test_invalid_value_before_process_access(self):
        with patch.object(w.ctypes, "WinDLL") as api:
            for setter in (live.set_swim, live.set_backpack):
                with self.assertRaises(ValueError):
                    setter("unused", 50)
            api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
