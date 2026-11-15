"""Experimental, build-specific weapon-switch adapter and local weapon catalogue.

The adapter is installed on disk while closed. During play the GUI writes only
a four-byte "pending weapon" ID into unused read/write memory; the next press
of the weapon-switch key equips it once and clears it, and every other press
performs the game's normal harpoon/gun swap. No remote thread, injected DLL,
code write or arbitrary-address UI is used at runtime.
"""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import re
import struct

from inspect_dave import bundle_files, catalog_entries, read_object_fields, serialized_summary

# The Tab (SwitchWeapon, input action 0xe) handler that actually runs is an
# INLINED copy of PlayerCharacter.OnSwitchWeapon_Performed inside
# PlayerCharacter.OnDirectHandler. The standalone OnSwitchWeapon_Performed
# (RVA 0x7CE530) has no callers, but is instruction-for-instruction the same
# swap logic, so the adapter calls it for the normal swap. The inlined block
# spans RVA 0x7C864C..0x7C86FC; it is entered only from `je` at 0x7C8646 (skip
# edge targets 0x7C86FC), rdi = PlayerCharacter, rsi = input context, and code
# after the block reloads every register it uses.
SWITCH_OFFSET = 8156236          # file offset of RVA 0x7C864C
SWITCH_RVA = 0x7C864C
SWITCH_END_RVA = 0x7C86FC        # first instruction after the inlined block
SWITCH_LENGTH = SWITCH_END_RVA - SWITCH_RVA  # 176
ORIGINAL_HEAD = bytes.fromhex("803d7e3e4a0700751f488d0d7cf40507")
DIRECT_EQUIP_RVA = 25998240
SWAP_RVA = 0x7CE530              # standalone OnSwitchWeapon_Performed (original bytes)
# .data ends at RVA 0x7F415A0 (VirtualSize) but its last page is mapped RW up
# to .pdata at 0x7F42000. Nothing in the image uses that slack; it is zero at load.
DATA_END_RVA = 0x7F415A0
NEXT_SECTION_RVA = 0x7F42000
PENDING_RVA = 0x7F41FF0
DEFAULT_ITEM = 3010001

# Earlier attempts, recognised only so existing installs can be read and
# migrated; never written. v1 patched the uncalled standalone method; v2 patched
# the right site but replaced the swap entirely (Tab always re-equipped).
LEGACY_OFFSET = 8180528
LEGACY_RVA = 8185136
LEGACY_ORIGINAL = bytes.fromhex("48895c2408574883ec20803d90df490700488bf9751f488d0d8b950507")


def _check_id(item_id):
    if isinstance(item_id, bool) or not isinstance(item_id, int) or not 1 <= item_id < 2**31:
        raise ValueError("Invalid weapon ID")


def _rel(target, end):
    """rel32 from the instruction ending at adapter offset `end` to RVA `target`."""
    return struct.pack("<i", target - (SWITCH_RVA + end))


def adapter():
    # 0  mov edx,[rip+PENDING]     queued weapon ID (0 = none)
    # 6  test edx,edx / je 45      nothing queued => normal swap
    # 10 mov rcx,[rdi+0x2a0]       PlayerCharacter.m_InstanceItemInven
    # 17 test rcx,rcx / je 45      no inventory => normal swap, keep queue
    # 22 mov dword [rip+PENDING],0 consume the queue (one equip per queue)
    # 32 xor r8d,r8d               MethodInfo* = null
    # 35 call DirectEquip          normal call: we are mid-function
    # 40 jmp SWITCH_END
    # 45 mov rcx,rdi / xor edx,edx
    # 50 call OnSwitchWeapon_Performed   the game's own harpoon/gun swap
    # 55 jmp SWITCH_END
    # 60 int3 padding (unreachable)
    code = (bytes.fromhex("8b15") + _rel(PENDING_RVA, 6)
            + bytes.fromhex("85d27423")
            + bytes.fromhex("488b8fa00200004885c97417")
            + bytes.fromhex("c705") + _rel(PENDING_RVA, 32) + bytes(4)
            + bytes.fromhex("4533c0e8") + _rel(DIRECT_EQUIP_RVA, 40)
            + b"\xe9" + _rel(SWITCH_END_RVA, 45)
            + bytes.fromhex("488bcf33d2e8") + _rel(SWAP_RVA, 55)
            + b"\xe9" + _rel(SWITCH_END_RVA, 60))
    assert len(code) == 60
    assert DATA_END_RVA <= PENDING_RVA and PENDING_RVA + 4 <= NEXT_SECTION_RVA and PENDING_RVA % 4 == 0
    return code + b"\xcc" * (SWITCH_LENGTH - len(code))


def v2_adapter(item_id):
    _check_id(item_id)
    call = DIRECT_EQUIP_RVA - (SWITCH_RVA + 28)
    resume = SWITCH_END_RVA - (SWITCH_RVA + 33)
    result = (b"\x90" * 3 + bytes.fromhex("488b8fa00200004885c9740dba")
              + struct.pack("<i", item_id) + bytes.fromhex("4533c0e8")
              + struct.pack("<i", call) + b"\xe9" + struct.pack("<i", resume))
    return result + b"\xcc" * (SWITCH_LENGTH - len(result))


def legacy_adapter(item_id):
    _check_id(item_id)
    relative = DIRECT_EQUIP_RVA - (LEGACY_RVA + 28)
    return (b"\x90" * 3 + bytes.fromhex("488b89a00200004885c9740dba")
            + struct.pack("<i", item_id) + bytes.fromhex("4533c0e9")
            + struct.pack("<i", relative) + b"\xc3")


def _decode_legacy(region):
    if region == LEGACY_ORIGINAL:
        return False
    item_id = struct.unpack_from("<i", region, 16)[0]
    try:
        if region == legacy_adapter(item_id):
            return True
    except ValueError:
        pass
    raise ValueError("Unsupported weapon adapter")


def decode_region(region, original=None):
    """True if the site holds the current adapter (or, for file migration, v2).

    `original` is the full unpatched block for file checks; live checks pass
    None and accept only the original head or the exact current adapter.
    """
    if len(region) != SWITCH_LENGTH:
        raise ValueError("Unsupported weapon adapter")
    if original is not None and region == original:
        return False
    if original is None and region[:len(ORIGINAL_HEAD)] == ORIGINAL_HEAD:
        return False
    if region == adapter():
        return True
    if original is not None:
        try:
            if region == v2_adapter(struct.unpack_from("<i", region, 16)[0]):
                return True
        except ValueError:
            pass
    raise ValueError("Unsupported weapon adapter")


def normalize_native(data, original):
    """Return (data with both sites restored from `original`, enabled)."""
    site = slice(SWITCH_OFFSET, SWITCH_OFFSET + SWITCH_LENGTH)
    legacy = slice(LEGACY_OFFSET, LEGACY_OFFSET + len(LEGACY_ORIGINAL))
    enabled = decode_region(data[site], original[site])
    legacy_enabled = _decode_legacy(data[legacy])
    if enabled and legacy_enabled:
        raise ValueError("Unsupported weapon adapter")
    normalized = bytearray(data)
    normalized[site] = original[site]
    normalized[legacy] = LEGACY_ORIGINAL
    return normalized, enabled or legacy_enabled


PLAYER_LOG = Path.home() / "AppData/LocalLow/nexon/DAVE THE DIVER/Player.log"


def log_position(log=PLAYER_LOG):
    """Current Player.log size, to pass to equip_events() after queuing."""
    try:
        return Path(log).stat().st_size
    except FileNotFoundError:
        return 0


def equip_events(since, log=PLAYER_LOG):
    """Weapon loads logged after `since` that did not come from dive start-up.

    Every *WeaponHandler.EquipItem logs an Addressables load with a stack trace.
    Start-of-dive loads come from InstanceItemInventory.EquipSavedSlotData; any
    other EquipItem stack is a mid-dive equip such as this selector's.
    """
    try:
        with open(log, "rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(since if since <= size else 0)  # log is recreated per launch
            text = stream.read().decode("utf8", "replace")
    except FileNotFoundError:
        return []
    events = []
    for block in re.split(r"\r?\n\s*\r?\n", text):
        handler = re.search(r"^(\w*WeaponHandler):EquipItem\(", block, re.M)
        if handler and "EquipSavedSlotData" not in block:
            events.append(handler.group(1))
    return events


def extract_catalog(game, highest_only=True, names_cache=None):
    """Read only the user's local base-game equipment table; never distribute it.

    Each row gets official per-language `names` when the local text table can be
    read (optionally cached in the ignored local file `names_cache`).
    """
    aa = Path(game) / "DaveTheDiver_Data/StreamingAssets/aa"
    _, matches = catalog_entries(aa / "catalog.json", "DR_GameData_Equipment.json")
    match = next(x for x in matches if x["internal_id"].endswith("/DR_GameData_Equipment.json"))
    for dep in match["dependencies"]:
        path = aa / "StandaloneWindows64" / dep.replace("\\", "/").split("/")[-1]
        for name, data, flags in bundle_files(path)[1]:
            if not flags & 4:
                continue
            summary = serialized_summary(data)
            for obj in summary["objects"]:
                typ = summary["types"][obj["type_index"]]
                if typ["class_id"] != 49:
                    continue
                strings = [f["value"] for f in read_object_fields(typ, obj) if isinstance(f["value"], str)]
                if "DR_GameData_Equipment" not in strings:
                    continue
                script = max(strings, key=len)
                found = re.search(r"EquipmentItem@/", script)
                if found is None:
                    raise ValueError("Equipment table not found")
                rows, _ = json.JSONDecoder().raw_decode(script, found.end())
                result = []
                for row in rows:
                    # Limit the first implementation to installed base-game weapons.
                    if row.get("ItemType") not in (0, 1, 2, 3) or row.get("DLCType", 0) != 0:
                        continue
                    if not row.get("ItemScriptableID") or not row.get("ItemTextID"):
                        continue
                    key = row["ItemTextID"]
                    readable = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", key.removesuffix("_Name").replace("_", " "))
                    result.append({"id": int(row["TID"]), "name": readable, "text_id": key, "icon": row.get("ItemIcon") or "",
                                   "level": row.get("ItemLevel", 0), "type": row["ItemType"]})
                if not result or len({x["id"] for x in result}) != len(result):
                    raise ValueError("Invalid weapon catalogue")
                if highest_only:
                    # Keep one entry per weapon: its highest level (ties: highest ID).
                    best = {}
                    for row in result:
                        key = (row["type"], row["name"])
                        if key not in best or (row["level"], row["id"]) > (best[key]["level"], best[key]["id"]):
                            best[key] = row
                    result = list(best.values())
                try:
                    texts = item_names(game, names_cache)
                except Exception:
                    texts = {}  # official names are optional; derived names still work
                for row in result:
                    official = texts.get(row["text_id"], {})
                    row["names"] = {language: official.get(language) or row["name"] for language in TEXT_LANGUAGES}
                    row["category"] = weapon_category(row)
                    # Gun families use the game's own "<Family>_Type" labels (e.g. SniperGun_Type).
                    family = texts.get(row["category"] + "_Type", {})
                    row["category_names"] = {language: family.get(language, "") for language in TEXT_LANGUAGES}
                return sorted(result, key=lambda x: (x["type"], x["name"], x["level"], x["id"]))
    raise ValueError("Local weapon catalogue not found")


# Gun families as named by the game's "<Family>_Type" texts, matched against ItemTextID.
# Order matters: the first token found wins (e.g. "Sleep_Sniper" is a sniper rifle,
# "SleepGun" is the Hush Dart family).
GUN_FAMILIES = [("ShotGun", "ShotGun"), ("Sniper", "SniperGun"), ("SleepGun", "SleepGun"),
                ("GrenadeLauncher", "GrenadeLauncher"), ("StickyBombGun", "StickyBombGun"),
                ("NetGun", "NetGun"), ("IceGun", "IceGun"), ("DrainGun", "DrainGun"), ("BasicRifle", "BasicRifle")]
OTHER_CATEGORIES = {1: "Harpoon", 2: "HarpoonHead", 3: "Melee"}


def weapon_category(row):
    """Category key: a gun family (BasicRifle, ShotGun, SniperGun, ...) or Harpoon/HarpoonHead/Melee."""
    if row["type"] != 0:
        return OTHER_CATEGORIES.get(row["type"], "Other")
    text_id = row.get("text_id", "")
    for token, family in GUN_FAMILIES:
        if token in text_id:
            return family
    return "OtherGun"


# GUI language -> column of the game's own text tables.
TEXT_LANGUAGES = {"en": "english", "zh-TW": "chinesetraditional"}


def item_names(game, cache=None):
    """Official item names {ItemTextID: {gui language: text}} from the local InstanceItemText table.

    Decompressing the text bundle takes seconds in pure Python, so the result can
    be cached in a local JSON file keyed by the bundle paths, sizes and mtimes.
    """
    aa = Path(game) / "DaveTheDiver_Data/StreamingAssets/aa"
    _, matches = catalog_entries(aa / "catalog.json", "InstanceItemText.asset")
    match = next(x for x in matches if x["internal_id"].endswith("/InstanceItemText.asset"))
    paths = [aa / "StandaloneWindows64" / dep.replace("\\", "/").split("/")[-1] for dep in match["dependencies"]]
    key = [[str(path.resolve()), path.stat().st_size, path.stat().st_mtime_ns] for path in paths]
    if cache is not None:
        try:
            stored = json.loads(Path(cache).read_text("utf8"))
            if stored.get("key") == key and stored.get("languages") == TEXT_LANGUAGES and stored.get("names"):
                return stored["names"]
        except (OSError, ValueError, AttributeError):
            pass
    names = _read_item_names(paths)
    if cache is not None:
        try:
            Path(cache).write_text(json.dumps({"key": key, "languages": TEXT_LANGUAGES, "names": names},
                                              ensure_ascii=False), "utf8")
        except OSError:
            pass
    return names


def _read_item_names(paths):
    marker = "InstanceItemText".encode("utf8")
    for path in paths:
        for name, data, flags in bundle_files(path)[1]:
            if not flags & 4 or marker not in data:
                continue
            summary = serialized_summary(data)
            for obj in summary["objects"]:
                typ = summary["types"][obj["type_index"]]
                # Only decode the one text table; the bundle holds many large ones.
                if typ["class_id"] != 114 or marker not in bytes.fromhex(obj["hex"]):
                    continue
                fields = read_object_fields(typ, obj)
                if not any(f["path"] == "root/WorksheetName" and f["value"] == "InstanceItemText" for f in fields):
                    continue
                names = {}
                for field in fields:
                    row = field["value"]
                    if field["path"].startswith("root/dataArray/") and isinstance(row, dict) and "name" in row:
                        names[row["name"]] = {language: str(row.get(column) or "").strip()
                                              for language, column in TEXT_LANGUAGES.items()}
                if not names:
                    raise ValueError("Item text table is empty")
                return names
    raise ValueError("Item text table not found")


def arm_live(game, item_id, allowed_ids):
    """Queue a weapon in the exact game process after verifying the installed adapter.

    A successful return means queued, not that the game has equipped the item.
    """
    if item_id not in allowed_ids:
        raise ValueError("Weapon is not in the local catalogue")
    live_write(game, SWITCH_RVA, SWITCH_LENGTH, decode_region, PENDING_RVA, struct.pack("<i", item_id),
               "Enable the weapon selector while the game is closed, then restart")
    return item_id


def live_write(game, site_rva, site_length, site_ok, target_rva, payload, not_installed):
    """Write `payload` to unused RW slack in the one running game, then read it back.

    The process image and GameAssembly.dll paths must match `game`, and
    `site_ok(bytes at site_rva)` must accept the installed patch (False -> not
    installed; it may raise for unknown code). Only data is written; no code
    page or protection is changed.
    """
    if not (DATA_END_RVA <= target_rva and target_rva + len(payload) <= NEXT_SECTION_RVA):
        raise ValueError("Live write target is outside the unused .data slack")
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        raise OSError("64-bit Python is required")
    game = Path(game).resolve()
    expected_exe = game / "DaveTheDiver.exe"
    expected_dll = game / "GameAssembly.dll"
    k = ctypes.WinDLL("kernel32", use_last_error=True)

    class Process(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("parent", wintypes.DWORD), ("priority", wintypes.LONG), ("flags", wintypes.DWORD),
                    ("name", wintypes.WCHAR * 260)]

    class Module(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("module", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("global_usage", wintypes.DWORD), ("process_usage", wintypes.DWORD),
                    ("base", ctypes.c_void_p), ("bytes", wintypes.DWORD), ("handle", wintypes.HMODULE),
                    ("name", wintypes.WCHAR * 256), ("path", wintypes.WCHAR * 260)]

    signatures = {
        "CreateToolhelp32Snapshot": ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
        "Process32FirstW": ([wintypes.HANDLE, ctypes.POINTER(Process)], wintypes.BOOL),
        "Process32NextW": ([wintypes.HANDLE, ctypes.POINTER(Process)], wintypes.BOOL),
        "Module32FirstW": ([wintypes.HANDLE, ctypes.POINTER(Module)], wintypes.BOOL),
        "Module32NextW": ([wintypes.HANDLE, ctypes.POINTER(Module)], wintypes.BOOL),
        "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        "QueryFullProcessImageNameW": ([wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        "ReadProcessMemory": ([wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)], wintypes.BOOL),
        "WriteProcessMemory": ([wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)], wintypes.BOOL),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (args, restype) in signatures.items():
        function = getattr(k, name)
        function.argtypes, function.restype = args, restype

    def check(ok):
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    def snapshot(flags, pid):
        handle = k.CreateToolhelp32Snapshot(flags, pid)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    candidates = []
    snap = snapshot(2, 0)
    try:
        entry = Process(); entry.size = ctypes.sizeof(entry)
        ok = k.Process32FirstW(snap, ctypes.byref(entry))
        check(ok)
        while ok:
            if entry.name.casefold() == "davethediver.exe":
                candidates.append(entry.pid)
            ok = k.Process32NextW(snap, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:
            check(False)
    finally:
        k.CloseHandle(snap)
    if len(candidates) != 1:
        raise ValueError("Start one DAVE THE DIVER game process first")
    handle = k.OpenProcess(0x1000 | 0x10 | 0x20 | 0x8, False, candidates[0])
    check(handle)
    try:
        text = ctypes.create_unicode_buffer(32768); length = wintypes.DWORD(len(text))
        check(k.QueryFullProcessImageNameW(handle, 0, text, ctypes.byref(length)))
        if Path(text.value).resolve() != expected_exe:
            raise ValueError("Running game does not match the selected installation")
        module_base = None
        snap = snapshot(0x8 | 0x10, candidates[0])
        try:
            entry = Module(); entry.size = ctypes.sizeof(entry)
            ok = k.Module32FirstW(snap, ctypes.byref(entry)); check(ok)
            while ok:
                if entry.name.casefold() == "gameassembly.dll":
                    if Path(entry.path).resolve() != expected_dll:
                        raise ValueError("Running game module path does not match")
                    module_base = entry.base
                    break
                ok = k.Module32NextW(snap, ctypes.byref(entry))
        finally:
            k.CloseHandle(snap)
        if module_base is None:
            raise ValueError("GameAssembly.dll is not loaded")
        def read(address, count):
            buffer = ctypes.create_string_buffer(count); actual = ctypes.c_size_t()
            check(k.ReadProcessMemory(handle, address, buffer, count, ctypes.byref(actual)))
            if actual.value != count:
                raise OSError("Incomplete memory read")
            return buffer.raw

        if not site_ok(read(module_base + site_rva, site_length)):
            raise ValueError(not_installed)
        # Plain data write into the RW slack after .data; no code is modified.
        target = module_base + target_rva
        actual = ctypes.c_size_t()
        check(k.WriteProcessMemory(handle, target, payload, len(payload), ctypes.byref(actual)))
        if actual.value != len(payload) or read(target, len(payload)) != payload:
            raise OSError("Live write verification failed")
    finally:
        k.CloseHandle(handle)
