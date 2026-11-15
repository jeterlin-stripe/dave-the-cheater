import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

import weapon_icons as icons


def decode_png(data):
    """Tiny PNG reader for the encoder's own output (RGBA8, filter 0)."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, chunks = 8, {}
    while pos < len(data):
        length, kind = struct.unpack_from(">I4s", data, pos)
        payload = data[pos + 8:pos + 8 + length]
        crc = struct.unpack_from(">I", data, pos + 8 + length)[0]
        assert crc == zlib.crc32(kind + payload)
        chunks[kind] = chunks.get(kind, b"") + payload
        pos += 12 + length
    width, height, depth, colour = struct.unpack_from(">IIBB", chunks[b"IHDR"])
    raw = zlib.decompress(chunks[b"IDAT"])
    stride = width * 4 + 1
    return width, height, depth, colour, [raw[r * stride + 1:(r + 1) * stride] for r in range(height)]


class WeaponIconTests(unittest.TestCase):
    def test_png_round_trip(self):
        rows = [bytes(range(r * 8, r * 8 + 8)) for r in range(3)]  # 2 px wide, 3 rows
        width, height, depth, colour, decoded = decode_png(icons.png_bytes(2, 3, rows))
        self.assertEqual((width, height, depth, colour), (2, 3, 8, 6))
        self.assertEqual(decoded, rows)

    def test_png_loads_in_tk(self):
        import tkinter as tk
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        try:
            image = tk.PhotoImage(data=icons.png_bytes(2, 1, [bytes([255, 0, 0, 255, 0, 0, 255, 128])]))
            self.assertEqual((image.width(), image.height()), (2, 1))
            self.assertEqual(image.get(0, 0), (255, 0, 0))
        finally:
            root.destroy()

    def test_cache_reuse_and_invalidation(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            bundle = folder / "atlas.bundle"
            bundle.write_bytes(b"v1")
            png = icons.png_bytes(1, 1, [b"\0\0\0\0"])
            with patch.object(icons, "atlas_bundle", return_value=bundle), \
                    patch.object(icons, "crop_icons", return_value={"Item_A": png, "../evil": png}) as crop:
                paths = icons.extract_icons("game", ["Item_A", ""], folder / "cache")
                self.assertEqual(set(paths), {"Item_A"})  # unsafe sprite names never become paths
                self.assertEqual(paths["Item_A"].read_bytes(), png)
                icons.extract_icons("game", ["Item_A"], folder / "cache")
                self.assertEqual(crop.call_count, 1)  # served from cache
                icons.extract_icons("game", ["Item_A", "Item_B"], folder / "cache")
                self.assertEqual(crop.call_count, 2)  # request changed
                bundle.write_bytes(b"v2 longer")
                icons.extract_icons("game", ["Item_A", "Item_B"], folder / "cache")
                self.assertEqual(crop.call_count, 3)  # game update
                paths["Item_A"].unlink()
                icons.extract_icons("game", ["Item_A", "Item_B"], folder / "cache")
                self.assertEqual(crop.call_count, 4)  # missing file


if __name__ == "__main__":
    unittest.main()
