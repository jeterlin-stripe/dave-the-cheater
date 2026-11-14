"""Local file-based DAVE controls. Python standard library only; no injection."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from inspect_dave import bundle_files, write_bundle
from gui_language import translate

HERE = Path(__file__).resolve().parent
DEFAULT_GAME = Path(r"G:\SteamLibrary\steamapps\common\Dave the Diver")
NATIVE_HASH = "ed213c248bf53e62a3bf2223ff3f89467a6edff6cec7d3ea921ada6a6e2a6600"
BUNDLE_HASH = "9800d47efc3d4106b1207530c92c0be6ecdda4647c378e4fc3d7aa662d93ea7e"
BUNDLE_NAME = "7314e4d32b10a297b1b8f2c2d3fac26f.bundle"
NODE_NAME = "CAB-3fc8e257bbfa28c753fb863c50d033ff"
SPEED_OFFSET = 7500
PATCHES = [
    ("oxygen", 24359754, bytes.fromhex("f3440f58c6"), bytes.fromhex("9090909090")),
    ("ammo", 24285869, bytes.fromhex("83ea01"), bytes.fromhex("83ea00")),
    ("ammo", 24289351, bytes.fromhex("83e901"), bytes.fromhex("83e900")),
    ("invincible", 8236080, bytes.fromhex("48895c"), bytes.fromhex("b001c3")),
    ("invincible", 24369456, bytes.fromhex("48"), bytes.fromhex("c3")),
    # PlayerCharacter.AvailableLiftDroneCount decrements in cargo interactions.
    ("drone", 26938848, bytes.fromhex("ff8ad0010000"), b"\x90" * 6),
    ("drone", 26941952, bytes.fromhex("ff8ad0010000"), b"\x90" * 6),
    ("drone", 27154928, bytes.fromhex("ff8ad0010000"), b"\x90" * 6),
    ("drone", 29786718, bytes.fromhex("ff8ad0010000"), b"\x90" * 6),
]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def game_running():
    """Enumerate all Windows processes, including outside this Python process tree."""
    class ProcessEntry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    k.Process32FirstW.restype = wintypes.BOOL
    k.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    k.Process32NextW.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    handle = k.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), "無法確認遊戲是否執行中；未套用任何變更。")
    entry = ProcessEntry()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        ok = k.Process32FirstW(handle, ctypes.byref(entry))
        if not ok:
            raise OSError(ctypes.get_last_error(), "無法讀取程序清單。")
        while ok:
            if entry.szExeFile.casefold() == "davethediver.exe":
                return True
            ok = k.Process32NextW(handle, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise OSError(ctypes.get_last_error(), "程序清單讀取不完整。")
        return False
    finally:
        k.CloseHandle(handle)


class Controller:
    def __init__(self, game):
        self.game = Path(game).resolve()
        self.native_path = self.game / "GameAssembly.dll"
        self.bundle_path = self.game / "DaveTheDiver_Data/StreamingAssets/aa/StandaloneWindows64" / BUNDLE_NAME
        self.native_original = (HERE / "resources-upgrade/original/GameAssembly.dll").read_bytes()
        self.bundle_original_path = HERE / "swim-1.5x/original" / BUNDLE_NAME
        self.bundle_original = self.bundle_original_path.read_bytes()
        if digest(self.native_original) != NATIVE_HASH or digest(self.bundle_original) != BUNDLE_HASH:
            raise ValueError("原始備份校驗失敗，請保留檔案並停止操作。")
        self.info, self.original_nodes = bundle_files(self.bundle_original_path)

    def decode_native(self, data):
        normalized = bytearray(data)
        values = {"ammo": [], "oxygen": [], "invincible": [], "drone": []}
        for feature, offset, before, after in PATCHES:
            current = data[offset:offset + len(before)]
            legacy = feature == "ammo" and offset == 24285869 and current == b"\x90" * 3
            if current not in (before, after) and not legacy:
                raise ValueError("遊戲程式版本或修改內容不符合；未覆寫。")
            values[feature].append(current != before)
            normalized[offset:offset + len(before)] = before
        if digest(normalized) != NATIVE_HASH:
            raise ValueError("遊戲程式已有更新或其他修改；本工具拒絕覆寫。")
        return {feature: all(states) for feature, states in values.items()}

    def decode_bundle(self):
        raw = self.bundle_path.read_bytes()
        if digest(raw) == BUNDLE_HASH:
            return 1.0, raw
        info, nodes = bundle_files(self.bundle_path)
        if info != self.info or len(nodes) != len(self.original_nodes):
            raise ValueError("速度資源版本不符合；未覆寫。")
        speed = None
        for original, current in zip(self.original_nodes, nodes):
            name, data, flags = current
            if (name, flags, len(data)) != (original[0], original[2], len(original[1])):
                raise ValueError("速度資源結構不符合。")
            normalized = bytearray(data)
            if name == NODE_NAME:
                speed = struct.unpack_from("<f", data, SPEED_OFFSET)[0]
                normalized[SPEED_OFFSET:SPEED_OFFSET + 4] = original[1][SPEED_OFFSET:SPEED_OFFSET + 4]
            if bytes(normalized) != original[1]:
                raise ValueError("速度資源包含其他修改；本工具拒絕覆寫。")
        if speed is None or not math.isfinite(speed) or speed <= 0:
            raise ValueError("無法辨識速度數值。")
        original_speed = struct.unpack_from("<f", next(b for n, b, f in self.original_nodes if n == NODE_NAME), SPEED_OFFSET)[0]
        return speed / original_speed, raw

    def read(self):
        native = self.native_path.read_bytes()
        settings = self.decode_native(native)
        factor, bundle = self.decode_bundle()
        return {**settings, "speed": factor}, native, bundle

    def build(self, settings):
        factor = float(settings["speed"])
        if not math.isfinite(factor) or not 0.1 <= factor <= 20:
            raise ValueError("倍率請輸入 0.1 至 20 之間的數字。")
        native = bytearray(self.native_original)
        for feature, offset, before, after in PATCHES:
            if settings.get(feature, False):
                native[offset:offset + len(after)] = after
        if factor == 1:
            bundle = self.bundle_original
        else:
            nodes = []
            for name, data, flags in self.original_nodes:
                patch = bytearray(data)
                if name == NODE_NAME:
                    original = struct.unpack_from("<f", data, SPEED_OFFSET)[0]
                    struct.pack_into("<f", patch, SPEED_OFFSET, original * factor)
                nodes.append((name, bytes(patch), flags))
            bundle = write_bundle(self.info, nodes)
        self.decode_native(bytes(native))
        return bytes(native), bundle

    def apply(self, settings):
        if game_running():
            raise ValueError("請先完全關閉 DAVE THE DIVER，再按套用。")
        current, old_native, old_bundle = self.read()
        new_native, new_bundle = self.build(settings)
        if game_running():
            raise ValueError("遊戲剛剛啟動，已取消套用。")
        # Recheck after building; never overwrite an intervening change.
        if self.native_path.read_bytes() != old_native or self.bundle_path.read_bytes() != old_bundle:
            raise ValueError("檔案在檢查後發生變更，已取消套用。")
        written = []
        try:
            for path, previous, replacement in [(self.native_path, old_native, new_native), (self.bundle_path, old_bundle, new_bundle)]:
                if previous == replacement:
                    continue
                # r+b does not truncate an inaccessible/locked file before checking access.
                with path.open("r+b") as stream:
                    written.append((path, previous))
                    stream.write(replacement)
                    stream.truncate()
                    stream.flush()
                if path.read_bytes() != replacement:
                    raise OSError("寫入後校驗失敗。")
        except Exception as error:
            rollback_errors = []
            for path, previous in reversed(written):
                try:
                    with path.open("r+b") as stream:
                        stream.write(previous)
                        stream.truncate()
                    if path.read_bytes() != previous:
                        raise OSError("還原校驗失敗")
                except Exception as rollback_error:
                    rollback_errors.append(f"{path}: {rollback_error}")
            if rollback_errors:
                raise OSError("套用失敗，且自動還原不完整。請勿啟動遊戲。\n" + "\n".join(rollback_errors)) from error
            raise OSError(f"未能套用，已保留／還原先前版本。\n{error}") from error
        verified, _, _ = self.read()
        if any(verified[key] != bool(settings.get(key, False)) for key in ("ammo", "oxygen", "invincible", "drone")) or not math.isclose(verified["speed"], float(settings["speed"]), rel_tol=1e-6):
            raise OSError("讀回的設定與預期不同。請先不要啟動遊戲。")
        # A log failure must not make a successful game-file update look like a failed one.
        try:
            (HERE / "gui-last-settings.json").write_text(json.dumps({"game": str(self.game), **verified}, indent=2), encoding="utf8")
        except OSError:
            pass
        return verified


class Panel(tk.Tk):
    def __init__(self):
        super().__init__()
        try:
            preference = json.loads((HERE / "gui-preferences.json").read_text("utf8"))
        except (OSError, ValueError):
            preference = {}
        self.language = preference.get("language", "zh-TW")
        if self.language not in ("zh-TW", "en"):
            self.language = "zh-TW"
        self.localized_texts = []
        self.raw_status = "正在讀取目前設定…"
        self.title(translate("Dave the Cheater", self.language))
        self.geometry("760x650")
        self.minsize(740, 630)
        self.configure(bg="#101b2a")
        self.path = tk.StringVar(value=str(DEFAULT_GAME))
        self.ammo, self.invincible = tk.BooleanVar(), tk.BooleanVar()
        self.drone = tk.BooleanVar()
        self.speed = tk.StringVar(value="3.5")
        self.oxygen = True
        self.loaded = False
        self.pending = False
        self.status = tk.StringVar(value=translate(self.raw_status, self.language))
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#101b2a")
        style.configure("TLabel", background="#101b2a", foreground="#e7f1ff", font=("Microsoft JhengHei UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 23, "bold"), foreground="#65d5ee")
        style.configure("Status.TLabel", background="#101b2a", foreground="#e7f1ff", padding=10)
        style.configure("SuccessStatus.TLabel", background="#153d32", foreground="#8df0b2", padding=10, font=("Microsoft JhengHei UI", 10, "bold"))
        style.configure("TButton", font=("Microsoft JhengHei UI", 10), padding=9)
        style.configure("Switch.TCheckbutton", background="#20374a", foreground="white", padding=12, font=("Microsoft JhengHei UI", 12))
        style.map("Switch.TCheckbutton", background=[("selected", "#087f8c")], foreground=[("selected", "white")])
        body = ttk.Frame(self, padding=24)
        body.pack(fill="both", expand=True)
        header = ttk.Frame(body)
        header.pack(fill="x")
        ttk.Label(header, textvariable=self.localized("Dave the Cheater"), style="Title.TLabel").pack(side="left")
        self.language_choice = tk.StringVar(value="English" if self.language == "en" else "繁體中文")
        language_box = ttk.Combobox(header, textvariable=self.language_choice, values=("繁體中文", "English"), state="readonly", width=12)
        language_box.pack(side="right")
        language_box.bind("<<ComboboxSelected>>", self.change_language)
        ttk.Label(body, textvariable=self.localized("修改遊戲檔案 · 套用後重新啟動生效")).pack(anchor="w", pady=(4, 20))
        row = ttk.Frame(body)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.path).pack(side="left", fill="x", expand=True)
        ttk.Button(row, textvariable=self.localized("選擇遊戲資料夾"), command=self.browse).pack(side="right", padx=(8, 0))
        switches = ttk.Frame(body)
        switches.pack(fill="x", pady=18)
        ttk.Checkbutton(switches, textvariable=self.localized("無限彈藥"), variable=self.ammo, style="Switch.TCheckbutton", command=self.dirty).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Checkbutton(switches, textvariable=self.localized("無敵"), variable=self.invincible, style="Switch.TCheckbutton", command=self.dirty).pack(side="left", fill="x", expand=True)
        ttk.Checkbutton(switches, textvariable=self.localized("無限貨物無人機"), variable=self.drone, style="Switch.TCheckbutton", command=self.dirty).pack(side="left", fill="x", expand=True, padx=(8, 0))
        ttk.Label(body, textvariable=self.localized("無人機開啟後不扣搬運次數；已零次時可能需要先重新潛水。"), wraplength=700).pack(anchor="w", pady=(0, 12))
        row = ttk.Frame(body)
        row.pack(fill="x", pady=4)
        ttk.Label(row, textvariable=self.localized("水下移動速度倍率"), font=("Microsoft JhengHei UI", 12)).pack(side="left")
        ttk.Spinbox(row, from_=0.1, to=20, increment=0.5, textvariable=self.speed, width=8, font=("Segoe UI", 15)).pack(side="right")
        self.speed.trace_add("write", lambda *_: self.dirty())
        ttk.Label(body, textvariable=self.localized("1 = 原始速度；可輸入 0.1–20，例如 3.5。\n氧氣補丁會保留目前狀態；無敵關閉後仍會受傷。"), wraplength=700).pack(anchor="w", pady=(10, 16))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        ttk.Button(buttons, textvariable=self.localized("套用設定"), command=self.apply).pack(side="left", fill="x", expand=True)
        ttk.Button(buttons, textvariable=self.localized("讀取目前設定"), command=self.refresh).pack(side="left", padx=8)
        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(12, 16))
        ttk.Button(actions, textvariable=self.localized("還原全部原始設定"), command=self.restore).pack(side="left")
        ttk.Button(actions, textvariable=self.localized("啟動遊戲"), command=self.launch_game).pack(side="right")
        self.status_label = ttk.Label(body, textvariable=self.status, wraplength=675, style="Status.TLabel")
        self.status_label.pack(fill="x", anchor="w")
        ttk.Label(body, textvariable=self.localized("彈藥涵蓋共用潛水槍械流程；尚未驗證所有 DLC／特殊武器。\n遊戲更新或其他模組造成版本不同時，工具會拒絕覆寫。"), wraplength=700, foreground="#a6b8ca").pack(anchor="w", pady=(16, 0))
        self.after(150, self.refresh)

    def tr(self, source):
        return translate(source, self.language)

    def localized(self, source):
        value = tk.StringVar(value=self.tr(source))
        self.localized_texts.append((value, source))
        return value

    def set_status(self, source):
        self.raw_status = source
        self.status.set(self.tr(source))
        success = source in ("套用成功，已讀回核對。請重新啟動遊戲。", "已還原全部原始檔案，並完成核對。")
        self.status_label.configure(style="SuccessStatus.TLabel" if success else "Status.TLabel")

    @staticmethod
    def error_source(error):
        if isinstance(error, FileNotFoundError):
            return "找不到所需檔案：" + str(error.filename or "")
        if isinstance(error, PermissionError):
            return "無法存取檔案，請確認檔案未被佔用且目前帳號有寫入權限。"
        if isinstance(error, ValueError) and "could not convert string to float" in str(error):
            return "倍率請輸入 0.1 至 20 之間的數字。"
        return str(error)

    def error_text(self, error):
        return self.tr(self.error_source(error))

    def change_language(self, _event=None):
        self.language = "en" if self.language_choice.get() == "English" else "zh-TW"
        self.title(self.tr("Dave the Cheater"))
        for variable, source in self.localized_texts:
            variable.set(self.tr(source))
        self.status.set(self.tr(self.raw_status))
        try:
            (HERE / "gui-preferences.json").write_text(json.dumps({"language": self.language}), encoding="utf8")
        except OSError:
            self.set_status("語言偏好無法儲存；本次切換仍已生效。")

    def dirty(self):
        if self.loaded:
            self.pending = True
            self.set_status("設定尚未套用。請先關閉遊戲，再按「套用設定」。")

    def launch_game(self):
        try:
            if game_running():
                self.set_status("遊戲已在執行中。")
                return
            if self.pending and not messagebox.askyesno(
                self.tr("尚有未套用的設定"),
                self.tr("目前變更尚未套用。要使用先前已套用的設定啟動遊戲嗎？"),
                parent=self,
            ):
                return
            os.startfile("steam://rungameid/1868140")
            self.set_status("已向 Steam 發送啟動請求。")
        except Exception as error:
            messagebox.showerror(self.tr("無法啟動遊戲"), self.error_text(error), parent=self)

    def browse(self):
        selected = filedialog.askdirectory(title=self.tr("選擇含有 DaveTheDiver.exe 的資料夾"))
        if selected:
            self.path.set(selected)
            self.refresh()

    def set_state(self, state):
        self.loaded = False
        self.ammo.set(state["ammo"])
        self.invincible.set(state["invincible"])
        self.drone.set(state["drone"])
        self.speed.set(f"{state['speed']:.6g}")
        self.oxygen = state["oxygen"]
        self.loaded = True
        self.pending = False

    def refresh(self):
        try:
            state, _, _ = Controller(self.path.get()).read()
            self.set_state(state)
            self.set_status("已讀取檔案設定。氧氣補丁：" + ("開啟" if self.oxygen else "關閉") + "。")
        except Exception as error:
            self.loaded = False
            self.set_status("讀取失敗：" + self.error_source(error))

    def apply(self):
        try:
            controller = Controller(self.path.get())
            # Preserve actual oxygen state, even if the folder was edited manually.
            actual, _, _ = controller.read()
            state = controller.apply({"ammo": self.ammo.get(), "invincible": self.invincible.get(), "drone": self.drone.get(), "speed": self.speed.get(), "oxygen": actual["oxygen"]})
            self.set_state(state)
            self.set_status("套用成功，已讀回核對。請重新啟動遊戲。")
        except Exception as error:
            self.set_status("未能套用；請查看錯誤訊息。")
            messagebox.showerror(self.tr("套用失敗"), self.error_text(error))

    def restore(self):
        if not messagebox.askyesno(self.tr("還原原始設定"), self.tr("將還原原始速度、彈藥、無人機與受傷規則，也會關閉氧氣補丁。是否繼續？")):
            return
        try:
            self.set_state(Controller(self.path.get()).apply({"ammo": False, "invincible": False, "drone": False, "oxygen": False, "speed": 1}))
            self.set_status("已還原全部原始檔案，並完成核對。")
        except Exception as error:
            messagebox.showerror(self.tr("還原失敗"), self.error_text(error))


if __name__ == "__main__":
    Panel().mainloop()
