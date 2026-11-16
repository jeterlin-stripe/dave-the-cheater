"""Live swimming-speed and backpack-capacity multipliers (supported build only).

Like the sushi-bar patch, a closed-game file patch makes the game read a factor
from unused, zero-initialised read/write slack after .data; the panel then
changes the factor while the game runs by writing `factor - 1` there (zero =
1x, so a fresh game starts unchanged).

Each hook replaces one instruction with a `call` to a small leaf routine placed
in int3 padding between functions (outside every .pdata range, so the routine
needs no unwind data: it never touches rsp and cannot fault). Each routine is
split over two padding runs joined by a `jmp`, because no padding run is
longer than 15 bytes.

Swimming: `PlayerCharacter.DetermineMoveSpeed` (called from `ApplyMovement`)
is the only reader of the base speed `PlayerCharacter+0x378`. The load
`movss xmm1,[rbx+0x378]` becomes `xmm1 = base * (1 + swim slot)`.

Backpack: the pickup cap/heavy debuff come from the inventory upgrade's
`OverwightThreshold` (+0x50), read only by `OverweightProperty.
get_OverloadedThreshold` and `GetDebuff`; both `movss xmm6,[rax+0x50]` loads
are scaled (live, re-evaluated on every pickup). The displayed weight limit /
slowdown point (`LootBox.weightMax`, from stat 9 = `LootboxWeight`) is
computed by `LootBox.Load` (each dive) and `LootBox.Add_Lobby`; both
`addss xmm0,[reg+0x38]` sites become `stat * (1 + slot) + WeightParameter`,
so that part changes from the next dive.
"""
import math
import struct

SWIM_SLOT_RVA = 0x7F41FF8       # unused RW slack after .data (weapon 0x7F41FF0, sushi 0x7F41FF4)
BACKPACK_SLOT_RVA = 0x7F41FFC
IL2CPP_DELTA = 0x1200           # il2cpp section: raw file offset = RVA - 0x1200
MIN_FACTOR, MAX_FACTOR = 0.1, 20.0
UNLIMITED = "unlimited"
UNLIMITED_FACTOR = 1000.0       # backpack "unlimited": 1000x every limit
CC = 0xCC


def _rel(at, end, target):
    """rel32 operand for an instruction at RVA `at` whose encoding ends `end` bytes later."""
    return struct.pack("<i", target - (at + end))


def _call(at, target, length):
    return b"\xe8" + _rel(at, 5, target) + bytes.fromhex("0f1f00")[:length - 5] if length > 5 else b"\xe8" + _rel(at, 5, target)


def _hook(site, original, first, second, first_body, second_body):
    """Site call -> first cave (body + jmp) -> second cave (body ending in ret)."""
    head = first_body(first)
    stage1 = head + b"\xe9" + _rel(first + len(head), 5, second)
    stage2 = second_body(second)
    return [(site, bytes.fromhex(original), _call(site, first, len(bytes.fromhex(original)))),
            (first, bytes([CC]) * len(stage1), stage1),
            (second, bytes([CC]) * len(stage2), stage2)]


def _slot_load(register_code, slot):
    # movss xmmN,[rip+slot]  (f3 0f 10 /r with mod=00 rm=101)
    return lambda at: bytes.fromhex("f30f10") + bytes([0x05 | register_code << 3]) + _rel(at, 8, slot)


def _swim():
    return _hook(0x7BF365, "f30f108b78030000", 0x7C00C3, 0x7C4871,
                 lambda at: bytes.fromhex("f30f108b78030000"),                     # movss xmm1,[rbx+0x378]
                 lambda at: _slot_load(0, SWIM_SLOT_RVA)(at)                      # movss xmm0,[slot]
                 + bytes.fromhex("0f59c1" "0f58c8" "c3"))                        # mulps xmm0,xmm1; addps xmm1,xmm0; ret


def _backpack():
    threshold_tail = lambda at: _slot_load(0, BACKPACK_SLOT_RVA)(at) + bytes.fromhex("0f59c6" "0f58f0" "c3")  # xmm6 += xmm6*s
    regions = _hook(0x1C5CBDE, "f30f107050", 0x1C5C2E1, 0x1C5F5B1,
                    lambda at: bytes.fromhex("f30f107050"), threshold_tail)            # get_OverloadedThreshold
    regions.append((0x1C5CAB4, bytes.fromhex("f30f107050"), _call(0x1C5CAB4, 0x1C5C2E1, 5)))  # GetDebuff, same routine
    # weightMax = stat + stat*s + WeightParameter  (xmm1 is dead at both sites)
    regions += _hook(0x1AA2E33, "f30f584338", 0x1AA7553, 0x1AA87E1, _slot_load(1, BACKPACK_SLOT_RVA),
                     lambda at: bytes.fromhex("f30f59c8" "f30f58c1" "f30f584338" "c3"))     # LootBox.Load ([rbx+0x38])
    regions += _hook(0x1A9EC04, "f30f584638", 0x1A9CF52, 0x1A96FE1, _slot_load(1, BACKPACK_SLOT_RVA),
                     lambda at: bytes.fromhex("f30f59c8" "f30f58c1" "f30f584638" "c3"))     # LootBox.Add_Lobby ([rsi+0x38])
    return regions


FEATURES = {"swim_live": _swim(), "backpack_live": _backpack()}
# The routine that reads each slot; live writes require it to be installed exactly.
SLOT_READERS = {"swim_live": FEATURES["swim_live"][2], "backpack_live": FEATURES["backpack_live"][2]}
MISMATCH = "即時倍率程式碼不符合；未覆寫。"


def normalize(data, feature):
    """Report whether `feature` is installed in a whole-DLL bytearray and restore the original bytes."""
    states = set()
    for rva, original, patched in FEATURES[feature]:
        current = bytes(data[rva - IL2CPP_DELTA:rva - IL2CPP_DELTA + len(original)])
        if current not in (original, patched):
            raise ValueError(MISMATCH)
        states.add(current == patched)
        data[rva - IL2CPP_DELTA:rva - IL2CPP_DELTA + len(original)] = original
    if len(states) != 1:
        raise ValueError(MISMATCH)  # partially installed
    return states.pop()


def apply(data, feature, enabled):
    """Install `feature` into a bytearray holding the original bytes."""
    for rva, original, patched in FEATURES[feature]:
        if bytes(data[rva - IL2CPP_DELTA:rva - IL2CPP_DELTA + len(original)]) != original:
            raise ValueError(MISMATCH)
    if enabled:
        for rva, original, patched in FEATURES[feature]:
            data[rva - IL2CPP_DELTA:rva - IL2CPP_DELTA + len(original)] = patched


def factor_value(value, allow_unlimited=False):
    """Validated factor: 0.1-20, or UNLIMITED where allowed."""
    if allow_unlimited and value == UNLIMITED:
        return UNLIMITED
    try:
        factor = float(value)
    except (TypeError, ValueError):
        factor = math.nan
    if not math.isfinite(factor) or not MIN_FACTOR <= factor <= MAX_FACTOR:
        raise ValueError("背包容量倍率請輸入 0.1 至 20 之間的數字。" if allow_unlimited else "倍率請輸入 0.1 至 20 之間的數字。")
    return factor


def slot_value(value, allow_unlimited=False):
    factor = factor_value(value, allow_unlimited)
    return struct.pack("<f", (UNLIMITED_FACTOR if factor == UNLIMITED else factor) - 1.0)


def _reader_check(feature):
    rva, original, patched = SLOT_READERS[feature]

    def check(region):
        region = bytes(region)
        if region == original:
            return False
        if region == patched:
            return True
        raise ValueError(MISMATCH)
    return rva, len(original), check


def _set_live(game, feature, slot, payload):
    import weapon_selector
    rva, length, check = _reader_check(feature)
    weapon_selector.live_write(game, rva, length, check, slot, payload,
                               "Enable live multipliers while the game is closed, then restart")


def set_swim(game, factor):
    payload = slot_value(factor)
    _set_live(game, "swim_live", SWIM_SLOT_RVA, payload)
    return float(factor)


def set_backpack(game, value):
    payload = slot_value(value, allow_unlimited=True)
    _set_live(game, "backpack_live", BACKPACK_SLOT_RVA, payload)
    return factor_value(value, allow_unlimited=True)
