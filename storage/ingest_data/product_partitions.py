"""Write compact time-partitioned products and their shared indexes."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import tempfile

import numpy as np
import pandas as pd
import xarray as xr

from polaris.config import get_settings
from storage.catalog import (
    DatasetCatalogRecord,
    ProductIndexRecord,
    stable_128_bit_id,
)


METADATA_SCHEMA_VERSION = 3
AGGREGATION_VERSION = 1


def dataset_variant_identity(record: dict) -> tuple[str, dict]:
    """Return a stable dataset-variant ID and normalized parameters."""
    parameters = record.get(
        "additional_parameters", record.get("additional_params")
    ) or {}
    identity = {
        "repository": record.get("repository", "unknown"),
        "dataset": record["dataset"],
        "additional_parameters": parameters,
    }
    return stable_128_bit_id(identity), dict(parameters)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _append_unique_jsonl(
    path: Path,
    records: list[dict],
    identity_field: str,
) -> None:
    existing = _read_jsonl(path)
    existing_ids = {item[identity_field] for item in existing}
    additions = [
        item for item in records if item[identity_field] not in existing_ids
    ]
    if not additions:
        return
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
            for item in [*existing, *additions]:
                json.dump(item, file, sort_keys=True)
                file.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _upsert_dataset_record(path: Path, record: DatasetCatalogRecord) -> None:
    """Add a variant or merge another variable into its catalog record."""
    existing = _read_jsonl(path)
    replacement = record.to_dict()
    for index, item in enumerate(existing):
        if item["dataset_variant_id"] != record.dataset_variant_id:
            continue
        for name in ("repository", "dataset", "additional_parameters"):
            if item[name] != replacement[name]:
                raise ValueError(
                    f"Dataset variant {record.dataset_variant_id} has conflicting {name}"
                )
        replacement = {
            **item,
            "variables": {**item.get("variables", {}), **record.variables},
        }
        existing[index] = replacement
        break
    else:
        existing.append(replacement)
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
            for item in existing:
                json.dump(item, file, sort_keys=True)
                file.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _time_partition_groups(
    data: xr.Dataset,
    time_unit: str,
) -> list[tuple[str, np.ndarray]]:
    timestamps = pd.DatetimeIndex(data["timestamp"].values)
    labels = (
        timestamps.strftime("%Y-%m")
        if time_unit in {"Source", "Hour", "Day"}
        else timestamps.strftime("%Y")
    )
    return [
        (label, np.flatnonzero(labels == label))
        for label in dict.fromkeys(labels)
    ]


def _chunk_encoding(data: xr.Dataset, target_bytes: int) -> dict:
    """Choose bounded spatial chunks so small regional reads stay small."""
    encoding = {}
    for name, variable in data.data_vars.items():
        if not variable.dims:
            continue
        itemsize = max(1, variable.dtype.itemsize)
        dimension_chunks = {
            dim: min(variable.sizes[dim], 128 if dim == "y" else 256)
            for dim in variable.dims
            if dim != "timestamp"
        }
        spatial_values = np.prod(
            list(dimension_chunks.values()),
            dtype=np.int64,
        )
        time_chunk = max(1, target_bytes // max(1, itemsize * spatial_values))
        chunks = tuple(
            min(variable.sizes[dim], int(time_chunk))
            if dim == "timestamp"
            else dimension_chunks[dim]
            for dim in variable.dims
        )
        encoding[name] = {
            "zlib": True,
            "complevel": 3,
            "shuffle": True,
            "chunksizes": chunks,
        }
    return encoding


def _stored_product(
    data: xr.Dataset,
    variable: str,
    time_unit: str,
    *,
    grid_id: str,
    coarseness_factor: int,
) -> xr.Dataset:
    names = (
        [variable]
        if time_unit == "Source"
        else [
            "polaris_weighted_sum",
            "polaris_weight_sum",
            "polaris_min",
            "polaris_max",
        ]
    )
    names.extend(
        name for name in ("source_count",) if name in data and name not in names
    )
    missing = [name for name in names if name not in data]
    if missing:
        raise ValueError(f"Product is missing stored variables: {missing}")
    result = data[names].copy()
    for name in tuple(result.coords):
        if name != "timestamp":
            result = result.drop_vars(name)
    result.attrs = {
        "grid_id": grid_id,
        "grid_y_start": 0,
        "grid_x_start": 0,
        "coarseness_factor": coarseness_factor,
    }
    return result


def write_product_partitions(
    data: xr.Dataset,
    record: dict,
    *,
    grid_id: str,
    grid_shape: tuple[int, int],
    time_unit: str,
    temporal_resolution: str,
    coarseness_factor: int,
    settings=None,
    target_chunk_bytes: int = 4 * 1024 * 1024,
) -> list[dict]:
    """Write monthly/yearly NetCDF partitions and append shared index rows."""
    settings = settings or get_settings()
    variable = record["variable"]
    variant_id, parameters = dataset_variant_identity(record)
    units = data[variable].attrs.get("units") if variable in data else None
    variable_metadata = {
        "units": units,
        "source_temporal_resolution": record["temporal_resolution"],
    }
    dataset_record = DatasetCatalogRecord(
        dataset_variant_id=variant_id,
        repository=record.get("repository", "unknown"),
        dataset=record["dataset"],
        additional_parameters=parameters,
        variables={variable: variable_metadata},
        display_name=record.get("display_name"),
    )
    _upsert_dataset_record(settings.datasets_catalog, dataset_record)

    stored = _stored_product(
        data,
        variable,
        time_unit,
        grid_id=grid_id,
        coarseness_factor=coarseness_factor,
    )
    new_records = []
    created_paths = []
    existing = {
        item["partition_id"]: item for item in _read_jsonl(settings.product_index)
    }
    try:
        for label, indices in _time_partition_groups(stored, time_unit):
            partition = stored.isel(timestamp=indices)
            time_start = timestamp_string(partition["timestamp"].values[0])
            time_end = timestamp_string(partition["timestamp"].values[-1])
            identity = {
                "dataset_variant_id": variant_id,
                "variable": variable,
                "grid_id": grid_id,
                "temporal_resolution": time_unit,
                "coarseness_factor": coarseness_factor,
                "time_start": time_start,
                "time_end": time_end,
            }
            partition_id = stable_128_bit_id(identity)
            relative_path = PurePosixPath(
                "products",
                variant_id,
                variable,
                time_unit,
                f"coarsen_{coarseness_factor}",
                f"{label}_{partition_id}.nc",
            ).as_posix()
            index_record = ProductIndexRecord(
                partition_id=partition_id,
                dataset_variant_id=variant_id,
                variable=variable,
                grid_id=grid_id,
                temporal_resolution=time_unit,
                coarseness_factor=coarseness_factor,
                time_start=time_start,
                time_end=time_end,
                grid_y_start=0,
                grid_y_stop=int(grid_shape[0]),
                grid_x_start=0,
                grid_x_stop=int(grid_shape[1]),
                relative_path=relative_path,
            )
            if partition_id in existing:
                path = settings.products_dir.parent / existing[partition_id][
                    "relative_path"
                ]
                if not path.is_file():
                    raise FileNotFoundError(
                        f"Index points to missing partition: {path}"
                    )
                continue
            output_path = settings.products_dir.parent / relative_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if output_path.exists():
                raise FileExistsError(
                    f"Orphan product partition exists: {output_path}"
                )
            temporary = output_path.with_name(f".{output_path.name}.partial")
            try:
                partition.to_netcdf(
                    temporary,
                    encoding=_chunk_encoding(partition, target_chunk_bytes),
                )
                temporary.replace(output_path)
            finally:
                temporary.unlink(missing_ok=True)
            created_paths.append(output_path)
            new_records.append(index_record.to_dict())
        _append_unique_jsonl(
            settings.product_index,
            new_records,
            "partition_id",
        )
    except BaseException:
        for path in created_paths:
            path.unlink(missing_ok=True)
        raise
    return new_records



def _preserve_compression(source: xr.DataArray, target: xr.DataArray) -> None:
    """Copy compatible NetCDF compression settings to an output variable."""
    for key in (
        "zlib", "complevel", "shuffle", "fletcher32", "chunksizes", "contiguous"
    ):
        target.encoding.pop(key, None)
    if not source.encoding.get("zlib", False):
        return
    target.encoding["zlib"] = True
    for key in ("complevel", "shuffle", "fletcher32"):
        if key in source.encoding:
            target.encoding[key] = source.encoding[key]
    chunks = source.encoding.get("chunksizes")
    if chunks is not None and len(chunks) == target.ndim:
        target.encoding["chunksizes"] = tuple(
            min(int(chunk), target.sizes[dimension])
            for chunk, dimension in zip(chunks, target.dims)
        )


def timestamp_string(value) -> str:
    """Return a metadata timestamp at second precision."""
    return np.datetime_as_string(np.datetime64(value), unit="s")
