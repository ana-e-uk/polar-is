"""Normalize canonical grid IDs and deduplicate equivalent grid assets."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile

import h5netcdf
import numpy as np
import xarray as xr

from polaris.config import Settings, get_settings
from storage.bucket_lookup import bucket_windows
from storage.catalog import GridCatalogRecord
from storage.grid_topology import canonical_grid_id


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".partial"
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with temporary.open("w", encoding="utf-8") as file:
            for record in records:
                json.dump(record, file, sort_keys=True)
                file.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def migrate_grid_identity(settings: Settings | None = None) -> dict[str, str]:
    """Apply geometry-only IDs and keep one lookup per distinct grid."""
    settings = settings or get_settings()
    records = _read_jsonl(settings.grids_catalog)
    old_to_new: dict[str, str] = {}
    new_records: dict[str, dict] = {}
    grids: dict[str, xr.Dataset] = {}

    for record in records:
        old_id = record["grid_id"]
        with xr.open_dataset(settings.grids_dir / f"{old_id}.nc") as source:
            grid = source.load()
        new_id = canonical_grid_id(grid)
        old_to_new[old_id] = new_id
        if new_id in grids:
            existing = grids[new_id]
            if dict(existing.sizes) != dict(grid.sizes) or set(existing.variables) != set(grid.variables):
                raise ValueError(f"Grid ID collision for {new_id}")
            for name in existing.variables:
                if existing[name].dims != grid[name].dims or not np.array_equal(
                    existing[name].values, grid[name].values, equal_nan=True
                ):
                    raise ValueError(f"Grid ID collision for {new_id}")
            continue
        grids[new_id] = grid
        new_records[new_id] = GridCatalogRecord(
            grid_id=new_id,
            grid_type=record["grid_type"],
            shape_y=record["shape_y"],
            shape_x=record["shape_x"],
            relative_path=f"catalogs/grids/{new_id}.nc",
        ).to_dict()

    if all(old_id == new_id for old_id, new_id in old_to_new.items()):
        return old_to_new

    for new_id, grid in grids.items():
        grid_path = settings.grids_dir / f"{new_id}.nc"
        if not grid_path.exists():
            temporary = grid_path.with_name(f".{grid_path.name}.partial")
            try:
                grid.to_netcdf(temporary)
                temporary.replace(grid_path)
            finally:
                temporary.unlink(missing_ok=True)
        lookup_path = settings.bucket_lookup_dir / f"{new_id}.jsonl"
        lookup_records = [
            record.to_dict()
            for record in bucket_windows(grid, new_id, settings.container_grid)
        ]
        _write_jsonl(lookup_path, lookup_records)

    product_records = _read_jsonl(settings.product_index)
    for record in product_records:
        record["grid_id"] = old_to_new[record["grid_id"]]
        product_path = settings.product_index.parent / record["relative_path"]
        with h5netcdf.File(product_path, "r+") as product:
            product.attrs["grid_id"] = record["grid_id"]

    _write_jsonl(settings.grids_catalog, list(new_records.values()))
    _write_jsonl(settings.product_index, product_records)

    backup = settings.product_index.parent / "backups" / "grid_id_migration"
    backup.mkdir(parents=True, exist_ok=True)
    for old_id, new_id in old_to_new.items():
        if old_id == new_id:
            continue
        for source in (
            settings.grids_dir / f"{old_id}.nc",
            settings.bucket_lookup_dir / f"{old_id}.jsonl",
        ):
            if source.exists():
                destination = backup / source.name
                if destination.exists():
                    source.unlink()
                else:
                    shutil.move(source, destination)
    return old_to_new


if __name__ == "__main__":
    mapping = migrate_grid_identity()
    print(
        f"Migrated {len(mapping)} prior IDs to "
        f"{len(set(mapping.values()))} canonical grids."
    )
