"""Weapon icons for the GUI, cropped from the user's own local InGameAtlas_Point sprite atlas.

Equipment rows name their icon sprite in `ItemIcon` (e.g. `Item_BasicRifle`).
Those sprites are packed into the `InGameAtlas_Point` SpriteAtlas, whose
texture is uncompressed RGBA32 stored bottom-up in the bundle's .resS node.
Each requested sprite is cropped into a PNG in a local, git-ignored cache
directory. Nothing is distributed and no game file is modified.
"""
import json
import struct
import zlib
from pathlib import Path

from inspect_dave import bundle_files, catalog_entries, read_object_fields, serialized_summary

ATLAS = "InGameAtlas_Point.spriteatlas"
SPRITE, TEXTURE, SPRITE_ATLAS = 213, 28, 687078895
RGBA32 = 4


def png_bytes(width, height, rows):
    """Minimal RGBA PNG encoder (top-down rows of width*4 bytes)."""
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
    raw = b"".join(b"\0" + row for row in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def atlas_bundle(game):
    aa = Path(game) / "DaveTheDiver_Data/StreamingAssets/aa"
    _, matches = catalog_entries(aa / "catalog.json", ATLAS)
    entry = next(x for x in matches if x["internal_id"].endswith("/" + ATLAS))
    name = entry["dependencies"][0].replace("\\", "/").split("/")[-1]
    return aa / "StandaloneWindows64" / name


def crop_icons(bundle, wanted):
    """{sprite name: PNG bytes} for the wanted sprite names found in the atlas bundle."""
    wanted = {name for name in wanted if name}
    _, nodes = bundle_files(bundle)
    files = {name: data for name, data, flags in nodes}
    serialized = next(data for name, data, flags in nodes if flags & 4)
    summary = serialized_summary(serialized)
    sprites, entries, textures = {}, [], {}
    for obj in summary["objects"]:
        typ = summary["types"][obj["type_index"]]
        kind = typ["class_id"]
        if kind == SPRITE:
            raw = bytes.fromhex(obj["hex"])
            if not any(name.encode() in raw for name in wanted):
                continue
            root = read_object_fields(typ, obj)[-1]["value"]
            if root.get("common:427") in wanted:
                sprites[root["common:427"]] = root["m_RenderDataKey"]
        elif kind == SPRITE_ATLAS:
            entries = read_object_fields(typ, obj)[-1]["value"]["m_RenderDataMap"]["common:49"]
        elif kind == TEXTURE:
            textures[obj["path_id"]] = read_object_fields(typ, obj)[-1]["value"]
    icons = {}
    for name, key in sprites.items():
        data = next((e["common:778"] for e in entries if e["common:155"] == key), None)
        if data is None or data["texture"]["m_FileID"] != 0:
            continue
        texture = textures.get(data["texture"]["m_PathID"])
        # Only unrotated, tightly packed sprites in an uncompressed RGBA32 texture are supported.
        if texture is None or texture["m_TextureFormat"] != RGBA32 or (data["settingsRaw"] >> 2) & 0xF:
            continue
        width, height = texture["m_Width"], texture["m_Height"]
        stream = texture["m_StreamData"]
        if stream["common:795"]:
            pixels = files[stream["path"].split("/")[-1]][stream["offset"]:stream["offset"] + stream["common:795"]]
        else:
            pixels = texture["image data"]
        if len(pixels) < width * height * 4:
            continue
        rect = data["textureRect"]
        x, y = int(round(rect["x"])), int(round(rect["y"]))
        w, h = int(round(rect["width"])), int(round(rect["height"]))
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > width or y + h > height:
            continue
        # Unity stores rows bottom-up; PNG rows are top-down.
        rows = [pixels[((y + h - 1 - r) * width + x) * 4:((y + h - 1 - r) * width + x + w) * 4] for r in range(h)]
        icons[name] = png_bytes(w, h, rows)
    return icons


def extract_icons(game, wanted, cache_dir):
    """Return {sprite name: PNG path}, cropping only when the atlas bundle or the request changed."""
    cache_dir = Path(cache_dir)
    bundle = atlas_bundle(game)
    stat = bundle.stat()
    key = {"bundle": str(bundle.resolve()), "size": stat.st_size, "mtime": stat.st_mtime_ns,
           "wanted": sorted({name for name in wanted if name})}
    stamp = cache_dir / "stamp.json"
    try:
        stored = json.loads(stamp.read_text("utf8"))
        if stored.get("key") == key:
            paths = {name: cache_dir / f"{name}.png" for name in stored.get("icons", [])}
            if all(path.is_file() for path in paths.values()):
                return paths
    except (OSError, ValueError, AttributeError):
        pass
    icons = crop_icons(bundle, key["wanted"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, data in icons.items():
        if not all(ch.isalnum() or ch in "_-" for ch in name):
            continue  # sprite names become file names
        path = cache_dir / f"{name}.png"
        path.write_bytes(data)
        paths[name] = path
    stamp.write_text(json.dumps({"key": key, "icons": sorted(paths)}), "utf8")
    return paths
