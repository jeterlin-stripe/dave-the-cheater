"""Live sushi-bar walking speed: DaveMoveValue.get_speedMultiplier reads a live factor.

StaffDave.CalcMoveSpeed (sushi bar), StaffDaveEvent.CalcMoveSpeed and
JungleSushiBarStaffDave.OnUpdate/UpdateMovement are the only callers of this
getter. They multiply its result (the current Tired/Walk/Run/Crawl multiplier
from DaveMoveData) into Dave's restaurant move speed.

The closed-game file patch rewrites the 80-byte getter body in place so it
returns `m + m * extra`, where `extra` is a float in unused read/write slack
after .data. The slack is zero at load, so the game starts at 1x; the panel
changes speed while the game runs by writing `factor - 1` to that slot.
The function's .pdata end is extended to cover the whole rewritten body.
"""
import math
import struct

GETTER_RVA = 0xC262B0           # DaveMoveValue.get_speedMultiplier, supported build only
OFFSET = GETTER_RVA - 0x1200    # il2cpp section: raw = RVA - 0x1200 (12734640)
LENGTH = 80                     # up to the next function at RVA 0xC26300
THROW_RVA = 0x57A390            # il2cpp exception helper already called by the original body
SLOT_RVA = 0x7F41FF4            # unused RW slack after .data (weapon selector uses 0x7F41FF0)
PDATA_END_OFFSET = 131332664    # raw offset of this function's RUNTIME_FUNCTION.EndAddress
PDATA_END_ORIGINAL = 0xC262FD
PDATA_END_PATCHED = GETTER_RVA + LENGTH
ORIGINAL = bytes.fromhex(
    "4883ec28837928ff742f488b51204885d27434488b52184885d2742b48634128"
    "3b4218731c488b4cc2204885c97418f30f1041144883c428c30f57c04883c428"
    "c3e88a4095ffcce8944095ffcccccccc")
MIN_FACTOR, MAX_FACTOR = 0.1, 10.0


def _rip(at, end, target):
    """rel32 for an instruction at body offset `at` (operand ends at `end`)."""
    return struct.pack("<i", target - (GETTER_RVA + end))


def patched():
    """Rewritten getter: returns multiplier * (1 + [SLOT])."""
    code = bytearray()
    code += bytes.fromhex("4883ec28")          # 00 sub rsp,0x28 (same prologue as the unwind info)
    code += bytes.fromhex("0f57c0")            # 04 xorps xmm0,xmm0
    code += bytes.fromhex("48634128")          # 07 movsxd rax,[rcx+0x28]   (move type index)
    code += bytes.fromhex("83f8ff")            # 0b cmp eax,-1
    code += bytes.fromhex("743b")              # 0e je  exit (no move type: return 0)
    code += bytes.fromhex("488b51204885d2")    # 10 mov rdx,[rcx+0x20]; test rdx,rdx
    code += bytes.fromhex("7418")              # 17 je  throw
    code += bytes.fromhex("488b52184885d2")    # 19 mov rdx,[rdx+0x18]; test rdx,rdx
    code += bytes.fromhex("740f")              # 20 je  throw
    code += bytes.fromhex("3b4218")            # 22 cmp eax,[rdx+0x18]
    code += bytes.fromhex("730a")              # 25 jae throw
    code += bytes.fromhex("488b4cc2204885c9")  # 27 mov rcx,[rdx+rax*8+0x20]; test rcx,rcx
    code += bytes.fromhex("7505")              # 2f jne load
    code += b"\xe8" + _rip(0x31, 0x36, THROW_RVA)                  # 31 throw (return address stays inside)
    code += bytes.fromhex("f30f104114")        # 36 load: movss xmm0,[rcx+0x14]
    code += bytes.fromhex("f30f100d") + _rip(0x3B, 0x43, SLOT_RVA)  # 3b movss xmm1,[rip+slot]
    code += bytes.fromhex("f30f59c8")          # 43 mulss xmm1,xmm0
    code += bytes.fromhex("f30f58c1")          # 47 addss xmm0,xmm1
    code += bytes.fromhex("4883c428c3")        # 4b exit: add rsp,0x28; ret
    assert len(code) == LENGTH
    return bytes(code)


def is_installed(region):
    """True for the patched body, False for the original; anything else is rejected."""
    region = bytes(region)
    if region == ORIGINAL:
        return False
    if region == patched():
        return True
    raise ValueError("餐廳移動速度程式碼不符合；未覆寫。")


def _pdata_end(data):
    return struct.unpack_from("<I", data, PDATA_END_OFFSET)[0]


def normalize(data):
    """Report whether the patch is in a whole-DLL bytearray and restore the original bytes."""
    installed = is_installed(data[OFFSET:OFFSET + LENGTH])
    if _pdata_end(data) != (PDATA_END_PATCHED if installed else PDATA_END_ORIGINAL):
        raise ValueError("餐廳移動速度程式碼不符合；未覆寫。")
    data[OFFSET:OFFSET + LENGTH] = ORIGINAL
    struct.pack_into("<I", data, PDATA_END_OFFSET, PDATA_END_ORIGINAL)
    return installed


def apply(data, enabled):
    """Install the patch into a bytearray holding the original bytes."""
    if data[OFFSET:OFFSET + LENGTH] != ORIGINAL or _pdata_end(data) != PDATA_END_ORIGINAL:
        raise ValueError("餐廳移動速度程式碼不符合；未覆寫。")
    if enabled:
        data[OFFSET:OFFSET + LENGTH] = patched()
        struct.pack_into("<I", data, PDATA_END_OFFSET, PDATA_END_PATCHED)


def slot_value(factor):
    """Bytes for the live slot: factor - 1 as float32 (0 means 1x)."""
    try:
        factor = float(factor)
    except (TypeError, ValueError):
        factor = math.nan
    if not math.isfinite(factor) or not MIN_FACTOR <= factor <= MAX_FACTOR:
        raise ValueError("餐廳移動速度倍率請輸入 0.1 至 10 之間的數字。")
    return struct.pack("<f", factor - 1.0)


def set_live(game, factor):
    """Write the factor into the running game after verifying the exact installed getter."""
    import weapon_selector
    payload = slot_value(factor)
    weapon_selector.live_write(game, GETTER_RVA, LENGTH, is_installed, SLOT_RVA, payload,
                               "Enable live multipliers while the game is closed, then restart")
    return float(factor)
