"""Supported-build profile and Steam game discovery. No GUI or game-file writes."""
import hashlib
import os
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
STEAM_APP_ID = 1868140

# Exact original hashes are the compatibility authority; see AGENTS.md.
NATIVE_HASH = "ed213c248bf53e62a3bf2223ff3f89467a6edff6cec7d3ea921ada6a6e2a6600"
BUNDLE_HASH = "9800d47efc3d4106b1207530c92c0be6ecdda4647c378e4fc3d7aa662d93ea7e"
BUNDLE_NAME = "7314e4d32b10a297b1b8f2c2d3fac26f.bundle"
NODE_NAME = "CAB-3fc8e257bbfa28c753fb863c50d033ff"
SPEED_OFFSET = 7500
# (feature, raw DLL file offset, original bytes, enabled bytes)
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
NATIVE_BACKUP = HERE / "resources-upgrade/original/GameAssembly.dll"
BUNDLE_BACKUP = HERE / "swim-1.5x/original" / BUNDLE_NAME
BUNDLE_RELATIVE = Path("DaveTheDiver_Data/StreamingAssets/aa/StandaloneWindows64") / BUNDLE_NAME


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _vdf_values(text, key):
    """Return the quoted values of `key` in a Valve KeyValues text file."""
    pattern = r'"%s"\s+"((?:[^"\\]|\\.)*)"' % re.escape(key)
    return [re.sub(r"\\(.)", r"\1", value) for value in re.findall(pattern, text, re.IGNORECASE)]


def steam_roots():
    """Likely Steam installation folders, most specific first."""
    roots = []
    try:
        import winreg
        for hive, key, name in [
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        ]:
            try:
                with winreg.OpenKey(hive, key) as handle:
                    roots.append(Path(winreg.QueryValueEx(handle, name)[0]))
            except OSError:
                pass
    except ImportError:
        pass
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        if os.environ.get(variable):
            roots.append(Path(os.environ[variable]) / "Steam")
    return roots


def library_folders(steam_root):
    steam_root = Path(steam_root)
    folders = [steam_root]
    try:
        text = (steam_root / "steamapps/libraryfolders.vdf").read_text("utf-8", "replace")
    except OSError:
        return folders
    folders.extend(Path(value) for value in _vdf_values(text, "path"))
    return folders


def find_game(roots=None):
    """Locate the game through Steam library folders and its app manifest; None if absent."""
    seen = set()
    for root in steam_roots() if roots is None else roots:
        for library in library_folders(root):
            key = os.path.normcase(str(library))
            if key in seen:
                continue
            seen.add(key)
            manifest = library / "steamapps" / f"appmanifest_{STEAM_APP_ID}.acf"
            try:
                names = _vdf_values(manifest.read_text("utf-8", "replace"), "installdir")
            except OSError:
                continue
            # A manifest's installdir must be a single folder name under steamapps/common.
            if not names or Path(names[0]).name != names[0] or names[0] in ("", ".", ".."):
                continue
            game = library / "steamapps/common" / names[0]
            if (game / "GameAssembly.dll").is_file():
                return game
    return None
