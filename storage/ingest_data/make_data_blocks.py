"""Split one native-grid dataset product into spatial-container blocks."""

from __future__ import annotations

import hashlib
import json
from numbers import Real
import os
from pathlib import Path
import shutil
import tempfile

import numpy as np
import xarray as xr

from polaris.config import ContainerScheme, get_settings
from storage.ingest_data.standardize import read_metadata, write_metadata
from storage.manage.space_containers import (
    ContainerGrid,
    container_id_from_code,
    ensure_container_scheme,
    map_containers,
    normalize_longitude,
)


METADATA_SCHEMA_VERSION = 2
AGGREGATION_VERSION = 1


def _finite_scalar_or_none(value):
    scalar = value.compute().item()
    if isinstance(scalar, Real) and not np.isfinite(scalar):
        return None
    return scalar


def block_bounds_and_extrema(
    data: xr.Dataset,
    mask: xr.DataArray,
    variable: str,
    grid: ContainerGrid,
) -> dict:
    """Return a loose cell-center envelope and scientific-variable extrema."""
    latitude, longitude = xr.broadcast(data["latitude"], data["longitude"])
    latitude = latitude.transpose("y", "x")
    longitude = normalize_longitude(longitude.transpose("y", "x"), grid)
    selected_latitude = latitude.where(mask)
    selected_longitude = longitude.where(mask)
    selected_values = data[variable].where(mask)
    return {
        "lat_min": selected_latitude.min().compute().item(),
        "lat_max": selected_latitude.max().compute().item(),
        "lon_min": selected_longitude.min().compute().item(),
        "lon_max": selected_longitude.max().compute().item(),
        "var_min": _finite_scalar_or_none(selected_values.min(skipna=True)),
        "var_max": _finite_scalar_or_none(selected_values.max(skipna=True)),
    }


def _preserve_compression(source: xr.DataArray, target: xr.DataArray) -> None:
    """Copy compatible NetCDF compression settings to an output variable."""
    for key in (
        "zlib",
        "complevel",
        "shuffle",
        "fletcher32",
        "chunksizes",
        "contiguous",
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


def spatially_crop_block(data: xr.Dataset, mask: xr.DataArray) -> xr.Dataset:
    """Crop to a mask envelope and mask variables containing both y and x."""
    y_indices = np.flatnonzero(mask.any(dim="x").values)
    x_indices = np.flatnonzero(mask.any(dim="y").values)
    if not len(y_indices) or not len(x_indices):
        raise ValueError("Cannot create a block from an empty mask")
    y_slice = slice(y_indices[0], y_indices[-1] + 1)
    x_slice = slice(x_indices[0], x_indices[-1] + 1)
    block = data.isel(y=y_slice, x=x_slice).copy()
    block_mask = mask.isel(y=y_slice, x=x_slice)
    for name, variable in block.data_vars.items():
        if {"y", "x"}.issubset(variable.dims):
            block[name] = variable.where(block_mask)
        _preserve_compression(data[name], block[name])
    return block


def _write_netcdf_atomically(block: xr.Dataset, output_path: Path) -> None:
    temporary_path = output_path.with_name(output_path.name + ".partial")
    try:
        block.to_netcdf(temporary_path)
        temporary_path.replace(output_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _append_metadata_atomically(metadata_path: Path, records: list[dict]) -> None:
    if not records:
        return
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=metadata_path.parent,
        prefix=f".{metadata_path.name}.",
        suffix=".partial",
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        if metadata_path.exists():
            shutil.copyfile(metadata_path, temporary_path)
        write_metadata(temporary_path, records)
        temporary_path.replace(metadata_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def read_container_definitions(path: Path) -> dict[str, dict]:
    with Path(path).open(encoding="utf-8") as file:
        definitions = json.load(file)
    if not isinstance(definitions, dict) or not definitions:
        raise ValueError(f"Invalid or empty container definitions: {path}")
    return definitions


def update_container_file_counts(scheme: ContainerScheme) -> None:
    """Atomically refresh direct NetCDF counts for one capacity."""
    definitions = read_container_definitions(scheme.definitions)
    for container_id, definition in definitions.items():
        if not isinstance(definition, dict):
            raise ValueError(f"Invalid definition for {container_id!r}")
        directory = scheme.data_dir / container_id
        definition["data"] = (
            sum(path.is_file() for path in directory.glob("*.nc"))
            if directory.is_dir()
            else 0
        )
    scheme.definitions.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=scheme.definitions.parent,
        prefix=f".{scheme.definitions.name}.",
        suffix=".partial",
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(definitions, file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        temporary_path.replace(scheme.definitions)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _block_id(value: dict) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.blake2b(encoded, digest_size=16).hexdigest()


def _base_block_record(record: dict, product: dict) -> dict:
    source_path = record.get("file_path")
    base = {**record}
    base.pop("file_path", None)
    if "coordinates" in base:
        base["dataset_bounds"] = base.pop("coordinates")
    source_paths = product.get("source_file_paths")
    if source_paths is None:
        source_paths = [source_path] if source_path is not None else []
    return {
        **base,
        **product,
        "metadata_schema_version": METADATA_SCHEMA_VERSION,
        "aggregation_version": AGGREGATION_VERSION,
        "source_file_paths": [str(path) for path in source_paths],
    }


def _block_record(
    base_record: dict,
    scheme: ContainerScheme,
    container_code: int,
    container_id: str,
    block_summary: dict,
    path: Path,
) -> dict:
    identity = {
        **base_record,
        "container": scheme.name,
        "container_code": container_code,
        "container_id": container_id,
    }
    return {
        **identity,
        "block_id": _block_id(identity),
        "block_summary": block_summary,
        "file_path": str(path),
    }


def _default_product_metadata(record: dict, data: xr.Dataset) -> dict:
    from storage.ingest_data.aggregate_data import (
        infer_native_temporal_resolution,
    )

    temporal_resolution = infer_native_temporal_resolution(
        data["timestamp"], record.get("temporal_resolution")
    )
    spatial_resolution = record.get("spatial_resolution")
    timestamps = data.get("timestamp")
    time_start = str(timestamps.values[0]) if timestamps is not None else None
    time_end = str(timestamps.values[-1]) if timestamps is not None else None
    return {
        "product_type": "native",
        "native_temporal_resolution": temporal_resolution,
        "temporal_resolution": temporal_resolution,
        "native_spatial_resolution": spatial_resolution,
        "spatial_resolution": spatial_resolution,
        "spatial_coarsening_factor": 1,
        "temporal_aggregation_method": None,
        "spatial_aggregation_method": None,
        "aggregation_order": "temporal_then_spatial",
        "time_start": time_start,
        "time_end": time_end,
    }


def write_blocks(
    data: xr.Dataset,
    record: dict,
    scheme: ContainerScheme,
    *,
    grid: ContainerGrid | None = None,
    product_metadata: dict | None = None,
) -> list[dict]:
    """Write one dataset product through the common container-block path."""
    grid = grid or ensure_container_scheme(scheme)
    definitions = read_container_definitions(scheme.definitions)
    available_ids = set(definitions)
    variable = record["variable"]
    if variable not in data.data_vars:
        raise ValueError(f"Scientific variable {variable!r} is missing")
    product = product_metadata or _default_product_metadata(record, data)
    base_record = _base_block_record(record, product)
    codes = map_containers(data, grid)
    existing_records = (
        read_metadata(scheme.metadata) if scheme.metadata.exists() else []
    )
    existing_by_id = {
        item["block_id"]: item
        for item in existing_records
        if "block_id" in item
    }
    created_paths: list[Path] = []
    new_records: list[dict] = []
    try:
        for raw_code in np.unique(codes.values):
            code = int(raw_code)
            container_id = container_id_from_code(code, grid)
            if container_id not in available_ids:
                raise ValueError(
                    f"Container {container_id!r} is missing from "
                    f"{scheme.definitions}"
                )
            mask = codes == code
            summary = block_bounds_and_extrema(data, mask, variable, grid)
            provisional = _block_record(
                base_record,
                scheme,
                code,
                container_id,
                summary,
                Path("pending"),
            )
            block_id = provisional["block_id"]
            if block_id in existing_by_id:
                existing_path = Path(existing_by_id[block_id]["file_path"])
                if not existing_path.is_file():
                    raise FileNotFoundError(
                        f"Metadata for {block_id} points to missing "
                        f"block {existing_path}"
                    )
                continue
            directory = scheme.data_dir / container_id
            directory.mkdir(parents=True, exist_ok=True)
            output_path = directory / f"{block_id}.nc"
            if output_path.exists():
                raise FileExistsError(
                    f"Orphan block exists without metadata: {output_path}"
                )
            block = spatially_crop_block(data, mask)
            _write_netcdf_atomically(block, output_path)
            created_paths.append(output_path)
            provisional["file_path"] = str(output_path)
            new_records.append(provisional)
        _append_metadata_atomically(scheme.metadata, new_records)
    except BaseException:
        for path in created_paths:
            path.unlink(missing_ok=True)
        raise
    try:
        update_container_file_counts(scheme)
    except Exception as error:
        raise RuntimeError(
            "Block files and metadata committed, but container counts could "
            "not be refreshed. Repair counts rather than rerunning ingestion."
        ) from error
    return new_records


def make_data_blocks(
    records: list[dict],
    scheme: ContainerScheme | None = None,
) -> list[dict]:
    """Write native-resolution capacity-1 blocks for standardized records."""
    if scheme is None:
        scheme = get_settings().container_schemes["capacity_1"]
    grid = ensure_container_scheme(scheme)
    results = []
    for record in records:
        with xr.open_dataset(record["file_path"]) as data:
            results.extend(write_blocks(data, record, scheme, grid=grid))
    return results


if __name__ == "__main__":
    settings = get_settings()
    make_data_blocks(read_metadata(settings.standardized_data_))
