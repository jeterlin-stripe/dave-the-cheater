# Dave the Cheater

A Windows GUI for a supported Steam installation of **DAVE THE DIVER**, using Python, Tkinter and the standard library. No downloaded trainers or runtime injection.

## Features

- Swimming speed multiplier, 0.1x to 20x.
- Infinite ammo, invincibility and infinite cargo-drone switches.
- Traditional Chinese / English UI with remembered language preference.
- Steam launch button, highlighted success status, original-file restore, running-game checks, version validation and failed-write rollback.
- Preserve the current oxygen patch when applying other controls.

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

Select your game folder, choose settings, click Apply settings, then Launch game. The language selector is at the top right. See [Traditional Chinese instructions](GUI-使用說明.md).

## Scope and verification

Swimming speed does not adjust sushi-restaurant walking speed. Ammo targets shared diving-gun logic and its inlined decrement; coverage is not verified for every DLC, special weapon or minigame. Empty guns may need one refill.

The cargo-drone option stops four identified use-count decrements in net/cargo interactions. It does not unlock the drone or refill empty counts; a new dive may be needed. Invincibility targets damage immunity and hit damage; scripted deaths remain unverified.

The user reported that the oxygen patch works. Other effects have not been comprehensively measured. File-level and GUI tests do not establish complete in-game coverage.

## Tests

```powershell
python -m unittest discover -v
```

Source checks need no game files. File-integration tests skip unless original backups are present. Integration tests use temporary fixtures instead of the real installation; they cover patch combinations, multiplier bounds, version mismatch, game-running guards, restore and rollback.

## Files

- `control_panel.py`: GUI and guarded file updates.
- `gui_language.py`: translations.
- `inspect_dave.py`: UnityFS/LZ4/Addressables/serialized-asset inspection and rebuilding.
- `prepare_backups.py`: validate and prepare local original backups.
- `test_source.py`, `test_control_panel.py`: source and file-integration tests.

Unofficial tool, not affiliated with the game's developer or publisher. No game assets or full game binaries are included.
