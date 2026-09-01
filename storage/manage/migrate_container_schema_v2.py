"""One-time migration of pre-container capacity-1 storage to schema v2."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile

import xarray as xr

from polaris.config import PROJECT_ROOT, get_settings
from storage.ingest_data.aggregate_data import infer_native_temporal_resolution
from storage.ingest_data.make_data_blocks import (
    AGGREGATION_VERSION,
    METADATA_SCHEMA_VERSION,
    _json_identity,
    update_container_file_counts,
)
from storage.ingest_data.standardize import read_metadata
from storage.manage.space_containers import (
    container_definitions,
    ensure_all_container_schemes,
    grid_for_scheme,
)


def _write_json_atomically(path: Path, value, *, json_lines=False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".partial",
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        with temporary_path.open("w", encoding="utf-8") as file:
            if json_lines:
                for item in value:
                    json.dump(item, file)
                    file.write("\n")
            else:
                json.dump(value, file, indent=2)
                file.write("\n")
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _relocate_project_path(value: str) -> str:
    parts = Path(value).parts
    try:
        storage_index = parts.index("storage")
    except ValueError:
        return value
    return str(PROJECT_ROOT.joinpath(*parts[storage_index:]))


def _matching_source(record: dict, standardized: list[dict]) -> str | None:
    identifying_fields = (
        "repository",
        "dataset",
        "variable",
        "start_year",
        "start_month",
        "end_year",
        "end_month",
        "region",
        "additional_params",
    )
    matches = [
        candidate
        for candidate in standardized
        if all(record.get(key) == candidate.get(key) for key in identifying_fields)
    ]
    if len(matches) == 1:
        return matches[0]["file_path"]
    return None


def migrate() -> None:
    settings = get_settings()
    capacity_1 = settings.container_schemes["capacity_1"]

    standardized = read_metadata(settings.standardized_data_)
    for record in standardized:
        record["file_path"] = _relocate_project_path(record["file_path"])
    _write_json_atomically(
        settings.standardized_data_, standardized, json_lines=True
    )

    old_definitions = json.loads(capacity_1.definitions.read_text())
    expected = container_definitions(grid_for_scheme(capacity_1))
    for container_id, definition in expected.items():
        definition["data"] = old_definitions.get(container_id, {}).get("data", 0)
    _write_json_atomically(capacity_1.definitions, expected)

    records = read_metadata(capacity_1.metadata)
    backup = capacity_1.metadata.with_name("metadata.schema1.backup.jsonl")
    if not backup.exists():
        shutil.copy2(capacity_1.metadata, backup)
    migrated = []
    skipped = []
    for old in records:
        record = {**old}
        if "bucket_code" in record:
            record["container_code"] = record.pop("bucket_code")
        if "bucket_id" in record:
            record["container_id"] = record.pop("bucket_id")
        record["container"] = "capacity_1"
        record["metadata_schema_version"] = METADATA_SCHEMA_VERSION
        record["aggregation_version"] = AGGREGATION_VERSION
        record["product_type"] = "native"
        record["native_spatial_resolution"] = record.get("spatial_resolution")
        record["spatial_coarsening_factor"] = 1
        record["temporal_aggregation_method"] = None
        record["spatial_aggregation_method"] = None
        record["aggregation_order"] = "temporal_then_spatial"
        source = _matching_source(record, standardized)
        record["source_file_paths"] = [source] if source else []
        path = (
            capacity_1.data_dir
            / record["container_id"]
            / Path(record["file_path"]).name
        )
        record["file_path"] = str(path)
        if not path.is_file():
            skipped.append(path)
            continue
        with xr.open_dataset(path) as block:
            timestamp = block.get("timestamp")
            native_temporal = infer_native_temporal_resolution(
                timestamp, record["temporal_resolution"]
            )
            record["native_temporal_resolution"] = native_temporal
            record["temporal_resolution"] = native_temporal
            record["time_start"] = (
                str(timestamp.values[0]) if timestamp is not None else None
            )
            record["time_end"] = (
                str(timestamp.values[-1]) if timestamp is not None else None
            )
        identity = {
            key: value
            for key, value in record.items()
            if key not in {"product_id", "block_summary", "file_path"}
        }
        record["product_id"] = _json_identity(identity)
        migrated.append(record)
    _write_json_atomically(capacity_1.metadata, migrated, json_lines=True)
    ensure_all_container_schemes()
    for scheme in settings.container_schemes.values():
        update_container_file_counts(scheme)
    if skipped:
        print(
            f"Skipped {len(skipped)} stale metadata records whose block files "
            f"were already missing; the original index is preserved at {backup}."
        )


if __name__ == "__main__":
    migrate()
