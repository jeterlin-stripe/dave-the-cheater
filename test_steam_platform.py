"""Linux/Steam Deck plumbing tested on any OS with a fake /proc and simulated process memory."""
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import live_multipliers as live
import steam_platform as sp

BASE = 0x6FFFF0000000


def pe_header(image_base=0x180000000):
    header = bytearray(0x400)
    header[:2] = b"MZ"
    struct.pack_into("<I", header, 60, 0x80)
    header[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<Q", header, 0x80 + 24 + 24, image_base)
    header[0x200:0x208] = b"il2cpp\0\0"
    return bytes(header)


class FakeMemory:
    """Sparse process memory addressed like /proc/<pid>/mem."""

    def __init__(self, regions, writable=True):
        self.regions, self.writable, self.position, self.writes = regions, writable, 0, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def seek(self, address):
        self.position = address

    def _region(self, count):
        for start, data in self.regions.items():
            if start <= self.position and self.position + count <= start + len(data):
                return start, data
        raise OSError(5, "Input/output error")

    def read(self, count):
        start, data = self._region(count)
        return bytes(data[self.position - start:self.position - start + count])

    def write(self, payload):
        if not self.writable:
            raise PermissionError(13, "Permission denied")
        start, data = self._region(len(payload))
        data[self.position - start:self.position - start + len(payload)] = payload
        self.writes.append((self.position, len(payload)))
        return len(payload)


class SteamPlatformTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = self.root / "sdcard"
        self.game = self.library / "steamapps/common/Dave the Diver"
        self.game.mkdir(parents=True)
        (self.game / "GameAssembly.dll").write_bytes(pe_header())
        self.proc = self.root / "proc"
        self.proc.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def add_process(self, pid, argv0, maps=""):
        folder = self.proc / str(pid)
        folder.mkdir(parents=True)
        (folder / "cmdline").write_bytes(argv0.encode() + b"\0--arg\0")
        (folder / "maps").write_text(maps, "utf8")

    def maps_line(self, start, path, offset=0):
        return f"{start:x}-{start + 0x1000:x} r--p {offset:08x} 103:02 1234 {path}\n"

    def test_library_folders_and_find_game(self):
        steam = self.root / "Steam"
        (steam / "steamapps").mkdir(parents=True)
        escaped = str(self.library).replace("\\", "\\\\")
        (steam / "steamapps/libraryfolders.vdf").write_text(
            f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{str(steam).replace(chr(92), chr(92) * 2)}"\n\t}}\n'
            f'\t"1"\n\t{{\n\t\t"path"\t\t"{escaped}"\n\t\t"apps"\n\t\t{{\n\t\t\t"1868140"\t\t"123"\n\t\t}}\n\t}}\n}}\n', "utf8")
        self.assertEqual(sp.library_folders(steam), [steam, self.library])
        self.assertEqual(sp.find_game([steam]), self.game)
        self.assertEqual(sp.find_game([self.root / "missing"], fallback="x"), "x")

    def test_proton_player_log_is_in_the_games_library(self):
        with patch.object(sp, "IS_WINDOWS", False):
            log = sp.player_log(self.game)
        self.assertEqual(log, self.library.resolve() / "steamapps/compatdata/1868140/pfx/drive_c/users/steamuser"
                         / "AppData/LocalLow/nexon/DAVE THE DIVER/Player.log")

    def test_game_pids_match_the_wine_program_only(self):
        self.add_process(100, "Z:\\home\\deck\\.local\\share\\Steam\\steamapps\\common\\Dave the Diver\\DaveTheDiver.exe")
        self.add_process(101, "C:\\windows\\system32\\steam.exe")
        self.add_process(102, "/usr/bin/python3")  # e.g. a wrapper that only mentions the game later in argv
        (self.proc / "102" / "cmdline").write_bytes(b"/usr/bin/python3\0DaveTheDiver.exe\0")
        (self.proc / "self").mkdir()
        self.assertEqual(sp.game_pids(self.proc), [100])
        self.assertTrue(sp.linux_game_running(self.proc))

    def live_setup(self, maps_path, header=None, site=None, writable=True):
        reader_rva, original, patched = live.SLOT_READERS["swim_live"]
        self.add_process(200, "Z:\\games\\DaveTheDiver.exe", self.maps_line(BASE, maps_path)
                         + self.maps_line(BASE + 0x1000, maps_path, 0x1000) + self.maps_line(0x7000, "/usr/lib/libc.so.6"))
        memory = FakeMemory({BASE: bytearray(header or pe_header()),
                             BASE + reader_rva: bytearray(site if site is not None else patched),
                             BASE + live.SWIM_SLOT_RVA: bytearray(4)}, writable)
        return memory

    def write(self, memory):
        reader_rva, _, _ = live.SLOT_READERS["swim_live"]
        check = live._reader_check("swim_live")[2]
        sp.linux_live_write(self.game, reader_rva, 15, check, live.SWIM_SLOT_RVA, live.slot_value(2),
                            "not installed", proc=self.proc, open_mem=lambda: memory)

    def test_live_write_by_mapped_path(self):
        memory = self.live_setup(str(self.game / "GameAssembly.dll"))
        self.write(memory)
        self.assertEqual(memory.writes, [(BASE + live.SWIM_SLOT_RVA, 4)])
        self.assertEqual(struct.unpack("<f", memory.regions[BASE + live.SWIM_SLOT_RVA])[0], 1.0)

    def test_container_path_falls_back_to_header_comparison(self):
        memory = self.live_setup("/run/pressure-vessel/games/Dave the Diver/GameAssembly.dll", header=pe_header(0x7FF000000000))
        self.write(memory)  # relocated ImageBase is ignored
        self.assertEqual(len(memory.writes), 1)

    def test_different_game_build_is_rejected(self):
        other = bytearray(pe_header()); other[0x200] ^= 1
        memory = self.live_setup("/elsewhere/GameAssembly.dll", header=bytes(other))
        with self.assertRaises(ValueError):
            self.write(memory)
        self.assertEqual(memory.writes, [])

    def test_unpatched_code_blocks_the_write(self):
        reader_rva, original, _ = live.SLOT_READERS["swim_live"]
        memory = self.live_setup(str(self.game / "GameAssembly.dll"), site=original)
        with self.assertRaises(ValueError):
            self.write(memory)
        self.assertEqual(memory.writes, [])

    def test_ptrace_restriction_explains_the_fix(self):
        memory = self.live_setup(str(self.game / "GameAssembly.dll"), writable=False)
        with self.assertRaises(PermissionError) as caught:
            self.write(memory)
        self.assertIn("ptrace_scope", str(caught.exception))

    def test_no_or_multiple_game_processes(self):
        with self.assertRaises(ValueError):
            self.write(FakeMemory({}))
        self.live_setup(str(self.game / "GameAssembly.dll"))
        self.add_process(201, "Z:\\other\\DaveTheDiver.exe")
        with self.assertRaises(ValueError):
            self.write(FakeMemory({}))


if __name__ == "__main__":
    unittest.main()
