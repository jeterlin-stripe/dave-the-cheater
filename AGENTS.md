# Dave the Cheater: maintenance and parameter-discovery guide

Read this guide before adding a feature or changing compatibility data. It records how the existing parameters were located, including unsuccessful approaches, and how to remap them after a game update.

## Project boundaries

- This is a Windows Steam, Python-standard-library tool. The GUI uses Tkinter; it edits files while the game is closed and does not inject into a running process.
- Keep Traditional Chinese and English UI strings in sync through `gui_language.py`.
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

## Game updates: remapping is required, not just new hashes

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
