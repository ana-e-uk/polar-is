"""Append-only audit log for queries accepted by Polar-is."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any


QUERY_CLIENTS = frozenset({"api", "cli", "interface"})


def normalize_query_client(value: str | None) -> str:
    """Return a known query origin, defaulting unlabelled clients to the API."""
    client = (value or "api").strip().lower()
    return client if client in QUERY_CLIENTS else "api"


def append_query_log(
    path: Path,
    *,
    job_id: str,
    client: str,
    owner: str,
    outputs: tuple[str, ...],
    query: dict[str, Any],
    submitted_at: datetime | None = None,
) -> None:
    """Append one complete JSON record using a single operating-system write."""
    timestamp = submitted_at or datetime.now(timezone.utc)
    record = {
        "job_id": job_id,
        "submitted_at": timestamp.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "client": normalize_query_client(client),
        "owner": owner,
        "outputs": list(outputs),
        "query": query,
    }
    line = (json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n").encode(
        "utf-8"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o640)
    try:
        written = os.write(descriptor, line)
        if written != len(line):
            raise OSError(f"Incomplete query-log write: {written} of {len(line)} bytes")
    finally:
        os.close(descriptor)
