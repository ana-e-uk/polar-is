"""Remove expired job artifacts left on disk by current or previous runs."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import time

from polaris.config import Settings, get_settings


_JOB_ID = re.compile(r"^[0-9a-f]{32}$")


def _newest_mtime(path: Path) -> float:
    newest = path.stat().st_mtime
    for root, directories, filenames in os.walk(path, followlinks=False):
        root_path = Path(root)
        for name in (*directories, *filenames):
            item = root_path / name
            try:
                newest = max(newest, item.stat().st_mtime)
            except FileNotFoundError:
                continue
    return newest


def cleanup_stale_outputs(
    settings: Settings | None = None,
    *,
    max_age_seconds: int | None = None,
    active_grace_seconds: int = 86_400,
    honor_active_markers: bool = True,
    now: float | None = None,
    dry_run: bool = False,
) -> tuple[Path, ...]:
    """Delete expired UUID-named job directories and return their paths.

    A live server places ``.active`` in a running job directory. Periodic cleanup
    skips a fresh marker, while a marker older than the grace period is treated
    as residue from a crashed process.
    """
    settings = settings or get_settings()
    maximum_age = (
        int(os.getenv("POLARIS_RESULT_TTL_SECONDS", "600"))
        if max_age_seconds is None
        else max_age_seconds
    )
    if maximum_age < 1 or active_grace_seconds < 1:
        raise ValueError("cleanup ages must be positive integers")
    current_time = time.time() if now is None else now
    jobs_root = settings._query_results / "jobs"
    if not jobs_root.is_dir():
        return ()

    removed = []
    for directory in jobs_root.iterdir():
        if not directory.is_dir() or not _JOB_ID.fullmatch(directory.name):
            continue
        marker = directory / ".active"
        if honor_active_markers and marker.exists():
            try:
                marker_age = current_time - marker.stat().st_mtime
            except FileNotFoundError:
                marker_age = active_grace_seconds + 1
            if marker_age < active_grace_seconds:
                continue
        try:
            age = current_time - _newest_mtime(directory)
        except FileNotFoundError:
            continue
        required_age = active_grace_seconds if marker.exists() else maximum_age
        if age < required_age:
            continue
        removed.append(directory)
        if not dry_run:
            shutil.rmtree(directory)
    return tuple(removed)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove expired Polar-is job output directories"
    )
    parser.add_argument(
        "--max-age-seconds",
        type=int,
        default=None,
        help="age for completed/orphaned outputs (default: result TTL)",
    )
    parser.add_argument(
        "--active-grace-seconds",
        type=int,
        default=86_400,
        help="age after which a stale .active marker may be removed",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    removed = cleanup_stale_outputs(
        max_age_seconds=args.max_age_seconds,
        active_grace_seconds=args.active_grace_seconds,
        dry_run=args.dry_run,
    )
    action = "Would remove" if args.dry_run else "Removed"
    print(f"{action} {len(removed)} expired Polar-is job directorie(s).")
    for path in removed:
        print(path)


if __name__ == "__main__":
    main()
