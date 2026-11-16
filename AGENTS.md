# Dave the Cheater: maintenance and parameter-discovery guide

Read this guide before adding a feature or changing compatibility data. It records how the existing parameters were located, including unsuccessful approaches, and how to remap them after a game update.

## Project boundaries

- This is a Windows Steam, Python-standard-library tool, also supported on Linux/Steam Deck desktop mode with the game under Proton (`steam_platform.py`). The GUI uses Tkinter. General controls edit files while the game is closed. The user explicitly requested arbitrary underwater weapon selection: the experimental selector adds a closed-game, build-specific input adapter and a narrowly scoped live four-byte item selection. The user also explicitly requested a sushi-bar speed multiplier adjustable while the game runs, and then asked for **all** multipliers (swimming speed, backpack capacity, sushi bar) to change on the fly without relaunching; each uses a closed-game patch plus a four-byte live data write (`weapon_selector.live_write`) to its own slot. Neither injects a DLL or creates a remote thread. Do not generalize these exceptions into unrestricted process edits.
- Keep Traditional Chinese and English UI strings in sync through `gui_language.py`.
- GUI layout (2026-11-15 rework): shared footer with the status bar and Apply/Reload/Restore/Launch buttons, packed before the notebook so it is never clipped; General tab has four switches (oxygen is now a normal switch) and speed presets; Weapons tab auto-loads the catalogue into a searchable, type-filtered `ttk.Treeview` and auto-polls `Player.log` after queueing. `gui-preferences.json` stores `language` and the last selected `weapon`.
- Keep file validation, original backups, running-game checks, read-back verification and rollback. Do not bypass them to make a new build appear supported.
- Never commit game binaries, extracted assets, modified bundles, original backups, user preferences, installation reports or credentials. `.gitignore` is an allowlist; explicitly allow new source/documentation files when necessary.
- Build and inspect copies first. Installation and gameplay tests are separate from successful parsing, writing and launching.
- Preserve unrelated switches and the current oxygen-patch state when applying a feature. Restore must produce the exact original files.
- The default branch is `master`.

## Where the implementation lives

| File | Responsibility |
| --- | --- |
| `control_panel.py` | Supported hashes, patch sites, swimming asset identification, GUI, validation and guarded writes |
| `inspect_dave.py` | Addressables lookup, UnityFS/LZ4 reading and rebuilding, serialized type trees, metadata enum analysis |
| `prepare_backups.py` | Local original-backup preparation; never downloads game files |
| `gui_language.py` | GUI translations, including application-generated error messages |
| `test_control_panel.py` | Local-backup-dependent integration tests using temporary fixtures |
| `test_source.py` | Checks that do not need game files |
| `live_multipliers.py` | Live swimming-speed and backpack-capacity hooks (call sites + leaf routines in int3 padding reading data slots) |
| `test_live_multipliers.py` | Routine layout, control-flow targets, slots, partial-install rejection and simulated live writes |
| `steam_platform.py` | Windows vs. Linux/Steam Deck: game discovery via `libraryfolders.vdf`, `/proc` process detection, `/proc/<pid>/mem` live writes, Proton `Player.log`, launching |
| `test_steam_platform.py` | Fake `/proc` and simulated process memory tests for the Linux backend |
| `sushi_speed.py` | Live sushi-bar movement multiplier: in-place rewrite of `DaveMoveValue.get_speedMultiplier` reading a data slot |
| `test_sushi_speed.py` | Encoding, branch-target, unwind, slot and simulated live-write tests for the sushi-bar patch |
| `weapon_icons.py` | Crops weapon icons from the local sprite atlas into ignored PNGs for the GUI |
| `test_weapon_icons.py` | PNG encoder, Tk loading and icon-cache tests |
| `weapon_selector.py` | Experimental local weapon catalogue, input adapter and constrained live selection |
| `test_weapon_selector.py` | Adapter encoding, control-flow, alignment and rejection tests |

`inspect_dave.py --movement` and `--build-copy` investigate **DaveMoveDataData**, the earlier walking-related candidate. They are not the swimming-speed implementation used by the GUI. Do not mistake those commands for a verified swimming patch.

## Establish the build and clean originals first

The original investigation found the game through Steam's `libraryfolders.vdf` and `appmanifest_1868140.acf`. The Steam app ID is **1868140**. Do not assume a particular drive or a developer's personal path.

Relevant installation files:

```text
GameAssembly.dll
DaveTheDiver_Data/il2cpp_data/Metadata/global-metadata.dat
DaveTheDiver_Data/StreamingAssets/aa/catalog.json
DaveTheDiver_Data/StreamingAssets/aa/StandaloneWindows64/*.bundle
```

This is Unity IL2CPP: gameplay methods are compiled native code in `GameAssembly.dll`, with names and structural information in `global-metadata.dat`. They are not editable C# DLLs or plain configuration settings.

The observed title-screen version was `v1.0.6.2132.steam`; the inspected bundles reported Unity `6000.0.52f1`. Exact original-file hashes are the compatibility authority:

| Original | SHA-256 |
| --- | --- |
| `GameAssembly.dll` | `ed213c248bf53e62a3bf2223ff3f89467a6edff6cec7d3ea921ada6a6e2a6600` |
| Supported swimming bundle | `9800d47efc3d4106b1207530c92c0be6ecdda4647c378e4fc3d7aa662d93ea7e` |

Record the Steam build ID, displayed version, metadata version, Unity version and clean hashes for every newly investigated build. A displayed version alone does not establish compatibility.

## Discovery workflow for another feature

1. Describe the exact action to alter, its resource, and the intended limit. For example, prevent normal ammunition subtraction rather than assign a very large capacity.
2. Search identifiers in the metadata string table for resource names and related verbs: `Ammo`, `Bullet`, `Breath`, `Oxygen`, `Drone`, `Decrease`, `Consume`, `SuccessInteract`, `SetHitHP`.
3. Associate names with declaring types, methods, fields, parameters and tokens. Similar names can belong to enemies, minigames, UI widgets or other scenes.
4. Follow actual references. Asset field names alone do not prove the active player uses the asset. Method names alone do not prove every caller goes through that method.
5. Prefer a serialized asset change if it controls the intended behavior. Otherwise map the relevant native method and inspect its instructions and callers.
6. Check for compiler inlining, alternate equipment paths, initialization resets, save synchronization, existing-zero resource counts and UI refresh code.
7. Build an offline candidate with exact original-byte guards and a diff restricted to the intended fields/instructions.
8. Verify the candidate, add independent on/off controls and translations, then test gameplay before claiming the feature works.

### Reading the current metadata layout

The inspected metadata has magic `0xFAB11BAF` and version **31**. The investigation read the header as little-endian uint32 values (`h = struct.unpack_from('<64I', data)`). The following are indexes into that uint32 array, not byte offsets:

| Header indexes | Table |
| --- | --- |
| `h[6], h[7]` | UTF-8 identifier string table offset and size |
| `h[12], h[13]` | Method definitions offset and size |
| `h[16], h[17]` | Field default-value records offset and size |
| `h[18], h[19]` | Field/parameter default-value data offset and size |
| `h[24], h[25]` | Field definitions offset and size |
| `h[32], h[33]` | Nested-type indices offset and size |
| `h[40], h[41]` | Type definitions offset and size |

For this build, type records are 88 bytes (`<16i8H2I`), method records 36 bytes, and field records 12 bytes. In a type record, field start is index 8, method start 9, nested-type start 12, method count 16, field count 18 and nested-type count 20. In a method record, name index is at byte 0, declaring-type index at byte 4 and token at byte 24.

Resolve identifier string offsets relative to the string table. Do not search all printable bytes and assume each match is an identifier: the first attempt produced huge concatenated literal strings and irrelevant results.

Default enum integers can use compressed signed encoding in version 31. The one-byte values encountered for the movement enum used zigzag encoding: even `n` means `n / 2`; odd `n` means `-(n / 2 rounded down) - 1`. The current helper intentionally rejects multibyte cases. Do not read these values as raw four-byte integers or generalize this small decoder to every default-value type.

All record widths, header layouts and token associations must be revalidated after an update. Runtime type indexes are not interchangeable with type-definition indexes. For nested compiler-generated classes, use the actual nested-type table to recover the parent.

## Asset-based parameters: swimming speed

### Follow the resource graph

1. Parse `catalog.json`. Its base64 key, bucket and entry tables map asset keys/internal IDs to dependency bundles. Some assets are keyed by GUID: search both human-readable keys **and internal IDs**.
2. Current entry records are seven little-endian int32 values, after the entry-count header. Dependency indexes refer to key buckets, not directly to entry records. Recursively follow dependencies with a visited set.
3. Decompress the candidate UnityFS bundle with `bundle_files()`. The reader handles raw/LZ4 blocks; `write_bundle()` currently rebuilds an uncompressed bundle.
4. Inspect serialized types and objects with `serialized_summary()` and `read_object_fields()`. The object reader retains decoded field offsets.
5. Follow a Unity `PPtr`: `m_FileID` selects an external serialized file using a one-based index; `m_PathID` selects the object in that file. A zero file ID means a local object reference.
6. Match the external CAB node name against dependency bundle contents and verify the referenced object's type and fields.

Useful commands:

```powershell
python inspect_dave.py --game 'D:/SteamLibrary/steamapps/common/Dave the Diver' --find PlayerGroup.prefab
python inspect_dave.py --bundle 'PATH/TO/CANDIDATE.bundle'
python inspect_dave.py --bundle 'PATH/TO/CANDIDATE.bundle' --extract 'NEW-SCRATCH-DIRECTORY'
python inspect_dave.py --serialized 'PATH/TO/EXTRACTED-CAB-FILE'
```

`--extract` requires a new output directory. The asset reader currently targets serialized format 22+ as found in this installation; it is not a universal Unity parser.

### The supported swimming reference chain

```text
Assets/Contents/PlayContents/Common/Prefabs/Player/PlayerGroup.prefab
  -> PlayerCharacter.moveProperty
  -> external file ID 29
  -> CAB-3fc8e257bbfa28c753fb863c50d033ff
  -> path ID 3307243921344500234
  -> PlayerMoveProperty.moveSpeed
```

Current identifiers, which are build-specific:

- Owning bundle: `7314e4d32b10a297b1b8f2c2d3fac26f.bundle`.
- Node: `CAB-3fc8e257bbfa28c753fb863c50d033ff`.
- Field offset: **7500 in the decompressed serialized node**, not in the compressed bundle.
- Original value: float32 approximately **2.3** (`2.299999952316284`).

Multiply the original float, never the currently patched float. Build from the original node, replace only these four bytes, rebuild, reread and compare all decoded nodes. Other fields such as deceleration, thresholds and village buffs must remain unchanged.

The earlier `DaveMoveDataData.asset` candidate contained `Tired`, `Walk`, `Run`, `Crawl` multipliers `0.6`, `0.9`, `1.2`, `0.3`. The user reported no apparent walking or swimming improvement after that patch; it was restored. Finding meaningful names and successfully loading a rebuilt bundle were not sufficient evidence of the intended effect.

The swimming bundle's original Addressables request options reported `m_Crc: 0` and `m_UseUWRForLocalBundles: false`. Recheck these settings on a new build. Do not assume its catalog hash or CRC behavior remains unchanged, or disable integrity checks as a shortcut.

## Native methods: map metadata tokens to PE file offsets

The original investigation used a small local Python PE parser and an already-installed `objdump` for static disassembly. The native-discovery snippets were scratch work; this repository does **not** currently include a general automatic native remapper.

1. Parse the PE headers and section table. Record the image base and each section's virtual address, raw-data offset and raw-data size.
2. Find the null-terminated `Assembly-CSharp.dll` module name in the DLL and resolve its virtual address through the section mapping.
3. Find pointers to that string, then validate a candidate IL2CPP code-generation-module structure. For the inspected x64 build it had a name pointer at +0, a uint32 method-pointer count at +8 and a method-pointer-array pointer at +16.
4. The candidate in the original file was at **raw file offset 101375760** and reported **139507** method pointers. These are historical evidence, not reusable update signatures.
5. A MethodDef token's low 24 bits provide its one-based row. For the correct assembly/module, read method pointer `[row - 1]` and convert its VA to a raw PE file offset.
6. Confirm the method name, declaring type, signature, executable section, instruction boundaries and relevant field accesses. Generic/shared functions and identical-code folding can make multiple tokens point to one body; changing a shared body may affect unrelated types.

For an address inside a section:

```text
RVA = VA - image_base
raw_offset = section.raw_offset + (RVA - section.virtual_address)
```

Only map addresses that actually have raw file data. Never confuse a VA, RVA, raw DLL offset, managed field offset or serialized-node offset.

Example static disassembly command; derive addresses for the current build first:

```powershell
objdump -d -M intel --start-address=0xCURRENT_VA --stop-address=0xCURRENT_END GameAssembly.dll
```

Names and signatures narrow the search; disassembly establishes what the code changes. Preserve branch conditions, stack/register conventions and downstream state/UI synchronization.

### Current native patch map (historical supported build only)

The authoritative implementation is `PATCHES` in `control_panel.py`. Values below are raw **DLL file offsets**, in decimal. Always check the original SHA and exact preimage bytes before using them.

| Feature/site | Offset | Original bytes | Enabled bytes |
| --- | ---: | --- | --- |
| Oxygen delta addition in `PlayerBreathHandler.ChangeOxygenValue` | 24359754 | `f3 44 0f 58 c6` | five `90` NOPs |
| `GunWeaponHandler.DecreaseBullet` subtraction | 24285869 | `83 ea 01` | `83 ea 00` |
| Inlined subtraction in `GunWeaponHandler.FireWeapon` | 24289351 | `83 e9 01` | `83 e9 00` |
| `PlayerCharacter.get_IsImmuneDamage` entry | 8236080 | `48 89 5c` | `b0 01 c3` |
| `PlayerBreathHandler.SetHitHP` entry | 24369456 | `48` | `c3` |
| `NetGearForTutorial` cargo callback | 26938848 | `ff 8a d0 01 00 00` | six `90` NOPs |
| `NetGear` cargo callback | 26941952 | `ff 8a d0 01 00 00` | six `90` NOPs |
| `StickyNet` cargo callback | 27154928 | `ff 8a d0 01 00 00` | six `90` NOPs |
| `AttachBalloonCommand_SO` cargo callback | 29786718 | `ff 8a d0 01 00 00` | six `90` NOPs |

### Why these locations were selected

- **Oxygen:** metadata identified `PlayerBreathHandler`, its update functions and `ChangeOxygenValue`. Static inspection showed `addss xmm8,xmm6` adding the oxygen delta to the prior value. Removing that addition preserved the surrounding state/UI updates. The user reported that normal oxygen consumption stopped, while damage still occurred; oxygen and invulnerability are separate features.
- **Ammo:** the first patch changed only `DecreaseBullet`, and the user reported continued ammo loss. Disassembly of `FireWeapon` revealed an **inlined copy** of the subtraction. Both subtract immediates now change from one to zero, preserving the arithmetic flag update used by the following conditional move. Simply NOPing an arithmetic instruction can leave condition flags stale. The decoder recognizes the old three-NOP patch for migration, but new output must use subtract-zero.
- **Invincibility:** the player immunity getter reads the breath handler's immunity flag; its player-specific getter is patched to return true. `SetHitHP` also receives an early return. A simpler breath-handler getter body appeared shareable, so it was not patched indiscriminately. These changes do not prove every scripted death is blocked.
- **Cargo drone:** `PlayerCharacter.AvailableLiftDroneCount` was identified through getter/setter accesses to field offset `0x1d0`. Searching for decrements to that field found four `dec dword ptr [rdx+0x1d0]` instructions. Method-token lookup and the nested-type table attributed callbacks to `NetGearForTutorial`, `NetGear`, `StickyNet` and `AttachBalloonCommand_SO`. Surrounding code checks/casts the player object. The following instructions overwrite/use no relevant decrement flags before the next call, so these count decrements were replaced with NOPs. The option does not unlock the drone or replenish an already-zero count.

Reference MethodDef tokens from this build include `DecreaseBullet` `0x06003754`, `FireWeapon` `0x0600375e`, `get_IsImmuneDamage` `0x06000314` and `SetHitHP` `0x06003968`. Tokens, callback names, field offsets and inlining can all change after an update.

## Adding a GUI option without breaking other features

1. Establish and document a guarded asset/native change as above. Do not connect an unverified guess to a success claim.
2. Add a distinct feature key and original/enabled byte ranges in `PATCHES`, or a separately validated asset transformation. Check for overlapping ranges.
3. Update the decoder's option state, `build`, `apply` read-back verification, `Panel` variables/widgets, `set_state`, Apply and Restore. Keep native normalization able to reconstruct the exact clean SHA.
4. Add Traditional Chinese and English strings and explain the feature's coverage and existing-zero behavior.
5. Test all relevant on/off combinations, preserving oxygen and existing switches. An enabled switch must not alter unrelated ranges; disabling must restore the exact original bytes.
6. Update README, usage guide and this map. Add new source files to the repository allowlist; keep game-derived outputs ignored.

### Sushi-bar movement speed (added 2026-11-15)

The sushi bar does not use `PlayerCharacter`/`PlayerMoveProperty`. Dave there is `StaffDave` (a `SushiBarStaffBase`), driven by `SushiBarPlayerHanlder`. `StaffDave.CalcMoveSpeed` (RVA `0x1CD0150`) returns `SushiBarStaffBase.CalcMoveSpeed` (staff-table serving speed, float at row `+0x70`, plus buffs) multiplied by `DaveMoveValue.get_speedMultiplier` (RVA `0xC262B0`). That getter reads the current `DaveMoveData` record's float at `+0x14`: the Tired/Walk/Run/Crawl multipliers 0.6/0.9/1.2/0.3 from `DaveMoveDataData`. So `DaveMoveData` is the sushi-bar stamina/dash table, not a swimming or village table. An earlier bundle edit of those values reportedly showed no effect, but it is not recorded whether that was tested in the sushi bar.

A raw `E8`/`E9` scan finds exactly four callers of the getter: `StaffDave.CalcMoveSpeed`, `StaffDaveEvent.CalcMoveSpeed`, `JungleSushiBarStaffDave.OnUpdate` and `JungleSushiBarStaffDave.UpdateMovement`. The getter is not identical-code-folded (one method maps to it). The user asked for the multiplier to be adjustable while the game runs, so the factor lives in data, not code. The DLL has no `int3` cave of 40+ bytes, so `sushi_speed.patched()` rewrites the 80-byte body (raw offset **12734640**, up to the next function at `0xC26300`) in place: same `sub rsp,0x28` prologue, the same `-1`/null/range checks (`movsxd` hoisted before the `-1` compare to save a byte), then `m + m * [slot]` via `movss xmm1,[rip+slot]; mulss xmm1,xmm0; addss xmm0,xmm1`. The slot is RVA **0x7F41FF4**, next to the weapon selector's pending slot in the zero-initialised `.data` slack, so a fresh game runs at 1x and the panel writes `factor - 1`. All invalid states call the null-reference thrower `0x57A390`; the last null check is inverted to skip over that call so its return address stays inside the function. Because the body now ends at `0xC26300`, the function's `.pdata` `EndAddress` (raw offset **131332664**) is changed from `0xC262FD` to `0xC26300`; `normalize()` requires body and unwind end to agree. Range 0.1-10.

Live writes reuse `weapon_selector.live_write()` (shared with the weapon queue): one `DaveTheDiver.exe` process, matching exe/module paths, exact patched body in memory, then a 4-byte write to the slot with read-back. The GUI keeps the running game in sync: it polls `game_running()` every 3 s, writes on value change (300 ms debounce) and after each new launch, and remembers the value as `sushi_speed` in `gui-preferences.json`. File state is the `sushi_live` boolean in decoded settings.

Status: statically verified (objdump of the patched copy) and file-tested; not yet confirmed in game.

### Live swimming speed and backpack capacity (added 2026-11-15)

The user asked for every multiplier to change without relaunching. Swimming speed was a bundle edit (`PlayerMoveProperty.moveSpeed`, read only at load), so both features are now native hooks reading data slots, like the sushi bar. GUI: one **Enable live multipliers** checkbox installs `sushi_live`, `swim_live` and `backpack_live` together; the three values live in `gui-preferences.json` (`swim_speed`, `backpack` = number or `"unlimited"`, `sushi_speed`) and are synced by `Panel.sync_live` (3 s poll, 300 ms debounce, reapplied after each launch). The GUI always sends `speed=1`, so Apply restores the swimming bundle; a previously applied bundle factor is read once and carried over to the live swimming value (status message tells the user to apply). `Controller` still decodes the bundle factor for that migration and for Restore.

**Code-cave technique.** No int3 padding run in the DLL is longer than 15 bytes (23,716 runs of 12-15 bytes lie strictly between a function's `.pdata` EndAddress and the next BeginAddress). Each hook replaces one instruction with `call stage1`; stage1 (body + `jmp stage2`) and stage2 (body + `ret`) occupy two such runs. The routines are leaf code with no unwind data: they never touch `rsp` and cannot fault, which is ABI-valid for addresses outside every `RUNTIME_FUNCTION`. `test_control_panel` checks against the real backup that every routine lies in padding entirely outside `.pdata` ranges. Slot loads use `movss` from memory (zeroing lanes 1-3), which allows 3-byte `mulps`/`addps` where both operands were loaded that way. Slots: weapon `0x7F41FF0`, sushi `0x7F41FF4`, swimming **`0x7F41FF8`**, backpack **`0x7F41FFC`** (last dword before `.pdata`); zero = 1x, the panel writes `factor - 1`.

Swimming (`swim_live`): `PlayerMoveProperty.GetMoveSpeed` result is stored in `PlayerCharacter+0x378` by `Awake`, `UpdateMoveProperty` and `Event_OnStopUseBooster`; a byte scan for SSE accesses to `+0x378` finds only one reader, `PlayerCharacter.DetermineMoveSpeed` (called from `ApplyMovement`) at RVA **0x7BF365** `movss xmm1,[rbx+0x378]` (8 bytes) -> `call 0x7C00C3; nop3`. Routine: `movss xmm1,[rbx+0x378]; jmp 0x7C4871` / `movss xmm0,[slot]; mulps xmm0,xmm1; addps xmm1,xmm0; ret`. `xmm0` is dead there (next is `ApplyMoveSpeed(rcx, xmm1)`); `rcx` is preserved. The forced-speed path (`+0x380` flag -> `+0x37c`) and buffs/boosters/grab multipliers are untouched and still multiply on top.

Backpack (`backpack_live`). `LootBox` (dive cargo) has two limits, both from the inventory upgrade (`SubEquipmentType` 3 = `inventory`; levels' `LootboxWeight`/`OverwightThreshold` (game spelling) in the `DR_GameData_Equipment` `SubEquipment` table: (9,13) ... (42,56) ... (185,196) kg):
- Overload threshold: `OverweightProperty.get_OverloadedThreshold` and `GetDebuff` are the only readers of the equipped inventory row's `+0x50` (checked over all 23 `GetEquipedSubEquipByType` callers). `RefreshOverweight` stores it (+ `WeightParameter`) in `LootBox+0x40`; `CheckOverloadedState` (18 pickup callers) blocks pickups above it; `GetDebuff` selects the heavier debuff. Both `movss xmm6,[rax+0x50]` sites (RVA **0x1C5CBDE**, **0x1C5CAB4**; skipped when no inventory is equipped) -> `call 0x1C5C2E1`: `movss xmm6,[rax+0x50]; jmp 0x1C5F5B1` / `movss xmm0,[slot]; mulps xmm0,xmm6; addps xmm6,xmm0; ret`. `xmm0` is dead at both sites. Re-evaluated on every add/remove, so it is live.
- Weight limit: `LootBox.weightMax` (`+0x18`, the "x / 42 kg" text; `RefreshOverweight` applies the slowdown above it) = player stat 9 + `WeightParameter` (`+0x38`), computed in `LootBox.Load` (dive start, from a scene `Start` coroutine) and `LootBox.Add_Lobby`. `SubEquipmentManager.MakeStatusDic` fills stat 9 from row `+0x4c`. `weightMax` is read inline in ~12 places (UI, add/remove/take), so instead of patching readers the two writers are hooked: `addss xmm0,[rbx+0x38]` at **0x1AA2E33** -> `call 0x1AA7553` (`movss xmm1,[slot]; jmp 0x1AA87E1` / `mulss xmm1,xmm0; addss xmm0,xmm1; addss xmm0,[rbx+0x38]; ret`) and `addss xmm0,[rsi+0x38]` at **0x1A9EC04** -> `call 0x1A9CF52` (same with `[rsi+0x38]`, second stage **0x1A96FE1**). Scalar ops here because the stat call's `xmm0` upper lanes are undefined; `xmm1` is dead at both sites. So the displayed limit/slowdown point changes from the next dive.
- Unlimited = factor 1000 (slot 999.0).

An earlier, never-shipped version of this feature edited the equipment table (same-length rewrite of the ten `LootboxWeight`/`OverwightThreshold` pairs). It was replaced because a data change needs a relaunch.

Status: statically verified (objdump of the patched copy, every site and routine) and file-tested; not yet confirmed in game.

### Steam Deck / Linux (added 2026-11-15)

Proton runs the same Windows depot, so hashes, backups, offsets and every file patch are unchanged; `steam_platform.py` only replaces OS plumbing, selected by `os.name`:

- **Game folder:** `find_game()` reads `steamapps/libraryfolders.vdf` under each Steam root (`~/.local/share/Steam`, `~/.steam/steam`, `~/.steam/root`, Flatpak; registry `SteamPath` on Windows) and returns the first library containing `steamapps/common/Dave the Diver/GameAssembly.dll`. Linux paths are case-sensitive; every hard-coded game path was checked against the installed case.
- **Process:** the game is the process whose `argv[0]` (from `/proc/<pid>/cmdline`, a Windows path under Wine) has basename `DaveTheDiver.exe`. Matching only argv[0] avoids Proton/pressure-vessel wrappers that pass the exe path as a later argument.
- **Live writes:** `weapon_selector.live_write()` dispatches to `linux_live_write()` (same contract and checks). Module base = an offset-0 mapping named `GameAssembly.dll` in `/proc/<pid>/maps`, accepted if its path resolves to the selected installation's DLL or, because Steam runs Proton in a pressure-vessel container whose mount paths can differ, if the first 0x400 bytes in memory equal the on-disk PE header ignoring `OptionalHeader.ImageBase`. Then the exact installed code is verified and the 4 bytes are written through `/proc/<pid>/mem` and read back. Writing requires ptrace-attach permission; with Yama `ptrace_scope=1` a non-descendant is refused, and the `PermissionError` tells the user to run `sudo sysctl kernel.yama.ptrace_scope=0` (temporary). Not verified on real SteamOS: whether Wine's header mapping appears with the file path, the actual default ptrace scope, and whether the stock Python has Tkinter.
- **Player.log:** `<library>/steamapps/compatdata/1868140/pfx/drive_c/users/steamuser/AppData/LocalLow/nexon/DAVE THE DIVER/Player.log` (the prefix lives in the game's own library).
- **Launch:** `xdg-open steam://rungameid/1868140`. **Fonts:** Noto Sans CJK TC / Noto Sans instead of Microsoft JhengHei UI / Segoe UI.
- **Small screens:** both tabs are `ScrollFrame`s (canvas + scrollbar shown only when needed; wheel/Button-4/5 scroll the current tab except over the Treeview). The weapon tab is `shrinkable` (the list shrinks down to a 560 px tab before scrolling), so a 1280×800 Deck window (720 px tall) scrolls while the 980 px Windows window looks as before.

## Game updates: remapping is required, not just new hashes

### Experimental underwater weapon-selector map

Root cause of the first (failed) attempt, found 2026-11-15: the adapter patched the standalone `PlayerCharacter.OnSwitchWeapon_Performed` (RVA `0x7CE530`), which **never runs**. The compiler inlined that method into `PlayerCharacter.OnDirectHandler`, the player input dispatcher. A full-DLL scan found no direct callers and no delegate-creation usage slot for the standalone method, while the lambda `<OnSwitchWeapon_Performed>b__897_0` MethodInfo slot (`0x187895050`) is referenced from both the standalone body and an identical block in `OnDirectHandler`. `Player.log` confirmed it: no `*WeaponHandler:EquipItem` load occurred after dive start-up during the Tab tests. Same lesson as the ammo `FireWeapon` inlining: check for inlined copies.

The user's requested scope includes weapons not carried on the current dive. `InGameMetaGunSystem.ChangeWeaponBySlot` only selects slots; it is not a general weapon grant API. The inspected `InstanceItemInventory.CheatEquip` entry is a **no-op stub**, despite its promising name. Do not invoke it or claim it works.

`InstanceItemInventory.DirectEquip(itemID)` = `StoreInstanceItem(itemID, false)` then tail-call `EquipItem(itemID, true)`. `EquipItem` stores the slot and, when the slot's handler (`[inventory+0x30]` type 0, `+0x28` types 1/2, `+0x20` type 3) is alive, calls the handler's virtual `EquipItem(SpecDataBase, bool)` so the live weapon is rebuilt.

Version history: v1 patched the uncalled standalone method (no effect). v2 patched the inlined block and called DirectEquip on every press; the user confirmed on 2026-11-15 that the weapon changed in a dive, but Tab had replaced the game's own harpoon/gun swap, so the new gun could not be selected. v3 (current) equips once per queue and otherwise performs the normal swap.

Supported-build constants in `weapon_selector.py` (v3):

- Patch site: the inlined SwitchWeapon block in `OnDirectHandler`, RVA **0x7C864C** to **0x7C86FC** (176 bytes), raw file offset **8156236** (il2cpp section: raw = RVA - 0x1200). It is entered only after `call 0x182dc1960` with action index `0xe` / `je 0x7C86FC` at RVA `0x7C8646`; no other branch targets its interior. `rdi` = PlayerCharacter, `rsi` = input context; the code at `0x7C86FC` reloads `r8`/`edx`/`rcx` and does not depend on `rbx` from this block.
- Pending-weapon slot: RVA **0x7F41FF0**, a dword in the unused slack between `.data`'s VirtualSize end (`0x7F415A0`) and `.pdata` (`0x7F42000`). That page is mapped with `.data`'s RW protection and the slack is zero at load, so nothing is pending at game start.
- Adapter: `mov edx,[pending]`; if 0, or `[rdi+0x2a0]` (PlayerCharacter.m_InstanceItemInven) is null, `mov rcx,rdi; call OnSwitchWeapon_Performed` (standalone RVA **0x7CE530**, restored to original bytes; verified instruction-equivalent to the inlined block apart from prologue/register order). Otherwise clear the slot and `call DirectEquip(inventory, id, null)`. Both paths `jmp 0x7C86FC`.
- `DirectEquip`: MethodDef `0x0600583e`, RVA **25998240**.
- Migration: the v1 adapter (raw offset 8180528) and the v2 adapter at the site are recognised in files only so existing installs can be read; Apply always restores original bytes and writes v3. Live queueing refuses anything but the exact v3 adapter.
- Live queueing verifies the process/module paths, the exact adapter and catalogue membership, then writes only the four-byte pending slot (plain data write; no code page or protection change). Read-back means queued, not equipped.
- Equip confirmation: `equip_events()` reads `Player.log` after the queue position and reports `*WeaponHandler:EquipItem` stack traces that did not come from `EquipSavedSlotData` (dive start-up). After a queue, the GUI polls it every second for up to three minutes and reports the equip in the weapon status line.
- The file no longer stores a weapon ID; `weapon_id` in decoded settings is always `DEFAULT_ITEM`.

Status 2026-11-15: user confirmed in game that v3 works: a queued weapon is equipped by the next weapon-switch press, and later presses swap between the harpoon and the new gun. The catalogue lists only the highest level of each weapon (`extract_catalog(highest_only=True)`, grouped by type and derived name); queue results and Apply/Restore errors are shown in the GUI status lines, not dialogs (only the restore and launch-with-unapplied-changes confirmations remain).

The weapon list is extracted locally from `DR_GameData_Equipment`'s `EquipmentItem` table. Follow its catalog dependency, find the TextAsset by name and parse `EquipmentItem@/` with `JSONDecoder.raw_decode`. Current catalogue filters: `ItemType` 0/1/2/3, `DLCType == 0`, valid ItemScriptableID and ItemTextID. Grouping uses names derived from `ItemTextID`; the GUI displays official names from the local `InstanceItemText` table (`DR_GameData_Text_Item.xlsx` worksheet, MonoBehaviour with `dataArray` rows keyed by `name` = `ItemTextID`, columns `english`, `chinesetraditional`, ...). All 109 highest-level rows have a match and names are unique per language. `item_names()` decompresses that bundle (~8 s in pure-Python LZ4), so the result is cached in the ignored `weapon-names-cache.json`, keyed by bundle path/size/mtime; the GUI loads the catalogue in a worker thread.

Weapon categories: `EquipmentItem` has no gun-family field. `weapon_selector.weapon_category()` matches `ItemTextID` tokens in order (`ShotGun`, `Sniper`, `SleepGun`, `GrenadeLauncher`, `StickyBombGun`, `NetGun`, `IceGun`, `DrainGun`, `BasicRifle`; first match wins, so `Sleep_Sniper` is a sniper and `SleepGun` is the Hush Dart family), and labels come from the game's `<Family>_Type` texts in `InstanceItemText` (e.g. `SniperGun_Type`). All 78 base-game guns map to the 8 families present; non-guns use `ItemType` (Harpoon, HarpoonHead, Melee). The GUI shows them as flowing category tabs with a representative icon and count.

Weapon icons (`weapon_icons.py`): each equipment row's `ItemIcon` names a Sprite packed in the `InGameAtlas_Point` SpriteAtlas (bundle found through the catalog entry `InGameAtlas_Point.spriteatlas`). A packed Sprite's own `m_RD.texture` is null; look up its `m_RenderDataKey` in the SpriteAtlas `m_RenderDataMap` to get the atlas texture PPtr, `textureRect` and `settingsRaw` (bits 2-5 = packing rotation; all weapon icons are 0). The atlas texture is `m_TextureFormat` 4 (RGBA32, 1024x2048, one mip) streamed from the bundle's `.resS` node; rows are bottom-up. Icons are cropped to PNG (stdlib zlib encoder) in the ignored `weapon-icons/` folder with a `stamp.json` keyed to bundle path/size/mtime and the requested names. 102 of 109 rows have an icon; the six harpoon guns' `Item_*HarpoonGun` sprites were not found in any non-DLC atlas and the dive knife has no `ItemIcon`. `inspect_dave.read_object_fields` now reads `TypelessData` (`common:894`) as length-prefixed bytes; it previously mis-parsed Sprite/Texture2D objects. There are 451 entries in the inspected base-game table, including levels. Never commit the extracted table/catalogue.

Status: offline byte/flow/restore tests pass and the user confirmed the equip and swap in a dive. Still verify keyboard binding availability, free-control state, animations, ammo/UI refresh and save effects before expanding support. Do not force-use during transitions/QTEs or claim every possible weapon/DLC works. The native callback rewrite, inventory field offset, method RVA, catalogue schema and live-write preconditions all require remapping after an update.

### Update procedure

Treat a Steam update or hash mismatch as **unsupported until re-investigated**. Do not apply the old offsets or merely replace the expected hashes to suppress the guard.

1. Stop writes and close the game. Preserve known-good originals, the existing profile and patch reports separately. Do not restore an old build's DLL over a newly updated installation.
2. Obtain clean originals for the updated installed build through the user's normal Steam installation/verification process. Preserve other intentional modifications before verification; do not silently discard them.
3. Record new versions/hashes and keep backups separated by build. The current project has a single fixed profile and fixed backup paths, not multi-build support. `prepare_backups.py` trusts existing matching backups; it does not discover a new build when old backups already exist. Do not overwrite the only old backup to retrofit a new version.
4. Reparse metadata magic/version and validate record sizes, strings, type/method associations, signatures and enum encoding. Adapt parsers if the layout changed.
5. Rediscover native code-generation-module pointers and method bodies for the correct assembly. Recheck every original instruction, field layout, control-flow dependency, inlined copy and alternate path. Do not port offsets by adding one global delta.
6. Rediscover the player's asset references through the new catalog and serialized objects. Bundle filenames, CAB names, path IDs, external indexes, field layouts and original float values may all change. Recheck catalog CRC/loading settings.
7. Build new copies and verify them. For maintainability, introduce a build-profile structure if supporting multiple versions: clean hashes, metadata/Unity/Steam versions, bundle/node/object identity, guarded field locations and native preimages belong together.
8. Update `control_panel.py`, `prepare_backups.py` and relevant inspector assumptions consistently. Preserve the unknown-version rejection. Do not accept arbitrary hashes or silently migrate one build's modified file into another build's profile.
9. Test a fresh setup, each switch, combinations, Restore and rollback using new-build backups. Then perform controlled gameplay checks. A title-screen launch alone is insufficient.
10. Publish the supported build and the level of verification in README and this document. Keep prior-build support explicit or clearly mark it unsupported.

## Verification and evidence

```powershell
python -m unittest test_source -v
python -m unittest discover -v
git diff --check
git status --short
```

Integration tests use temporary fixtures and skip when local original backups are absent. They do not measure gameplay. For each newly mapped feature, record: original hashes, reference chain/token, raw offset domain, preimage/postimage, rationale, changed-byte set and test result.

Runtime checks should compare before/after in the same scene and conditions. Test repeated shots, multiple weapon types, several cargo lifts, ordinary breathing, hit damage and switching features off. Measure speed over a fixed route rather than infer it from a multiplier value. Do not spend progression/resources or overwrite saves beyond the user's authorized test scope.

Current evidence: the user confirmed the oxygen behavior; early walking and ammo candidates failed; the later ammo/invincibility/cargo patches have static and file-operation coverage but no comprehensive game-wide validation recorded here. Keep these distinctions in user-facing reports.
