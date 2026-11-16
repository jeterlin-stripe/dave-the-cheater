"""Platform support: Windows and Linux/SteamOS (Steam Deck desktop mode, game under Proton).

Under Proton the game is the same Windows build (same files and hashes), so all
file patches are identical. Only the operating-system plumbing differs:

* the game folder is found through Steam's `libraryfolders.vdf` (SD cards too);
* Player.log lives in the Proton prefix (`compatdata/1868140/pfx/...`);
* the game process is the Wine process whose argv[0] ends in DaveTheDiver.exe;
* live writes go through /proc/<pid>/mem at the address where GameAssembly.dll
  is mapped, after the same exact-code verification as on Windows.
"""
import os
import re
import subprocess
from pathlib import Path

APP_ID = 1868140
GAME_DIR = "Dave the Diver"
EXE = "davethediver.exe"
IS_WINDOWS = os.name == "nt"
LOG_TAIL = Path("AppData/LocalLow/nexon/DAVE THE DIVER/Player.log")
PTRACE_HELP = ("SteamOS 阻擋了記憶體存取。請在 Konsole 執行：sudo sysctl kernel.yama.ptrace_scope=0"
               "（重新開機後恢復），再重試。")


# ----- locating the game -----
def steam_roots(home=None, environ=None):
    """Candidate Steam installation folders for this platform."""
    home = Path(home or Path.home())
    environ = os.environ if environ is None else environ
    if IS_WINDOWS:
        roots = [Path(environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam"]
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                roots.insert(0, Path(winreg.QueryValueEx(key, "SteamPath")[0]))
        except OSError:
            pass
        return roots
    return [home / ".local/share/Steam", home / ".steam/steam", home / ".steam/root",
            home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"]


def library_folders(root):
    """Library paths listed in <root>/steamapps/libraryfolders.vdf (plus the root itself)."""
    found = [Path(root)]
    try:
        text = (Path(root) / "steamapps/libraryfolders.vdf").read_text("utf8", "replace")
    except OSError:
        return found
    for value in re.findall(r'"path"\s+"((?:[^"\\]|\\.)*)"', text):
        path = Path(value.replace("\\\\", "\\"))
        if path not in found:
            found.append(path)
    return found


def find_game(roots=None, fallback=None):
    """First installed DAVE THE DIVER folder (one containing GameAssembly.dll), else `fallback`."""
    for root in roots if roots is not None else steam_roots():
        for library in library_folders(root):
            game = library / "steamapps/common" / GAME_DIR
            if (game / "GameAssembly.dll").is_file():
                return game
    return fallback


def player_log(game):
    """The game's Player.log: the Windows profile, or the Proton prefix of the game's library."""
    if IS_WINDOWS:
        return Path.home() / LOG_TAIL
    steamapps = Path(game).resolve().parent.parent
    return steamapps / "compatdata" / str(APP_ID) / "pfx/drive_c/users/steamuser" / LOG_TAIL


def launch_game():
    uri = f"steam://rungameid/{APP_ID}"
    if IS_WINDOWS:
        os.startfile(uri)
    else:
        subprocess.Popen(["xdg-open", uri], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


# ----- Linux processes -----
def _argv0(cmdline):
    return cmdline.split(b"\0", 1)[0].decode("utf8", "replace")


def game_pids(proc="/proc"):
    """PIDs whose program is DaveTheDiver.exe (Wine shows the Windows path as argv[0])."""
    pids = []
    for entry in Path(proc).iterdir():
        if not entry.name.isdigit():
            continue
        try:
            program = _argv0((entry / "cmdline").read_bytes())
        except OSError:
            continue  # exited, or not ours
        if program.replace("\\", "/").rsplit("/", 1)[-1].casefold() == EXE:
            pids.append(int(entry.name))
    return pids


def module_mappings(maps_text, name="gameassembly.dll"):
    """(start address, path) of every offset-0 mapping of a file called `name` in /proc/<pid>/maps."""
    found = []
    for line in maps_text.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6 or int(parts[2], 16) != 0:
            continue
        path = parts[5].strip()
        if path.replace("\\", "/").rsplit("/", 1)[-1].casefold() == name:
            found.append((int(parts[0].split("-")[0], 16), path))
    return found


def _same_header(memory_header, disk_header):
    """PE headers equal apart from OptionalHeader.ImageBase (a loader may update it on relocation)."""
    if len(memory_header) != len(disk_header) or memory_header[:2] != b"MZ":
        return False
    pe = int.from_bytes(disk_header[60:64], "little")
    image_base = slice(pe + 24 + 24, pe + 24 + 32)
    a, b = bytearray(memory_header), bytearray(disk_header)
    a[image_base] = b[image_base] = bytes(8)
    return a == b


def linux_live_write(game, site_rva, site_length, site_ok, target_rva, payload, not_installed,
                     proc="/proc", open_mem=None):
    """Same contract as weapon_selector.live_write, through /proc/<pid>/mem."""
    game = Path(game).resolve()
    pids = game_pids(proc)
    if len(pids) != 1:
        raise ValueError("Start one DAVE THE DIVER game process first")
    pid = pids[0]
    dll = game / "GameAssembly.dll"
    mappings = module_mappings((Path(proc) / str(pid) / "maps").read_text("utf8", "replace"))
    if not mappings:
        raise ValueError("GameAssembly.dll is not loaded")
    with open(dll, "rb") as stream:
        disk_header = stream.read(0x400)
    opener = open_mem or (lambda: open(Path(proc) / str(pid) / "mem", "r+b", buffering=0))
    try:
        mem = opener()
    except PermissionError as error:
        raise PermissionError(PTRACE_HELP) from error
    with mem:
        def read(address, count):
            mem.seek(address)
            data = mem.read(count)
            if data is None or len(data) != count:
                raise OSError("Incomplete memory read")
            return data

        def matches(start, path):
            try:
                if Path(path).resolve() == dll:
                    return True
            except OSError:
                pass
            # Inside Steam's container the mapped path may differ; compare the loaded PE header instead.
            return _same_header(read(start, len(disk_header)), disk_header)
        try:
            bases = [start for start, path in mappings if matches(start, path)]
            if len(set(bases)) != 1:
                raise ValueError("Running game does not match the selected installation")
            base = bases[0]
            if not site_ok(read(base + site_rva, site_length)):
                raise ValueError(not_installed)
            mem.seek(base + target_rva)
            mem.write(payload)
        except PermissionError as error:
            raise PermissionError(PTRACE_HELP) from error
        if read(base + target_rva, len(payload)) != payload:
            raise OSError("Live write verification failed")


def linux_game_running(proc="/proc"):
    return bool(game_pids(proc))
