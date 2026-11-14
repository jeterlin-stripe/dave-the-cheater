"""Prepare ignored local backups from an unmodified supported installation."""
import argparse
from pathlib import Path
from dave_profile import BUNDLE_BACKUP, BUNDLE_HASH, BUNDLE_RELATIVE, NATIVE_BACKUP, NATIVE_HASH, digest, find_game


def prepare(game):
    game = Path(game)
    files = [
        (game / "GameAssembly.dll", NATIVE_BACKUP, NATIVE_HASH),
        (game / BUNDLE_RELATIVE, BUNDLE_BACKUP, BUNDLE_HASH),
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
    parser.add_argument("--game", type=Path, help="Game folder; detected from Steam libraries when omitted")
    game = parser.parse_args().game or find_game()
    if game is None:
        parser.error("Could not find DAVE THE DIVER in Steam libraries; pass --game.")
    for filename in prepare(game):
        print(f"Verified local backup: {filename}")
