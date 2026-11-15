# Dave the Cheater

A Windows GUI for a supported Steam installation of **DAVE THE DIVER**, using Python, Tkinter and the standard library. No downloaded trainers or runtime injection.

## GUI preview

![Dave the Cheater GUI with English controls, four feature switches, swimming and sushi-bar speed multipliers with presets, status bar and action buttons](docs/images/gui.png)

The top-right language selector switches between **English** and **繁體中文**.

## Features

- Swimming speed multiplier, 0.1x to 20x.
- Sushi bar movement speed multiplier, 0.1x to 10x, adjustable live while the game runs (Dave's walking, running and tired speed while serving).
- Infinite oxygen, infinite ammo, invincibility and infinite cargo-drone switches.
- Underwater weapon selector: equip any base-game weapon mid-dive from a searchable list.
- Traditional Chinese / English UI with remembered language preference.
- Steam launch button, colour-coded status bar, original-file restore, running-game checks, version validation and failed-write rollback.
- Keyboard shortcuts: **Ctrl+S** applies settings, **F5** reloads them from the game files.

**Close the game before applying settings and restart afterward.** Switches do not modify files until Apply settings is clicked.

## Setup

Requires Windows, Python 3.10+ with Tkinter, Steam, and your own game installation. No pip packages are needed.

This tool supports one specific build. The observed title screen reported `v1.0.6.2132.steam`; exact SHA-256 checks determine compatibility. Updated or otherwise modified files are rejected.

Game binaries, modified game files, backups, preferences and reports are not distributed in this repository. For a fresh checkout, prepare ignored local backups from your own unmodified supported installation:

```powershell
python prepare_backups.py --game 'D:/SteamLibrary/steamapps/common/Dave the Diver'
```

Preparation validates both originals before creating backups. It does not modify game files. Existing verified backups are retained. Unsupported or already-modified originals are rejected.

Then double-click `Start-Dave-Controls.cmd`, or run:

```powershell
python control_panel.py
```

## How to use

1. **Close DAVE THE DIVER completely.** Steam can remain open.
2. Open **Start-Dave-Controls.cmd**, or run `python control_panel.py`.
3. Check the **Game folder** path; click **Browse…** to select the folder containing `DaveTheDiver.exe` if it differs.
4. Choose **English** or **繁體中文** from the top-right language selector.
5. Enable or disable **Infinite oxygen**, **Infinite ammo**, **Invincible** and **Infinite cargo drone**. A checked, teal button means enabled.
6. Enter a **Swimming speed multiplier** such as `3.5`, or click a preset (`1×`, `2×`, `3.5×`, `5×`). `1` restores normal swimming speed; the allowed range is `0.1`–`20`. To use the sushi bar speed, tick **Enable live sushi bar speed** before applying.
7. Click **Apply settings**. It turns amber while there are unapplied changes. Wait for the green success message confirming the files were written and checked.
8. Click **Launch game** to start through Steam, then test the changes in-game.

Editing a field or switch does not apply it automatically. If you launch with unapplied changes, the GUI asks whether to use the previously applied settings. A running game blocks file changes.

The status bar above the buttons is shared by both tabs: green means success, amber means unapplied changes or a waiting step, red means an error. **Reload** rereads the actual file settings. **Restore all defaults** restores the original game files, disables every patch including oxygen and the weapon selector, and returns swimming speed to `1`.

If ammo or drone uses are already zero, you may need to refill or start a new dive first. See [繁體中文操作說明](GUI-使用說明.md) for the Chinese guide.

## Scope and verification

### Weapons tab

Equipping a weapon mid-dive and swapping to it has been **tested in game** on the supported build. The list comes from your own local data: base-game guns, harpoons, harpoon heads and melee weapons, one entry per weapon at its highest level, including weapons not carried on the current dive; DLC weapons are not currently included. It loads automatically in the background when the panel opens. Weapon names are the game's own official names in the panel language (Traditional Chinese or English), read from your local text tables; search accepts either language. Each row also shows the weapon's in-game icon, and the bar above the status line shows the selected weapon's larger icon next to **Equip selected weapon**. Names and icons come from your own game files: the first load takes about ten seconds, after which they are cached in the ignored local file `weapon-names-cache.json` and folder `weapon-icons/`. Harpoon guns and the dive knife have no item icon in the game data, so they are listed without one.

1. With the game closed, open **Weapons**, tick **Enable weapon selector** and click **Apply settings**. The badge on the right shows whether the selector is installed in the game files.
2. Start the game and begin a dive.
3. Pick a category tab or use **Search**, then click **Equip selected weapon** (or double-click it, or press Enter). The tabs group guns by the game's own families (Underwater Rifle, Triple Axel, Sniper Rifle, Tranquilizer Gun / Hush Darts, Grenade Launcher, Sticky Bomb Gun, Net Gun, Ice Gun), followed by harpoon guns, harpoon tips and melee weapons, each with a count.
4. Return to the game and press your **weapon-switch key** (Tab by default) once to equip it, then again to swap between the harpoon and the new gun.

After queueing, the panel watches the game's `Player.log` for up to three minutes and turns the weapon status green once the game has loaded the weapon. Your last selected weapon is remembered.

Only the first key press after each queue equips; every other press is the game's normal harpoon/gun swap. Queueing writes only a four-byte weapon ID into unused read/write memory; the game's own input handler performs the equip on its thread. No game code is modified at runtime, and no remote thread or external mod loader is used. Disable the selector and apply while the game is closed to restore the original file.

Swimming speed does not adjust sushi-restaurant walking speed; that is the separate sushi bar multiplier. After **Enable live sushi bar speed** has been applied once with the game closed, the multiplier box takes effect immediately while the game runs: the panel writes only a four-byte value into unused read/write memory, and the badge shows **Active in game**. The game itself always starts at 1×; while the panel is open it reapplies your remembered value automatically after each launch. It scales the walk, run and tired multipliers Dave uses in the main sushi bar, the event variant and the Jungle DLC restaurant; it does not change hired staff, customers or village walking. It is statically verified and file-tested, but not yet confirmed in game. Ammo targets shared diving-gun logic and its inlined decrement; coverage is not verified for every DLC, special weapon or minigame. Empty guns may need one refill.

The cargo-drone option stops four identified use-count decrements in net/cargo interactions. It does not unlock the drone or refill empty counts; a new dive may be needed. Invincibility targets damage immunity and hit damage; scripted deaths remain unverified.

The user reported that the oxygen patch works. Other effects have not been comprehensively measured. File-level and GUI tests do not establish complete in-game coverage.

## Tests

```powershell
python -m unittest discover -v
```

Source checks need no game files. File-integration tests skip unless original backups are present. Integration tests use temporary fixtures instead of the real installation; they cover patch combinations, multiplier bounds, version mismatch, game-running guards, restore and rollback.

## Files

For parameter discovery, adding features, and remapping after game updates, read [AGENTS.md](AGENTS.md).

- `control_panel.py`: GUI and guarded file updates.
- `gui_language.py`: translations.
- `inspect_dave.py`: UnityFS/LZ4/Addressables/serialized-asset inspection and rebuilding.
- `prepare_backups.py`: validate and prepare local original backups.
- `weapon_selector.py`: experimental underwater weapon selector and local catalogue reader.
- `test_source.py`, `test_control_panel.py`: source and file-integration tests.

Unofficial tool, not affiliated with the game's developer or publisher. No game assets or full game binaries are included.
