#!/usr/bin/env python3
"""Create a transaction-consistent staging tree and send it to encrypted restic storage."""

from __future__ import annotations

import fcntl
import os
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

DATA_ROOT = Path(os.environ.get("VIDEOMEMORY_HOST_DATA", "/opt/videomemory/data")).resolve()
WORK_ROOT = Path(os.environ.get("VIDEOMEMORY_BACKUP_WORK", "/opt/videomemory/backup-work")).resolve()
LOCK_PATH = WORK_ROOT / "backup.lock"
SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
SQLITE_SIDECARS = ("-journal", "-shm", "-wal")


def _skip_database_files(_directory: str, names: list[str]) -> set[str]:
    skipped: set[str] = set()
    for name in names:
        if Path(name).suffix.lower() in SQLITE_SUFFIXES or name.endswith(SQLITE_SIDECARS):
            skipped.add(name)
    return skipped


def _sqlite_files() -> list[Path]:
    return sorted(
        path for path in DATA_ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in SQLITE_SUFFIXES
    )


def _backup_database(source: Path, staging: Path) -> None:
    destination = staging / source.relative_to(DATA_ROOT)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=30) as live,
        sqlite3.connect(destination) as snapshot,
    ):
        live.backup(snapshot)
        result = snapshot.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError(f"SQLite integrity check failed for {source}")


def _run(*args: str) -> None:
    subprocess.run(args, check=True)


def main() -> None:
    if not DATA_ROOT.is_dir():
        raise RuntimeError(f"data root does not exist: {DATA_ROOT}")
    WORK_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with LOCK_PATH.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with tempfile.TemporaryDirectory(prefix="snapshot-", dir=WORK_ROOT) as temporary:
            staging = Path(temporary) / "videomemory"
            shutil.copytree(DATA_ROOT, staging, ignore=_skip_database_files, symlinks=True)
            databases = _sqlite_files()
            for database in databases:
                _backup_database(database, staging)

            stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            subprocess.run(
                [
                    "restic", "backup", ".",
                    "--host", "videomemory-prod",
                    "--tag", "azure",
                    "--tag", "production",
                    "--time", stamp,
                ],
                check=True,
                cwd=staging,
            )
            _run(
                "restic", "forget",
                "--host", "videomemory-prod",
                "--keep-daily", "7",
                "--keep-weekly", "4",
                "--keep-monthly", "6",
                "--prune",
            )
            print(f"backup complete: {len(databases)} SQLite databases verified at {stamp}")


if __name__ == "__main__":
    main()
