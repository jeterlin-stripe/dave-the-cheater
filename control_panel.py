"""DAVE controls with guarded file patches and an underwater weapon selector."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
import queue
import threading
from pathlib import Path
import struct
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from inspect_dave import bundle_files, write_bundle
from gui_language import translate, TRANSLATIONS
import weapon_selector as weapons
import sushi_speed
import weapon_icons

HERE = Path(__file__).resolve().parent
ICON_CACHE = HERE / "weapon-icons"  # local, git-ignored crops of the game's own item icons
NAMES_CACHE = HERE / "weapon-names-cache.json"  # local, git-ignored copy of the game's own item names
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
        normalized, weapon_enabled = weapons.normalize_native(data, self.native_original)
        sushi_live = sushi_speed.normalize(normalized)
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
        return {**{feature: all(states) for feature, states in values.items()},
                "weapon_enabled": weapon_enabled, "weapon_id": weapons.DEFAULT_ITEM, "sushi_live": sushi_live}

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
        if settings.get("weapon_enabled", False):
            selected = weapons.adapter()  # weapon choice is queued live, not stored in the file
            native[weapons.SWITCH_OFFSET:weapons.SWITCH_OFFSET + len(selected)] = selected
        sushi_speed.apply(native, settings.get("sushi_live", False))
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
        if verified["weapon_enabled"] != bool(settings.get("weapon_enabled", False)) or verified["sushi_live"] != bool(settings.get("sushi_live", False)):
            raise OSError("讀回的設定與預期不同。請先不要啟動遊戲。")
        # A log failure must not make a successful game-file update look like a failed one.
        try:
            (HERE / "gui-last-settings.json").write_text(json.dumps({"game": str(self.game), **verified}, indent=2), encoding="utf8")
        except OSError:
            pass
        return verified


BG, CARD, TEXT, MUTED, ACCENT = "#101b2a", "#16263a", "#e7f1ff", "#a6b8ca", "#087f8c"
STATUS_COLORS = {"info": ("#1b2c3f", TEXT), "success": ("#153d32", "#8df0b2"),
                 "warning": ("#3d3415", "#f5d77a"), "error": ("#4a1d24", "#ffb3bd")}
# Category tabs in display order. Gun families take the game's own "<Family>_Type" names;
# the others use panel translations.
WEAPON_CATEGORIES = ["", "BasicRifle", "ShotGun", "SniperGun", "SleepGun", "GrenadeLauncher", "StickyBombGun",
                     "NetGun", "IceGun", "DrainGun", "OtherGun", "Harpoon", "HarpoonHead", "Melee", "Other"]
CATEGORY_LABELS = {"": "全部", "Harpoon": "魚叉槍", "HarpoonHead": "魚叉頭", "Melee": "近戰武器",
                   "OtherGun": "其他槍械", "Other": "其他"}
UI_FONT = "Microsoft JhengHei UI"
EQUIP_POLL_MS, EQUIP_POLL_LIMIT = 1000, 180
SUSHI_NOTE = "Dave 在壽司店（含叢林 DLC 店面）走路、奔跑與疲累時的速度；1 = 原始速度，可輸入 0.1–10。遊戲執行中修改會立即生效，面板開著時重新啟動遊戲也會自動套用。"


class Panel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.preferences = self.read_preferences()
        self.language = self.preferences.get("language", "zh-TW")
        if self.language not in ("zh-TW", "en"):
            self.language = "zh-TW"
        self.localized_texts = []
        self.raw_status, self.status_kind = "正在讀取目前設定…", "info"
        self.title(translate("Dave the Cheater", self.language))
        height = min(980, self.winfo_screenheight() - 80)
        self.geometry(f"840x{height}")
        self.minsize(760, min(760, height))
        self.configure(bg=BG)
        self.path = tk.StringVar(value=str(DEFAULT_GAME))
        self.oxygen, self.ammo = tk.BooleanVar(), tk.BooleanVar()
        self.invincible, self.drone = tk.BooleanVar(), tk.BooleanVar()
        self.weapon_enabled = tk.BooleanVar()
        self.weapon_installed = None
        self.weapon_catalog, self.visible_weapons = [], []
        self.weapon_search, self.weapon_category = tk.StringVar(), tk.StringVar(value="")
        self.category_buttons = {}
        self.raw_weapon_status, self.weapon_kind, self.weapon_item = "", "info", None
        self.catalog_results = queue.Queue()
        self.icon_paths, self.icon_images = {}, {}
        self.catalog_loading = False
        self.weapon_status = tk.StringVar()
        self.installed_label = tk.StringVar()
        self.queue_log_position = None
        self.equip_poll = None
        self.speed = tk.StringVar(value="3.5")
        self.sushi_live = tk.BooleanVar()
        self.sushi_installed = False
        self.sushi_speed = tk.StringVar(value=str(self.preferences.get("sushi_speed", "1")))
        self.sushi_applied = None
        self.sushi_sync_job = None
        self.sushi_state = tk.StringVar()
        self.raw_sushi_state = ("", "")
        self.loaded = False
        self.pending = False
        self.status = tk.StringVar(value=translate(self.raw_status, self.language))
        self.build_styles()
        root = ttk.Frame(self, padding=(24, 16, 24, 16))
        root.pack(fill="both", expand=True)
        self.build_header(root)
        self.build_footer(root)
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, pady=(12, 0))
        options_tab = ttk.Frame(self.notebook, padding=16)
        self.weapon_tab = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(options_tab, text=self.tr("一般設定"))
        self.notebook.add(self.weapon_tab, text=self.tr("武器"))
        self.build_options_tab(options_tab)
        self.build_weapon_tab()
        self.bind("<Control-s>", lambda _: self.apply())
        self.bind("<F5>", lambda _: self.refresh())
        self.after(150, self.startup)
        self.after(3000, self.poll_sushi)

    # ----- layout -----
    def build_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(18, 8), font=(UI_FONT, 10))
        style.map("TNotebook.Tab", background=[("selected", ACCENT)], foreground=[("selected", "white")])
        style.configure("TLabel", background=BG, foreground=TEXT, font=(UI_FONT, 10))
        style.configure("Muted.TLabel", foreground=MUTED, font=(UI_FONT, 9))
        style.configure("Heading.TLabel", font=(UI_FONT, 12, "bold"))
        style.configure("Title.TLabel", font=("Segoe UI", 23, "bold"), foreground="#65d5ee")
        style.configure("Badge.TLabel", padding=(10, 4), font=(UI_FONT, 9, "bold"))
        for kind, (background, foreground) in STATUS_COLORS.items():
            style.configure(f"{kind}.Status.TLabel", background=background, foreground=foreground,
                            padding=10, font=(UI_FONT, 10, "bold" if kind != "info" else "normal"))
        style.configure("TButton", font=(UI_FONT, 10), padding=8)
        style.configure("Accent.TButton", background=ACCENT, foreground="white", font=(UI_FONT, 11, "bold"), padding=10)
        style.map("Accent.TButton", background=[("active", "#0a9aa9"), ("disabled", "#2c4a55")])
        style.configure("Pending.TButton", background="#d9a520", foreground="#101b2a", font=(UI_FONT, 11, "bold"), padding=10)
        style.map("Pending.TButton", background=[("active", "#f0bd36")])
        style.configure("Small.TButton", font=(UI_FONT, 9), padding=(8, 3))
        style.configure("Switch.TCheckbutton", background="#20374a", foreground="white", padding=12, font=(UI_FONT, 12))
        style.map("Switch.TCheckbutton", background=[("selected", ACCENT), ("active", "#2b4a61")], foreground=[("selected", "white")])
        style.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT, rowheight=28, font=(UI_FONT, 11), borderwidth=0)
        style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "white")])
        style.configure("Treeview.Heading", background="#20374a", foreground=MUTED, font=(UI_FONT, 9, "bold"), relief="flat")
        style.map("Treeview.Heading", background=[("active", "#2b4a61")])
        style.configure("Category.Toolbutton", background="#20374a", foreground=TEXT, font=(UI_FONT, 9),
                        padding=(8, 3), anchor="center", relief="flat")
        style.map("Category.Toolbutton", background=[("selected", ACCENT), ("active", "#2b4a61")],
                  foreground=[("selected", "white")])
        style.configure("TCheckbutton", background=BG, foreground=TEXT, font=(UI_FONT, 11))
        style.map("TCheckbutton", background=[("active", BG)])

    def build_header(self, root):
        header = ttk.Frame(root)
        header.pack(fill="x")
        titles = ttk.Frame(header)
        titles.pack(side="left")
        ttk.Label(titles, textvariable=self.localized("Dave the Cheater"), style="Title.TLabel").pack(anchor="w")
        ttk.Label(titles, textvariable=self.localized("修改遊戲檔案 · 套用後重新啟動生效"), style="Muted.TLabel").pack(anchor="w")
        self.language_choice = tk.StringVar(value="English" if self.language == "en" else "繁體中文")
        language_box = ttk.Combobox(header, textvariable=self.language_choice, values=("繁體中文", "English"), state="readonly", width=12)
        language_box.pack(side="right", anchor="n")
        language_box.bind("<<ComboboxSelected>>", self.change_language)
        row = ttk.Frame(root)
        row.pack(fill="x", pady=(14, 0))
        ttk.Label(row, textvariable=self.localized("遊戲資料夾")).pack(side="left", padx=(0, 8))
        entry = ttk.Entry(row, textvariable=self.path)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _: self.change_folder())
        ttk.Button(row, textvariable=self.localized("瀏覽…"), command=self.browse).pack(side="right", padx=(8, 0))

    def build_footer(self, root):
        # Packed before the notebook so the shared actions and status are never clipped.
        footer = ttk.Frame(root)
        footer.pack(side="bottom", fill="x", pady=(12, 0))
        self.status_label = ttk.Label(footer, textvariable=self.status, wraplength=760, style="info.Status.TLabel")
        self.status_label.pack(fill="x", pady=(0, 10))
        buttons = ttk.Frame(footer)
        buttons.pack(fill="x")
        self.apply_button = ttk.Button(buttons, textvariable=self.localized("套用設定"), command=self.apply, style="Accent.TButton")
        self.apply_button.pack(side="left", fill="x", expand=True)
        ttk.Button(buttons, textvariable=self.localized("重新讀取"), command=self.refresh).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, textvariable=self.localized("還原全部原始設定"), command=self.restore).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, textvariable=self.localized("啟動遊戲"), command=self.launch_game).pack(side="left", padx=(8, 0))

    def build_options_tab(self, body):
        switches = ttk.Frame(body)
        switches.pack(fill="x")
        for column in (0, 1):
            switches.columnconfigure(column, weight=1, uniform="switch")
        for index, (text, variable) in enumerate([("無限氧氣", self.oxygen), ("無限彈藥", self.ammo),
                                                  ("無敵", self.invincible), ("無限貨物無人機", self.drone)]):
            ttk.Checkbutton(switches, textvariable=self.localized(text), variable=variable, style="Switch.TCheckbutton",
                            command=self.dirty).grid(row=index // 2, column=index % 2, sticky="ew",
                                                     padx=(0 if index % 2 == 0 else 8, 0), pady=(0, 8))
        ttk.Label(body, textvariable=self.localized("無人機開啟後不扣搬運次數；已零次時可能需要先重新潛水。"), style="Muted.TLabel", wraplength=720).pack(anchor="w", pady=(2, 18))
        self.speed_row(body, "水下移動速度倍率", self.speed, 20, ("1", "2", "3.5", "5"),
                       "1 = 原始速度；可輸入 0.1–20。關閉無敵後仍會受傷。")
        self.build_sushi_row(body)
        ttk.Label(body, textvariable=self.localized("彈藥涵蓋共用潛水槍械流程；尚未驗證所有 DLC／特殊武器。\n遊戲更新或其他模組造成版本不同時，工具會拒絕覆寫。"), style="Muted.TLabel", wraplength=720).pack(side="bottom", anchor="w")

    def build_sushi_row(self, body):
        top = ttk.Frame(body)
        top.pack(fill="x")
        ttk.Label(top, textvariable=self.localized("壽司店移動速度倍率（遊戲中即時調整）"), style="Heading.TLabel").pack(side="left")
        self.sushi_badge = ttk.Label(top, textvariable=self.sushi_state, style="Badge.TLabel")
        self.sushi_badge.pack(side="right")
        ttk.Checkbutton(body, textvariable=self.localized("啟用即時壽司店速度（關閉遊戲時套用一次即可）"), variable=self.sushi_live,
                        command=self.dirty).pack(anchor="w", pady=(6, 0))
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(8, 4))
        ttk.Spinbox(row, from_=0.1, to=sushi_speed.MAX_FACTOR, increment=0.25, textvariable=self.sushi_speed, width=7,
                    font=("Segoe UI", 15)).pack(side="left")
        ttk.Label(row, text="×", font=("Segoe UI", 14)).pack(side="left", padx=(6, 16))
        for value in ("1", "1.5", "2", "3"):
            ttk.Button(row, text=f"{value}×", style="Small.TButton", width=5,
                       command=lambda v=value: self.sushi_speed.set(v)).pack(side="left", padx=(0, 6))
        self.sushi_speed.trace_add("write", lambda *_: self.sushi_changed())
        ttk.Label(body, textvariable=self.localized(SUSHI_NOTE), style="Muted.TLabel", wraplength=720).pack(anchor="w", pady=(4, 18))

    def speed_row(self, body, title, variable, maximum, presets, note):
        ttk.Label(body, textvariable=self.localized(title), style="Heading.TLabel").pack(anchor="w")
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(8, 4))
        ttk.Spinbox(row, from_=0.1, to=maximum, increment=0.5, textvariable=variable, width=7, font=("Segoe UI", 15)).pack(side="left")
        ttk.Label(row, text="×", font=("Segoe UI", 14)).pack(side="left", padx=(6, 16))
        for value in presets:
            ttk.Button(row, text=f"{value}×", style="Small.TButton", width=5, command=lambda v=value: variable.set(v)).pack(side="left", padx=(0, 6))
        variable.trace_add("write", lambda *_: self.dirty())
        ttk.Label(body, textvariable=self.localized(note), style="Muted.TLabel", wraplength=720).pack(anchor="w", pady=(4, 18))

    def build_weapon_tab(self):
        body = self.weapon_tab
        top = ttk.Frame(body)
        top.pack(fill="x")
        ttk.Checkbutton(top, textvariable=self.localized("啟用武器選擇器"), variable=self.weapon_enabled, command=self.dirty).pack(side="left")
        self.installed_badge = ttk.Label(top, textvariable=self.installed_label, style="Badge.TLabel")
        self.installed_badge.pack(side="right")
        ttk.Label(body, textvariable=self.localized("潛水途中：選擇武器 → 按「裝備」→ 回到遊戲按一次「切換武器」鍵（預設 Tab）。之後再按即可在魚叉與新槍之間切換。"), style="Muted.TLabel", wraplength=770).pack(anchor="w", pady=(6, 10))
        filters = ttk.Frame(body)
        filters.pack(fill="x")
        ttk.Label(filters, textvariable=self.localized("搜尋")).pack(side="left")
        search = ttk.Entry(filters, textvariable=self.weapon_search)
        search.pack(side="left", fill="x", expand=True, padx=(8, 8))
        ttk.Button(filters, textvariable=self.localized("重新載入清單"), style="Small.TButton", command=self.load_weapons).pack(side="left")
        # Category tabs; rebuilt once the catalogue is loaded.
        self.category_bar = ttk.Frame(body, height=1)
        self.category_bar.pack(fill="x", pady=(10, 0))
        self.category_bar.bind("<Configure>", lambda event: self.layout_category_tabs() if event.width != getattr(self, "_category_width", None) and not setattr(self, "_category_width", event.width) else None)
        self.weapon_search.trace_add("write", lambda *_: self.filter_weapons())
        search.bind("<Down>", lambda _: self.weapon_list.focus_set())
        search.bind("<Return>", lambda _: self.queue_weapon())
        # Bottom-anchored first so the list, not the controls, shrinks in a small window.
        ttk.Label(body, textvariable=self.localized("本篇武器每種只列最高等級（不含 DLC），不需本次攜帶；名稱與圖示取自遊戲本身，搜尋可用中文或英文。"), style="Muted.TLabel", wraplength=770).pack(side="bottom", anchor="w", pady=(6, 0))
        self.weapon_status_label = ttk.Label(body, textvariable=self.weapon_status, wraplength=740, style="info.Status.TLabel")
        self.weapon_status_label.pack(side="bottom", fill="x", pady=(10, 0))
        # Selection bar: icon, name and details of the selected weapon next to the Equip button.
        bar = ttk.Frame(body, style="Card.TFrame", padding=(10, 8))
        bar.pack(side="bottom", fill="x")
        self.queue_button = ttk.Button(bar, textvariable=self.localized("裝備選定武器"), style="Accent.TButton", command=self.queue_weapon)
        self.queue_button.pack(side="right")
        self.preview_image = ttk.Label(bar, background=CARD, anchor="center", width=12)
        self.preview_image.pack(side="left")
        details = ttk.Frame(bar, style="Card.TFrame")
        details.pack(side="left", fill="x", expand=True, padx=(12, 12))
        self.preview_name = ttk.Label(details, background=CARD, foreground=TEXT, font=(UI_FONT, 13, "bold"))
        self.preview_name.pack(anchor="w")
        self.preview_detail = ttk.Label(details, background=CARD, foreground=MUTED, font=(UI_FONT, 9))
        self.preview_detail.pack(anchor="w")
        frame = ttk.Frame(body)
        frame.pack(fill="both", expand=True, pady=10)
        self.weapon_list = ttk.Treeview(frame, columns=("name", "level", "type"), show="tree headings", selectmode="browse", height=6)
        self.weapon_list.column("#0", width=64, minwidth=64, stretch=False, anchor="center")
        for column, source, width, anchor in (("name", "名稱", 380, "w"), ("level", "等級", 70, "center"), ("type", "類型", 130, "w")):
            self.weapon_list.heading(column, text=self.tr(source), anchor=anchor)
            self.weapon_list.column(column, width=width, anchor=anchor, stretch=column == "name")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.weapon_list.yview)
        self.weapon_list.configure(yscrollcommand=scroll.set)
        self.weapon_list.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.weapon_list.bind("<Double-1>", lambda event: self.queue_weapon() if self.weapon_list.identify_row(event.y) else None)
        self.weapon_list.bind("<Return>", lambda _: self.queue_weapon())
        self.weapon_list.bind("<<TreeviewSelect>>", lambda _: (self.remember_weapon(), self.update_preview()))
        self.weapon_message("正在載入本機武器清單…")

    # ----- text and state helpers -----
    @staticmethod
    def read_preferences():
        try:
            value = json.loads((HERE / "gui-preferences.json").read_text("utf8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_preference(self, key, value):
        self.preferences[key] = value
        try:
            (HERE / "gui-preferences.json").write_text(json.dumps(self.preferences), encoding="utf8")
            return True
        except OSError:
            return False

    def tr(self, source):
        return translate(source, self.language)

    def localized(self, source):
        value = tk.StringVar(value=self.tr(source))
        self.localized_texts.append((value, source))
        return value

    def set_status(self, source, kind="info"):
        self.raw_status, self.status_kind = source, kind
        self.status.set(self.tr(source))
        self.status_label.configure(style=f"{kind}.Status.TLabel")

    def weapon_message(self, source, kind="info", item_id=None):
        self.raw_weapon_status, self.weapon_kind, self.weapon_item = source, kind, item_id
        self.render_weapon_message()

    def render_weapon_message(self):
        name = self.weapon_display(self.weapon_item) if self.weapon_item is not None else ""
        self.weapon_status.set(self.tr(self.raw_weapon_status).replace("{name}", name))
        self.weapon_status_label.configure(style=f"{self.weapon_kind}.Status.TLabel")

    def update_installed_badge(self):
        if self.weapon_installed is None:
            self.installed_label.set("")
            self.installed_badge.configure(style="Badge.TLabel", background=BG)
            return
        source = "遊戲檔案：已安裝" if self.weapon_installed else "遊戲檔案：未安裝"
        background, foreground = STATUS_COLORS["success" if self.weapon_installed else "warning"]
        self.installed_label.set(self.tr(source))
        self.installed_badge.configure(background=background, foreground=foreground)

    @staticmethod
    def category_order(row):
        key = row.get("category", "Other")
        return WEAPON_CATEGORIES.index(key) if key in WEAPON_CATEGORIES else len(WEAPON_CATEGORIES)

    def category_label(self, key):
        """Official game name for gun families, panel translation for the rest."""
        if key in CATEGORY_LABELS:
            return self.tr(CATEGORY_LABELS[key])
        row = next((row for row in self.weapon_catalog if row.get("category") == key), None)
        names = row.get("category_names", {}) if row else {}
        return names.get(self.language) or names.get("en") or key

    def build_category_tabs(self):
        for button in self.category_buttons.values():
            button.destroy()
        self.category_buttons = {}
        counts = {}
        for row in self.weapon_catalog:
            counts[row.get("category", "Other")] = counts.get(row.get("category", "Other"), 0) + 1
        keys = [key for key in WEAPON_CATEGORIES if key == "" or counts.get(key)]
        if self.weapon_category.get() not in keys:
            self.weapon_category.set("")
        for index, key in enumerate(keys):
            # A representative icon: the basic ("Normal_") version when there is one.
            rows = [row for row in self.weapon_catalog if key == "" or row.get("category") == key]
            sample = next((row for row in rows if row.get("text_id", "").startswith("Normal_") and row["icon"] in self.icon_paths),
                          next((row for row in rows if row["icon"] in self.icon_paths), None))
            image = self.icon_image(sample, "thumb") if sample and key else None
            count = len(self.weapon_catalog) if key == "" else counts[key]
            button = ttk.Radiobutton(self.category_bar, text=f"{self.category_label(key)}  {count}", image=image or "",
                                     compound="left" if image else "none", value=key, variable=self.weapon_category,
                                     style="Category.Toolbutton", command=self.filter_weapons)
            self.category_buttons[key] = button
        self.layout_category_tabs()

    def layout_category_tabs(self, _event=None):
        """Flow the category tabs into as many rows as the width needs, at their natural widths."""
        self.update_idletasks()
        available = max(self.category_bar.winfo_width(), 400)
        x = y = row_height = 0
        for button in self.category_buttons.values():
            width, height = button.winfo_reqwidth(), button.winfo_reqheight()
            if x and x + width > available:
                x, y = 0, y + row_height + 4
                row_height = 0
            button.place(x=x, y=y)
            x += width + 4
            row_height = max(row_height, height)
        self.category_bar.configure(height=y + row_height)

    @staticmethod
    def error_source(error):
        if isinstance(error, FileNotFoundError):
            return "找不到所需檔案：" + str(error.filename or "")
        if isinstance(error, PermissionError):
            return "無法存取檔案，請確認檔案未被佔用且目前帳號有寫入權限。"
        if isinstance(error, ValueError) and "could not convert string to float" in str(error):
            return "倍率請輸入 0.1 至 20 之間的數字。"
        text = str(error)
        for source, english in TRANSLATIONS.items():
            if english == text:
                return source
        return text

    def error_text(self, error):
        return self.tr(self.error_source(error))

    def change_language(self, _event=None):
        self.language = "en" if self.language_choice.get() == "English" else "zh-TW"
        self.title(self.tr("Dave the Cheater"))
        for variable, source in self.localized_texts:
            variable.set(self.tr(source))
        self.status.set(self.tr(self.raw_status))
        self.render_weapon_message()
        self.notebook.tab(0, text=self.tr("一般設定"))
        self.notebook.tab(1, text=self.tr("武器"))
        self.build_category_tabs()
        self.update_installed_badge()
        self.sushi_state.set(self.tr(self.raw_sushi_state[0]).replace("{value}", self.raw_sushi_state[1]))
        for column, source in (("name", "名稱"), ("level", "等級"), ("type", "類型")):
            self.weapon_list.heading(column, text=self.tr(source))
        self.filter_weapons()
        if not self.save_preference("language", self.language):
            self.set_status("語言偏好無法儲存；本次切換仍已生效。", "warning")

    def dirty(self):
        if self.loaded:
            self.pending = True
            self.apply_button.configure(style="Pending.TButton")
            self.set_status("設定尚未套用。請先關閉遊戲，再按「套用設定」。", "warning")

    def set_state(self, state):
        self.loaded = False
        self.oxygen.set(state["oxygen"])
        self.ammo.set(state["ammo"])
        self.invincible.set(state["invincible"])
        self.drone.set(state["drone"])
        self.weapon_enabled.set(state.get("weapon_enabled", False))
        self.weapon_installed = state.get("weapon_enabled", False)
        self.update_installed_badge()
        self.speed.set(f"{state['speed']:.6g}")
        self.sushi_live.set(state.get("sushi_live", False))
        self.sushi_installed = state.get("sushi_live", False)
        self.sushi_applied = None
        self.loaded = True
        self.pending = False
        self.apply_button.configure(style="Accent.TButton")

    # ----- general actions -----
    def startup(self):
        if self.refresh():
            self.load_weapons()
        else:
            self.weapon_message("請先選擇有效的遊戲資料夾。", "warning")

    def refresh(self):
        try:
            state, _, _ = Controller(self.path.get()).read()
            self.set_state(state)
            self.set_status("已讀取遊戲檔案中的目前設定。")
            return True
        except Exception as error:
            self.loaded = False
            self.weapon_installed = None
            self.update_installed_badge()
            self.set_status("讀取失敗：" + self.error_source(error), "error")
            return False

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
            self.set_status("無法啟動遊戲：" + self.error_source(error), "error")

    def browse(self):
        selected = filedialog.askdirectory(title=self.tr("選擇含有 DaveTheDiver.exe 的資料夾"))
        if selected:
            self.path.set(selected)
            self.change_folder()

    def change_folder(self):
        self.weapon_catalog = []
        self.filter_weapons()
        self.startup()

    def apply(self):
        try:
            state = Controller(self.path.get()).apply({
                "ammo": self.ammo.get(), "invincible": self.invincible.get(), "drone": self.drone.get(),
                "speed": self.speed.get(), "oxygen": self.oxygen.get(), "weapon_enabled": self.weapon_enabled.get(),
                "sushi_live": self.sushi_live.get()})
            self.set_state(state)
            self.set_status("套用成功，已讀回核對。請重新啟動遊戲。", "success")
        except Exception as error:
            self.set_status("未能套用：" + self.error_source(error), "error")

    def restore(self):
        if not messagebox.askyesno(self.tr("還原原始設定"), self.tr("將還原原始水下與壽司店速度、氧氣、彈藥、無人機、受傷規則與武器選擇器。是否繼續？"), parent=self):
            return
        try:
            self.set_state(Controller(self.path.get()).apply({"ammo": False, "invincible": False, "drone": False, "oxygen": False, "speed": 1}))
            self.set_status("已還原全部原始檔案，並完成核對。", "success")
        except Exception as error:
            self.set_status("還原失敗：" + self.error_source(error), "error")

    # ----- live sushi-bar speed -----
    def sushi_message(self, source, kind, value=""):
        self.raw_sushi_state = (source, value)
        self.sushi_state.set(self.tr(source).replace("{value}", value))
        background, foreground = STATUS_COLORS[kind] if source else (BG, TEXT)
        self.sushi_badge.configure(background=background, foreground=foreground)

    def sushi_changed(self):
        self.save_preference("sushi_speed", self.sushi_speed.get())
        if self.sushi_sync_job is not None:
            self.after_cancel(self.sushi_sync_job)
        self.sushi_sync_job = self.after(300, self.sync_sushi)

    def poll_sushi(self):
        self.sync_sushi()
        self.after(3000, self.poll_sushi)

    def sync_sushi(self):
        """Keep the running game's sushi-bar factor equal to the panel value."""
        self.sushi_sync_job = None
        try:
            factor = float(self.sushi_speed.get())
            sushi_speed.slot_value(factor)
        except ValueError:
            self.sushi_message("請輸入 0.1–10", "error")
            return
        label = f"{factor:g}×"
        if not self.sushi_installed:
            self.sushi_message("未安裝" if self.loaded else "", "warning")
            return
        try:
            running = game_running()
        except OSError:
            running = False
        if not running:
            self.sushi_applied = None
            self.sushi_message("遊戲未執行；啟動後自動套用 {value}", "info", label)
            return
        if self.sushi_applied == factor:
            return
        try:
            sushi_speed.set_live(self.path.get(), factor)
            self.sushi_applied = factor
            self.sushi_message("遊戲中已生效：{value}", "success", label)
        except Exception as error:
            # The game may still be starting (GameAssembly.dll not loaded yet); retry on the next poll.
            self.sushi_message(self.error_source(error), "warning")

    # ----- weapons -----
    def row_name(self, row):
        """Official in-game name in the panel language (derived identifier name as fallback)."""
        return row.get("names", {}).get(self.language) or row["name"]

    def weapon_display(self, item_id):
        row = next((row for row in self.weapon_catalog if row["id"] == item_id), None)
        return self.row_name(row) if row else f"#{item_id}"

    def weapon_values(self, row):
        level = f"Lv.{row['level']}" if row["level"] else "—"
        return self.row_name(row), level, self.category_label(row.get("category", "Other"))

    def filter_weapons(self):
        selected = self.selected_weapon_id() or self.preferences.get("weapon")
        words = self.weapon_search.get().casefold().split()
        category = self.weapon_category.get()
        def searchable(row):
            # Match the official name in either language and the data identifier name.
            return " ".join([row["name"], *row.get("names", {}).values()]).casefold()
        self.visible_weapons = sorted((row for row in self.weapon_catalog
                                       if (not category or row.get("category") == category)
                                       and all(word in searchable(row) for word in words)),
                                      key=lambda row: (self.category_order(row), self.row_name(row).casefold(), row["id"]))
        self.weapon_list.delete(*self.weapon_list.get_children())
        for row in self.visible_weapons:
            self.weapon_list.insert("", "end", iid=str(row["id"]), values=self.weapon_values(row),
                                    image=self.icon_image(row, "thumb") or "")
        ids = [row["id"] for row in self.visible_weapons]
        self.select_weapon_index(ids.index(selected) if selected in ids else 0)
        self.update_preview()

    def icon_image(self, row, size):
        """Tk image for a row's icon ("thumb" fits a list row, "full" is the preview), or None."""
        name = row.get("icon")
        if name not in self.icon_paths:
            return None
        if name not in self.icon_images:
            try:
                full = tk.PhotoImage(file=str(self.icon_paths[name]))
            except tk.TclError:
                self.icon_paths.pop(name, None)
                return None
            w, h = full.width(), full.height()
            thumb = full.subsample(max(1, -(-h // 22), -(-w // 56)))
            # Pixel art: enlarge the preview by whole pixels, up to 160x64.
            zoom = max(1, min(160 // max(w, 1), 64 // max(h, 1)))
            self.icon_images[name] = {"thumb": thumb, "full": full.zoom(zoom) if zoom > 1 else full}
        return self.icon_images[name][size]

    def update_preview(self):
        item_id = self.selected_weapon_id()
        row = next((row for row in self.weapon_catalog if row["id"] == item_id), None)
        if row is None:
            self.preview_image.configure(image="", text="")
            self.preview_name.configure(text="")
            self.preview_detail.configure(text="")
            return
        image = self.icon_image(row, "full")
        self.preview_image.configure(image=image or "", text="" if image else self.tr("（無圖示）"),
                                     foreground=MUTED)
        name, level, kind = self.weapon_values(row)
        self.preview_name.configure(text=name)
        detail = f"{kind} · {level}" if level != "—" else kind
        self.preview_detail.configure(text=detail + "  ·  " + self.tr("雙擊或按 Enter 也可裝備"))

    def select_weapon_index(self, index):
        if not self.visible_weapons:
            return
        item = str(self.visible_weapons[index]["id"])
        self.weapon_list.selection_set(item)
        self.weapon_list.focus(item)
        self.weapon_list.see(item)

    def selected_weapon_id(self):
        selection = self.weapon_list.selection()
        return int(selection[0]) if selection else None

    def remember_weapon(self):
        if self.selected_weapon_id():
            self.save_preference("weapon", self.selected_weapon_id())

    def load_weapons(self):
        """Read the catalogue in a worker thread; the first run decompresses a large text bundle."""
        if self.catalog_loading:
            return
        self.catalog_loading = True
        self.weapon_message("正在載入本機武器清單…")
        game = self.path.get()

        def work():
            try:
                catalog = weapons.extract_catalog(game, names_cache=NAMES_CACHE)
            except Exception as error:
                self.catalog_results.put((game, None, {}, error))
                return
            try:
                icons = weapon_icons.extract_icons(game, [row["icon"] for row in catalog], ICON_CACHE)
            except Exception:
                icons = {}  # icons are optional
            self.catalog_results.put((game, catalog, icons, None))
        threading.Thread(target=work, daemon=True).start()
        self.after(100, self.finish_load_weapons)

    def finish_load_weapons(self):
        try:
            game, catalog, icons, error = self.catalog_results.get_nowait()
        except queue.Empty:
            self.after(100, self.finish_load_weapons)
            return
        self.catalog_loading = False
        if game != self.path.get():
            self.load_weapons()  # the folder changed while loading
            return
        if error is None:
            self.weapon_catalog = catalog
            self.icon_paths, self.icon_images = icons, {}
            self.build_category_tabs()
            self.filter_weapons()
            self.weapon_message("已載入本機武器清單。潛水中選擇武器後按「裝備」。")
        else:
            self.weapon_catalog = []
            self.filter_weapons()
            self.weapon_message("無法載入武器清單：" + self.error_source(error), "error")

    def queue_weapon(self):
        item_id = self.selected_weapon_id()
        if item_id is None:
            self.weapon_message("請先在清單中選擇武器。", "warning")
            return
        self.queue_button.configure(state="disabled")
        self.weapon_message("正在檢查遊戲並更新武器選擇…")
        self.update_idletasks()
        try:
            if not self.weapon_installed:
                raise ValueError(self.tr("請先關閉遊戲並啟用武器選擇器，再重新啟動遊戲。"))
            position = weapons.log_position()
            weapons.arm_live(self.path.get(), item_id, {row["id"] for row in self.weapon_catalog})
            self.queue_log_position = position
            self.weapon_message("已排入「{name}」。回到遊戲按一次「切換武器」鍵（預設 Tab）即可裝備。", "warning", item_id)
            self.start_equip_poll(item_id)
        except Exception as error:
            self.weapon_message(self.error_source(error), "error")
        finally:
            self.queue_button.configure(state="normal")

    def start_equip_poll(self, item_id):
        if self.equip_poll is not None:
            self.after_cancel(self.equip_poll)
        self.equip_poll = self.after(EQUIP_POLL_MS, self.poll_equip, item_id, EQUIP_POLL_LIMIT)

    def poll_equip(self, item_id, remaining):
        self.equip_poll = None
        try:
            events = weapons.equip_events(self.queue_log_position)
        except OSError:
            events = []
        if events:
            self.weapon_message("已在遊戲中裝備「{name}」。再按「切換武器」鍵可在魚叉與新槍之間切換。", "success", item_id)
        elif remaining > 1:
            self.equip_poll = self.after(EQUIP_POLL_MS, self.poll_equip, item_id, remaining - 1)
        else:
            self.weapon_message("三分鐘內遊戲記錄未出現裝備動作。「{name}」仍在排隊中，請在遊戲中按「切換武器」鍵（預設 Tab）。", "warning", item_id)


if __name__ == "__main__":
    Panel().mainloop()
