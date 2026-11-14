"""DAVE THE DIVER asset inspector and copy-only builder. Standard library only."""
import argparse
import base64
import hashlib
import json
import lzma
import math
import struct
from pathlib import Path


class Reader:
    def __init__(self, data, endian=">"):
        self.data, self.pos, self.endian = data, 0, endian

    def unpack(self, fmt):
        size = struct.calcsize(self.endian + fmt)
        if self.pos + size > len(self.data):
            raise ValueError("Unexpected end of data")
        result = struct.unpack_from(self.endian + fmt, self.data, self.pos)
        self.pos += size
        return result[0] if len(result) == 1 else result

    def take(self, size):
        if size < 0 or self.pos + size > len(self.data):
            raise ValueError("Invalid data length")
        result = self.data[self.pos:self.pos + size]
        self.pos += size
        return result

    def string(self):
        end = self.data.index(b"\0", self.pos)
        value = self.take(end - self.pos).decode("utf-8", "replace")
        self.pos += 1
        return value

    def align(self, size=16):
        self.pos = (self.pos + size - 1) // size * size


def lz4(data, expected):
    """Decode a raw LZ4 block, including overlapping match copies."""
    r, out = Reader(data), bytearray()
    while r.pos < len(data):
        token = r.unpack("B")
        literal = token >> 4
        if literal == 15:
            while True:
                extra = r.unpack("B")
                literal += extra
                if extra != 255:
                    break
        out.extend(r.take(literal))
        if len(out) > expected:
            raise ValueError("LZ4 output exceeds declared size")
        if r.pos == len(data):
            break
        offset = int.from_bytes(r.take(2), "little")
        if not offset or offset > len(out):
            raise ValueError("Invalid LZ4 match offset")
        length = (token & 15) + 4
        if token & 15 == 15:
            while True:
                extra = r.unpack("B")
                length += extra
                if extra != 255:
                    break
        if len(out) + length > expected:
            raise ValueError("LZ4 match exceeds declared size")
        for _ in range(length):
            out.append(out[-offset])
    if len(out) != expected:
        raise ValueError(f"LZ4 size mismatch: {len(out)} != {expected}")
    return bytes(out)


def decompress(data, kind, expected):
    if kind == 0:
        result = data
    elif kind in (2, 3):
        return lz4(data, expected)
    elif kind == 1:
        props = data[:5]
        result = lzma.decompress(props + expected.to_bytes(8, "little") + data[5:])
    else:
        raise ValueError(f"Unsupported compression: {kind}")
    if len(result) != expected:
        raise ValueError("Decompression size mismatch")
    return result


def bundle_files(path):
    data = path.read_bytes()
    r = Reader(data)
    if r.string() != "UnityFS":
        raise ValueError("Not a UnityFS bundle")
    version = r.unpack("I")
    player, engine = r.string(), r.string()
    size, compressed, plain, flags = r.unpack("QIII")
    if size != len(data):
        raise ValueError("Bundle file size mismatch")
    if version >= 7:
        r.align()
    start = r.pos
    info_pos = len(data) - compressed if flags & 128 else start
    info = Reader(decompress(data[info_pos:info_pos + compressed], flags & 63, plain))
    info.take(16)
    blocks = [info.unpack("IIH") for _ in range(info.unpack("I"))]
    nodes = []
    for _ in range(info.unpack("I")):
        offset, length, node_flags = info.unpack("QQI")
        nodes.append((offset, length, node_flags, info.string()))
    r.pos = start if flags & 128 else start + compressed
    if flags & 512:
        r.align()
    payload = bytearray()
    for raw_size, packed_size, block_flags in blocks:
        payload.extend(decompress(r.take(packed_size), block_flags & 63, raw_size))
    files = []
    for offset, length, node_flags, name in nodes:
        if offset + length > len(payload):
            raise ValueError("Invalid bundle node range")
        files.append((name, bytes(payload[offset:offset + length]), node_flags))
    return {"format": version, "engine": engine, "player": player}, files


def catalog_entries(path, pattern):
    c = json.loads(path.read_text("utf-8-sig"))
    keys = base64.b64decode(c["m_KeyDataString"])
    buckets = Reader(base64.b64decode(c["m_BucketDataString"]), "<")
    entries = base64.b64decode(c["m_EntryDataString"])
    mapping, bucket_entries = {}, []
    for _ in range(buckets.unpack("i")):
        offset, count = buckets.unpack("ii")
        indexes = [buckets.unpack("i") for _ in range(count)]
        bucket_entries.append(indexes)
        kind = keys[offset]
        if kind in (0, 1):
            length = struct.unpack_from("<i", keys, offset + 1)[0]
            value = keys[offset + 5:offset + 5 + length].decode("ascii" if kind == 0 else "utf-16-le", "replace")
            mapping[value] = indexes
    results = []
    for key, indexes in mapping.items():
        for index in indexes:
            internal, provider, dependency, dep_hash, extra, primary, resource_type = struct.unpack_from("<7i", entries, 4 + index * 28)
            if pattern.lower() not in key.lower() and pattern.lower() not in c["m_InternalIds"][internal].lower():
                continue
            deps, visited = [], set()
            def visit(bucket):
                if bucket < 0 or bucket in visited:
                    return
                visited.add(bucket)
                for dep_index in bucket_entries[bucket]:
                    values = struct.unpack_from("<7i", entries, 4 + dep_index * 28)
                    dep_id = c["m_InternalIds"][values[0]]
                    if dep_id not in deps:
                        deps.append(dep_id)
                    visit(values[2])
            visit(dependency)
            results.append({"key": key, "entry": index, "internal_id": c["m_InternalIds"][internal], "dependencies": deps})
    return c, results


def serialized_summary(data):
    r = Reader(data)
    metadata_size, file_size, version, data_offset = r.unpack("4I")
    endian = r.unpack("B")
    r.take(3)
    if version < 22:
        raise ValueError("This inspector currently supports serialized format 22+")
    metadata_size, file_size, data_offset, reserved = r.unpack("IQQQ")
    r.endian = ">" if endian else "<"
    engine, platform, trees = r.string(), r.unpack("i"), r.unpack("B")
    types = []
    for _ in range(r.unpack("i")):
        class_id, stripped, script_index = r.unpack("iBh")
        if class_id == 114:
            r.take(16)
        r.take(16)
        nodes = []
        if trees:
            count, string_size = r.unpack("ii")
            raw_nodes = [r.unpack("HBBIIiiiQ") for _ in range(count)]
            strings = r.take(string_size)
            def resolve(offset):
                if offset & 0x80000000:
                    return f"common:{offset & 0x7fffffff}"
                end = strings.index(b"\0", offset)
                return strings[offset:end].decode("utf8", "replace")
            for v in raw_nodes:
                nodes.append({"level": v[1], "type": resolve(v[3]), "name": resolve(v[4]), "size": v[5], "flags": v[7]})
        for _ in range(r.unpack("i")):
            r.unpack("i")
        types.append({"class_id": class_id, "script_index": script_index, "nodes": nodes})
    objects = []
    for _ in range(r.unpack("i")):
        r.align(4)
        path_id, offset, size, type_index = r.unpack("qQIi")
        raw = data[data_offset + offset:data_offset + offset + size]
        objects.append({"path_id": path_id, "offset": data_offset + offset, "size": size, "type_index": type_index, "hex": raw.hex()})
    for _ in range(r.unpack("i")):
        r.unpack("i")
        r.align(4)
        r.unpack("q")
    externals = []
    for _ in range(r.unpack("i")):
        r.string()
        guid = r.take(16).hex()
        kind = r.unpack("i")
        externals.append({"guid": guid, "kind": kind, "path": r.string()})
    return {"version": version, "engine": engine, "types": types, "objects": objects, "externals": externals}


def movement_report(game):
    aa = game / "DaveTheDiver_Data/StreamingAssets/aa"
    _, matches = catalog_entries(aa / "catalog.json", "Assets/ScriptableObjects/Common/DaveMoveDataData.asset")
    match = next(x for x in matches if x["internal_id"] == "Assets/ScriptableObjects/Common/DaveMoveDataData.asset")
    findings = []
    for dep in match["dependencies"]:
        path = aa / "StandaloneWindows64" / dep.replace("\\", "/").split("/")[-1]
        _, files = bundle_files(path)
        for name, data, _ in files:
            summary = serialized_summary(data)
            for obj in summary["objects"]:
                typ = summary["types"][obj["type_index"]]
                names = [n["name"] for n in typ["nodes"]]
                if typ["class_id"] != 114 or "_speedMultiplier" not in names:
                    continue
                expected = ["_moveType", "_speedMultiplier", "_staminaUse", "staminaInit", "staminaMax", "staminaZeroPenaltyTime", "staminaZeroPenaltyRecover", "moveThreshold"]
                relevant = [n for n in names if n in expected]
                if relevant != expected:
                    raise ValueError("Movement schema differs from supported layout")
                r = Reader(bytes.fromhex(obj["hex"]), "<")
                r.take(12)  # m_GameObject PPtr
                r.take(1)   # m_Enabled
                r.align(4)
                r.take(12)  # m_Script PPtr
                asset_name = r.take(r.unpack("i")).decode("utf8")
                r.align(4)
                if asset_name != "DaveMoveDataData":
                    continue
                count = r.unpack("i")
                if not 0 < count < 100:
                    raise ValueError("Unexpected movement record count")
                records = []
                for _ in range(count):
                    record_offset = r.pos
                    state, speed, stamina = r.unpack("iff")
                    records.append({"move_type_id": state, "speed_multiplier": speed, "stamina_use": stamina, "serialized_speed_offset": obj["offset"] + record_offset + 4})
                stamina_fields = dict(zip(expected[3:], r.unpack("5f")))
                if r.pos != len(r.data):
                    raise ValueError("Unparsed trailing movement data")
                findings.append({"asset": asset_name, "bundle": str(path), "bundle_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "serialized_node": name, "path_id": obj["path_id"], "records": records, "other_fields": stamina_fields})
        if findings:
            break
    if not findings:
        raise ValueError("No supported movement data found")
    labels = movement_enum(game)
    for finding in findings:
        for record in finding["records"]:
            record["state_name"] = labels.get(record["move_type_id"], "Unknown")
    return {"read_only": True, "note": "State names verified against local IL2CPP metadata. Runtime scene use and swimming effects remain unverified.", "findings": findings}


def movement_enum(game):
    data = (game / "DaveTheDiver_Data/il2cpp_data/Metadata/global-metadata.dat").read_bytes()
    h = struct.unpack_from("<64I", data)
    if h[0] != 0xFAB11BAF or h[1] != 31:
        raise ValueError("Unsupported metadata version for movement enum")
    def name(index):
        start = h[6] + index
        return data[start:data.index(b"\0", start)].decode("utf8")
    defaults = {}
    for pos in range(h[16], h[16] + h[17], 12):
        field, typ, offset = struct.unpack_from("<iii", data, pos)
        if offset >= 0:
            defaults[field] = offset
    for pos in range(h[40], h[40] + h[41], 88):
        t = struct.unpack_from("<16i8H2I", data, pos)
        if name(t[0]) != "MoveType":
            continue
        fields = [(i, name(struct.unpack_from("<i", data, h[24] + i * 12)[0])) for i in range(t[8], t[8] + t[18])]
        if [n for _, n in fields] != ["value__", "None", "Tired", "Walk", "Run", "Crawl"]:
            continue
        result = {}
        for index, field_name in fields[1:]:
            # Metadata v31 stores these enum constants as one-byte zigzag integers.
            encoded = data[h[18] + defaults[index]]
            if encoded >= 128:
                raise ValueError("Unexpected enum encoding")
            value = -(encoded // 2) - 1 if encoded & 1 else encoded // 2
            result[value] = field_name
        if result != {-1: "None", 0: "Tired", 1: "Walk", 2: "Run", 3: "Crawl"}:
            raise ValueError("Unexpected movement enum values")
        return result
    raise ValueError("Expected movement enum not found")


def read_object_fields(typ, obj):
    """Decode a type-tree object and retain field byte offsets for analysis."""
    nodes = typ["nodes"]
    r, fields = Reader(bytes.fromhex(obj["hex"]), "<"), []
    def end(index):
        j = index + 1
        while j < len(nodes) and nodes[j]["level"] > nodes[index]["level"]:
            j += 1
        return j
    def read(index, path):
        n = nodes[index]
        stop = end(index)
        start = r.pos
        children = []
        j = index + 1
        while j < stop:
            children.append(j)
            j = end(j)
        if n["type"] == "common:840":
            value = r.take(r.unpack("i")).decode("utf8", "replace")
            r.align(4)
        elif n["type"] == "common:49":  # Array
            count = r.unpack("i")
            if not 0 <= count <= 1000000 or len(children) != 2:
                raise ValueError("Unsupported array layout")
            value = [read(children[1], f"{path}[{k}]") for k in range(count)]
        elif children:
            value = {nodes[j]["name"]: read(j, path + "/" + nodes[j]["name"]) for j in children}
        elif n["size"] >= 0:
            raw = r.take(n["size"])
            if n["type"] == "common:161" and len(raw) == 4:
                value = struct.unpack("<f", raw)[0]
            elif len(raw) in (1, 2, 4, 8):
                value = int.from_bytes(raw, "little", signed=True)
            else:
                value = raw.hex()
        else:
            raise ValueError(f"Unsupported variable leaf {n}")
        if n["flags"] & 16384:
            r.align(4)
        fields.append({"path": path, "offset": obj["offset"] + start, "value": value})
        return value
    read(0, "root")
    if r.pos != len(r.data):
        raise ValueError(f"Object parse mismatch {r.pos} != {len(r.data)}")
    return fields


def write_bundle(info, files):
    """Build a UnityFS bundle with uncompressed data and block info."""
    payload, nodes = bytearray(), []
    for name, data, flags in files:
        nodes.append((len(payload), len(data), flags, name))
        payload.extend(data)
    block_info = bytearray(hashlib.md5(payload).digest())
    block_info.extend(struct.pack(">IIIH", 1, len(payload), len(payload), 0))
    block_info.extend(struct.pack(">I", len(nodes)))
    for offset, length, flags, name in nodes:
        block_info.extend(struct.pack(">QQI", offset, length, flags))
        block_info.extend(name.encode("utf8") + b"\0")
    header = bytearray(b"UnityFS\0" + struct.pack(">I", info["format"]))
    header.extend(info["player"].encode() + b"\0" + info["engine"].encode() + b"\0")
    size_pos = len(header)
    header.extend(struct.pack(">QIII", 0, len(block_info), len(block_info), 64))
    if info["format"] >= 7:
        header.extend(b"\0" * (-len(header) % 16))
    struct.pack_into(">Q", header, size_pos, len(header) + len(block_info) + len(payload))
    return bytes(header + block_info + payload)


def build_copy(game, destination, factor):
    if not math.isfinite(factor) or not 1 < factor <= 3:
        raise ValueError("Factor must be greater than 1 and at most 3")
    game_resolved, dest_resolved = game.resolve(), destination.resolve()
    if dest_resolved == game_resolved or game_resolved in dest_resolved.parents:
        raise ValueError("Output must be outside the game directory")
    report = movement_report(game)
    finding = report["findings"][0]
    source = Path(finding["bundle"])
    original = source.read_bytes()
    info, files = bundle_files(source)
    modified, changes = [], []
    for name, data, flags in files:
        patch = bytearray(data)
        if name == finding["serialized_node"]:
            allowed = set()
            for record in finding["records"]:
                offset = record["serialized_speed_offset"]
                old = struct.unpack_from("<f", data, offset)[0]
                if old != record["speed_multiplier"]:
                    raise ValueError("Original value no longer matches report")
                struct.pack_into("<f", patch, offset, old * factor)
                new = struct.unpack_from("<f", patch, offset)[0]
                changes.append({"state": record["state_name"], "before": old, "after": new, "offset": offset})
                allowed.update(range(offset, offset + 4))
            differences = {i for i, (a, b) in enumerate(zip(data, patch)) if a != b}
            if not differences or not differences <= allowed:
                raise ValueError("Unexpected byte differences")
        modified.append((name, bytes(patch), flags))
    if len(changes) != 4:
        raise ValueError("Expected exactly four movement changes")
    rebuilt = write_bundle(info, modified)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "original").mkdir()
    (destination / "modified").mkdir()
    (destination / "original" / source.name).write_bytes(original)
    output = destination / "modified" / source.name
    output.write_bytes(rebuilt)
    check_info, check_files = bundle_files(output)
    if check_info != info or check_files != modified:
        raise ValueError("Rebuilt bundle failed round-trip verification")
    if source.read_bytes() != original:
        raise ValueError("Source changed during processing")
    result = {"installed": False, "runtime_tested": False, "factor": factor, "source": str(source), "original_sha256": hashlib.sha256(original).hexdigest(), "modified_sha256": hashlib.sha256(rebuilt).hexdigest(), "changes": changes, "verification": "Rebuilt bundle re-read successfully; decoded nodes match expected data; changes limited to four speed floats; original untouched.", "limitations": "Game loading, catalog CRC validation, scene use, and swimming effects require further verification."}
    (destination / "build-report.json").write_text(json.dumps(result, indent=2), encoding="utf8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, default=Path(r"G:\SteamLibrary\steamapps\common\Dave the Diver"))
    parser.add_argument("--find", default="DaveMoveData")
    parser.add_argument("--bundle", type=Path, help="Read and list one UnityFS bundle")
    parser.add_argument("--extract", type=Path, help="Extract bundle nodes into a NEW directory")
    parser.add_argument("--serialized", type=Path, help="Inspect a format-22 serialized asset file")
    parser.add_argument("--movement", action="store_true", help="Locate and read Dave movement multipliers without changing files")
    parser.add_argument("--build-copy", type=Path, help="Create original/modified bundles in a NEW directory outside the game")
    parser.add_argument("--factor", type=float, default=1.5)
    args = parser.parse_args()
    if args.build_copy:
        print(json.dumps(build_copy(args.game, args.build_copy, args.factor), indent=2))
    elif args.movement:
        print(json.dumps(movement_report(args.game), indent=2))
    elif args.serialized:
        print(json.dumps(serialized_summary(args.serialized.read_bytes()), indent=2))
    elif args.bundle:
        info, files = bundle_files(args.bundle)
        info["files"] = [{"name": n, "bytes": len(b), "flags": f, "sha256": hashlib.sha256(b).hexdigest()} for n, b, f in files]
        if args.extract:
            args.extract.mkdir(parents=True, exist_ok=False)
            for i, (name, data, _) in enumerate(files):
                # Never trust internal bundle paths.
                (args.extract / f"{i:03d}_{Path(name).name}").write_bytes(data)
        print(json.dumps(info, indent=2))
    else:
        _, results = catalog_entries(args.game / "DaveTheDiver_Data/StreamingAssets/aa/catalog.json", args.find)
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
