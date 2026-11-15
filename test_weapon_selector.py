import struct
import ctypes
from pathlib import Path
import unittest
from unittest.mock import patch, Mock

import weapon_selector as w

BASE = 0x180000000


class SimulatedKernel:
    """Windows API simulation: no process access or live writes."""
    def __init__(self, game, wrong_path=False, fail_first_write=False, site=None):
        self.game = Path(game).resolve()
        # Sparse memory: the patched code site and the pending-weapon slot.
        self.regions = {BASE + w.SWITCH_RVA: bytearray(w.adapter() if site is None else site),
                        BASE + w.PENDING_RVA: bytearray(4)}
        self.writes = []
        self.fail_first_write = fail_first_write
        self.CreateToolhelp32Snapshot = Mock(side_effect=lambda flags, pid: 100 if flags == 2 else 200)
        self.Process32FirstW = Mock(side_effect=self.first_process)
        self.Process32NextW = Mock(side_effect=self.end_processes)
        self.Module32FirstW = Mock(side_effect=self.first_module)
        self.Module32NextW = Mock(return_value=False)
        self.OpenProcess = Mock(return_value=300)
        self.QueryFullProcessImageNameW = Mock(side_effect=lambda handle, flags, buffer, size: self.image_path(buffer, wrong_path))
        self.ReadProcessMemory = Mock(side_effect=self.read)
        self.WriteProcessMemory = Mock(side_effect=self.write)
        self.CloseHandle = Mock(return_value=True)

    def locate(self, address, count):
        for start, data in self.regions.items():
            if start <= address and address + count <= start + len(data):
                return data, address - start
        raise AssertionError(f"access outside simulated regions: {address:#x}")

    def first_process(self, handle, pointer):
        pointer._obj.name = "DaveTheDiver.exe"
        pointer._obj.pid = 123
        return True

    def end_processes(self, *_):
        ctypes.set_last_error(18)
        return False

    def first_module(self, handle, pointer):
        pointer._obj.name = "GameAssembly.dll"
        pointer._obj.path = str(self.game / "GameAssembly.dll")
        pointer._obj.base = BASE
        return True

    def image_path(self, buffer, wrong):
        buffer.value = str(self.game / ("Other.exe" if wrong else "DaveTheDiver.exe"))
        return True

    def read(self, handle, address, buffer, count, actual):
        data, offset = self.locate(address, count)
        ctypes.memmove(buffer, bytes(data[offset:offset + count]), count)
        actual._obj.value = count
        return True

    def write(self, handle, address, buffer, count, actual):
        self.writes.append((address, count))
        if self.fail_first_write:
            self.fail_first_write = False
            ctypes.set_last_error(5)
            return False
        data, offset = self.locate(address, count)
        data[offset:offset + count] = ctypes.string_at(buffer, count)
        actual._obj.value = count
        return True

    @property
    def pending(self):
        return struct.unpack("<i", self.regions[BASE + w.PENDING_RVA])[0]


def disp_target(code, at, end):
    """RVA targeted by the rel32 stored at adapter offset `at` for an instruction ending at `end`."""
    return w.SWITCH_RVA + end + struct.unpack_from("<i", code, at)[0]


class AdapterTests(unittest.TestCase):
    ORIGINAL = w.ORIGINAL_HEAD + bytes(w.SWITCH_LENGTH - len(w.ORIGINAL_HEAD))

    def test_original_and_adapter_decode(self):
        self.assertFalse(w.decode_region(self.ORIGINAL, self.ORIGINAL))
        self.assertFalse(w.decode_region(self.ORIGINAL))
        self.assertTrue(w.decode_region(w.adapter(), self.ORIGINAL))
        self.assertTrue(w.decode_region(w.adapter()))
        self.assertEqual(len(w.adapter()), w.SWITCH_LENGTH)

    def test_v2_adapter_is_migrated_from_file_but_rejected_live(self):
        old = w.v2_adapter(3010081)
        self.assertTrue(w.decode_region(old, self.ORIGINAL))
        with self.assertRaises(ValueError):
            w.decode_region(old)

    def test_control_flow(self):
        code = w.adapter()
        self.assertEqual(w.SWITCH_END_RVA - w.SWITCH_RVA, 176)
        # mov edx,[rip+PENDING]; test edx,edx; je swap
        self.assertEqual(code[0:2], bytes.fromhex("8b15"))
        self.assertEqual(disp_target(code, 2, 6), w.PENDING_RVA)
        self.assertEqual(code[6:9], bytes.fromhex("85d274"))
        self.assertEqual(10 + code[9], 45)
        # mov rcx,[rdi+0x2a0]; test rcx,rcx; je swap
        self.assertEqual(code[10:20], bytes.fromhex("488b8fa00200004885c9"))
        self.assertEqual(code[20], 0x74)
        self.assertEqual(22 + code[21], 45)
        # mov dword [rip+PENDING],0  (rip-relative with imm32: rip is after the imm)
        self.assertEqual(code[22:24], bytes.fromhex("c705"))
        self.assertEqual(disp_target(code, 24, 32), w.PENDING_RVA)
        self.assertEqual(code[28:32], bytes(4))
        # xor r8d,r8d; call DirectEquip; jmp end
        self.assertEqual(code[32:35], bytes.fromhex("4533c0"))
        self.assertEqual(code[35], 0xe8)
        self.assertEqual(disp_target(code, 36, 40), w.DIRECT_EQUIP_RVA)
        self.assertEqual(code[40], 0xe9)
        self.assertEqual(disp_target(code, 41, 45), w.SWITCH_END_RVA)
        # swap: mov rcx,rdi; xor edx,edx; call OnSwitchWeapon_Performed; jmp end
        self.assertEqual(code[45:51], bytes.fromhex("488bcf33d2e8"))
        self.assertEqual(disp_target(code, 51, 55), w.SWAP_RVA)
        self.assertEqual(code[55], 0xe9)
        self.assertEqual(disp_target(code, 56, 60), w.SWITCH_END_RVA)
        self.assertEqual(set(code[60:]), {0xcc})

    def test_pending_slot_is_unused_rw_slack(self):
        self.assertLessEqual(w.DATA_END_RVA, w.PENDING_RVA)
        self.assertLessEqual(w.PENDING_RVA + 4, w.NEXT_SECTION_RVA)
        self.assertEqual(w.PENDING_RVA % 4, 0)
        # Same 4 KiB page as the end of .data, so it is mapped with .data's RW protection.
        self.assertEqual((w.DATA_END_RVA - 1) // 0x1000, w.PENDING_RVA // 0x1000)

    def test_reject_unknown_code_and_bad_ids(self):
        for value in [0, -1, 2**31, True, 1.5, "3010001"]:
            with self.assertRaises(ValueError):
                w.v2_adapter(value)
        changed = bytearray(w.adapter()); changed[11] ^= 1
        with self.assertRaises(ValueError):
            w.decode_region(bytes(changed), self.ORIGINAL)

    def test_equip_events_ignore_dive_startup(self):
        import os
        import tempfile
        startup = ("Load Request\nGunWeaponHandler:EquipItem(SpecDataBase, Boolean)\n"
                   "InstanceItemInventory:EquipItem(Int32, Boolean)\n"
                   "InstanceItemInventory:EquipSavedSlotData()\n\n")
        live = ("Load Request\nGunWeaponHandler:EquipItem(SpecDataBase, Boolean)\n"
                "InstanceItemInventory:EquipItem(Int32, Boolean)\n"
                "PlayerCharacter:OnDirectHandler(CallbackContext)\n\n")
        with tempfile.TemporaryDirectory() as folder:
            log = os.path.join(folder, "Player.log")
            Path(log).write_text(startup, encoding="utf8")
            since = w.log_position(log)
            self.assertEqual(w.equip_events(since, log), [])
            with open(log, "a", encoding="utf8") as stream:
                stream.write(startup + live)
            self.assertEqual(w.equip_events(since, log), ["GunWeaponHandler"])
            self.assertEqual(w.equip_events(0, log), ["GunWeaponHandler"])

    def test_reject_unlisted_id_before_any_process_access(self):
        with patch.object(w.ctypes, "WinDLL") as api:
            with self.assertRaises(ValueError):
                w.arm_live("unused", 999, {w.DEFAULT_ITEM})
            api.assert_not_called()

    def test_simulated_live_queue_writes_only_pending_slot(self):
        api = SimulatedKernel("C:/Games/Dave")
        with patch.object(w.ctypes, "WinDLL", return_value=api):
            self.assertEqual(w.arm_live(api.game, 3010002, {3010002}), 3010002)
        self.assertEqual(api.writes, [(BASE + w.PENDING_RVA, 4)])
        self.assertEqual(api.pending, 3010002)
        self.assertEqual(bytes(api.regions[BASE + w.SWITCH_RVA]), w.adapter())
        self.assertEqual(api.CloseHandle.call_count, 3)

    def test_simulated_unpatched_or_old_game_blocks_writes(self):
        for site in (self.ORIGINAL, w.v2_adapter(3010001)):
            api = SimulatedKernel("C:/Games/Dave", site=site)
            with patch.object(w.ctypes, "WinDLL", return_value=api):
                with self.assertRaises(ValueError):
                    w.arm_live(api.game, 3010002, {3010002})
            self.assertEqual(api.writes, [])

    def test_simulated_wrong_process_path_blocks_all_writes(self):
        api = SimulatedKernel("C:/Games/Dave", wrong_path=True)
        with patch.object(w.ctypes, "WinDLL", return_value=api):
            with self.assertRaises(ValueError):
                w.arm_live(api.game, 3010002, {3010002})
        self.assertEqual(api.writes, [])

    def test_simulated_write_failure_raises_and_leaves_slot_clear(self):
        api = SimulatedKernel("C:/Games/Dave", fail_first_write=True)
        with patch.object(w.ctypes, "WinDLL", return_value=api):
            with self.assertRaises(OSError):
                w.arm_live(api.game, 3010002, {3010002})
        self.assertEqual(api.pending, 0)


if __name__ == "__main__":
    unittest.main()
