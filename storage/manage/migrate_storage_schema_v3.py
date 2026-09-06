"""Migrate stored blocks to metadata schema 3.

Schema 3 uses normalized block fields, 128-bit block IDs, and derived paths.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile

from polaris.config import get_settings
from storage.ingest_data.aggregate_data import normalize_temporal_resolution
from storage.ingest_data.make_data_blocks import (
    AGGREGATION_VERSION,
    METADATA_SCHEMA_VERSION,
    _block_id,
    block_path,
    timestamp_string,
    update_container_file_counts,
)
from storage.ingest_data.standardize import read_metadata


def _write_metadata_atomically(path: Path, records: list[dict]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".partial",
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        with temporary_path.open("w", encoding="utf-8") as file:
            for record in records:
                json.dump(record, file)
                file.write("\n")
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _normalize_record(old: dict, scheme) -> dict:
    record = {**old}
    record.pop("file_path", None)
    record.pop("source_file_paths", None)
    record.pop("product_id", None)
    record.pop("block_id", None)

    record["spatial_level"] = record.pop("container", scheme.name)
    if "container_code" in record:
        record["bucket_code"] = record.pop("container_code")
    if "container_id" in record:
        record["bucket_id"] = record.pop("container_id")
    if "additional_params" in record:
        record["additional_parameters"] = record.pop("additional_params")
    if "spatial_coarsening_factor" in record:
        record["coarseness_factor"] = record.pop(
            "spatial_coarsening_factor"
        )

    record["temporal_resolution"] = normalize_temporal_resolution(
        record["temporal_resolution"]
    )
    record["native_temporal_resolution"] = normalize_temporal_resolution(
        record["native_temporal_resolution"]
    )
    record["coarseness_factor"] = int(record["coarseness_factor"])
    record["time_start"] = timestamp_string(record["time_start"])
    record["time_end"] = timestamp_string(record["time_end"])
    record["metadata_schema_version"] = METADATA_SCHEMA_VERSION
    record["aggregation_version"] = AGGREGATION_VERSION

    identity = {
        key: value
        for key, value in record.items()
        if key != "block_summary"
    }
    return {
        **identity,
        "block_id": _block_id(identity),
        "block_summary": record["block_summary"],
    }


def migrate_scheme(scheme) -> int:
    if not scheme.metadata.exists():
        return 0

    old_records = read_metadata(scheme.metadata)
    if any(record.get("product_type") == "aggregate" for record in old_records):
        raise ValueError(
            f"Regenerate aggregate blocks before migrating {scheme.name}"
        )

    moves = []
    new_records = []
    targets = set()
    for old, new in zip(
        old_records,
        (_normalize_record(record, scheme) for record in old_records),
    ):
        source = Path(old["file_path"])
        target = block_path(scheme, new["bucket_id"], new["block_id"])
        if not source.is_file():
            raise FileNotFoundError(f"Stored block is missing: {source}")
        if target in targets or (target.exists() and target != source):
            raise FileExistsError(f"Migration target already exists: {target}")
        targets.add(target)
        moves.append((source, target))
        new_records.append(new)

    backup = scheme.metadata.with_name("metadata.schema2.backup.jsonl")
    if not backup.exists():
        shutil.copy2(scheme.metadata, backup)

    completed = []
    try:
        for source, target in moves:
            source.replace(target)
            completed.append((source, target))
        _write_metadata_atomically(scheme.metadata, new_records)
    except BaseException:
        for source, target in reversed(completed):
            target.replace(source)
        raise

    update_container_file_counts(scheme)
    return len(new_records)


def migrate() -> int:
    settings = get_settings()
    return sum(
        migrate_scheme(scheme)
        for scheme in settings.container_schemes.values()
    )


if __name__ == "__main__":
    print(f"Migrated {migrate()} blocks to metadata schema 3")
