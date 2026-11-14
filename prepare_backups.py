"""Prepare ignored local backups from an unmodified supported installation."""
import argparse
from pathlib import Path
from control_panel import BUNDLE_HASH, BUNDLE_NAME, DEFAULT_GAME, HERE, NATIVE_HASH, digest


def prepare(game):
    game = Path(game)
    files = [
        (game / "GameAssembly.dll", HERE / "resources-upgrade/original/GameAssembly.dll", NATIVE_HASH),
        (game / "DaveTheDiver_Data/StreamingAssets/aa/StandaloneWindows64" / BUNDLE_NAME,
         HERE / "swim-1.5x/original" / BUNDLE_NAME, BUNDLE_HASH),
    ]
    pending = []
    for source, target, expected in files:
        if target.exists():
            if digest(target.read_bytes()) != expected:
                raise ValueError(f"Existing backup does not match; not overwritten: {target}")
            continue
        data = source.read_bytes()
        if digest(data) != expected:
            raise ValueError(f"Unsupported or modified original: {source}. No backups created.")
        pending.append((target, data))
    for target, data in pending:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
        if digest(target.read_bytes()) != digest(data):
            raise OSError(f"Backup verification failed: {target}")
    return [str(target) for _, target, _ in files]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, default=DEFAULT_GAME)
    for filename in prepare(parser.parse_args().game):
        print(f"Verified local backup: {filename}")
