"""Map reusable geographic buckets to windows on canonical grids."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

import numpy as np
import xarray as xr

from polaris.config import get_settings
from storage.catalog import BucketWindowRecord, GridCatalogRecord
from storage.manage.space_containers import (
    container_grid,
    container_id_from_code,
    map_containers,
)


def bucket_windows(
    grid: xr.Dataset,
    grid_id: str,
    bucket_configuration: dict,
) -> list[BucketWindowRecord]:
    """Return bounding grid windows for every bucket touching a grid."""
    buckets = container_grid("buckets", 1, **bucket_configuration)
    codes = map_containers(grid, buckets)
    records = []
    for raw_code in np.unique(codes.values):
        code = int(raw_code)
        mask = codes == code
        y_indices = np.flatnonzero(mask.any(dim="x").values)
        x_indices = np.flatnonzero(mask.any(dim="y").values)
        if not y_indices.size or not x_indices.size:
            continue
        records.append(
            BucketWindowRecord(
                grid_id=grid_id,
                bucket_id=container_id_from_code(code, buckets),
                grid_y_start=int(y_indices[0]),
                grid_y_stop=int(y_indices[-1] + 1),
                grid_x_start=int(x_indices[0]),
                grid_x_stop=int(x_indices[-1] + 1),
            )
        )
    return records


def ensure_bucket_lookup(
    grid_record: GridCatalogRecord,
    grid: xr.Dataset,
    *,
    settings=None,
) -> Path:
    """Write one immutable bucket lookup file for a canonical grid."""
    settings = settings or get_settings()
    path = settings.bucket_lookup_dir / f"{grid_record.grid_id}.jsonl"
    if path.exists():
        return path
    records = bucket_windows(
        grid,
        grid_record.grid_id,
        settings.container_grid,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".partial",
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with temporary.open("w", encoding="utf-8") as file:
            for record in records:
                json.dump(record.to_dict(), file, sort_keys=True)
                file.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def read_bucket_lookup(path: Path) -> tuple[BucketWindowRecord, ...]:
    if not path.exists():
        raise FileNotFoundError(f"Missing bucket lookup: {path}")
    return tuple(
        BucketWindowRecord.from_dict(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
