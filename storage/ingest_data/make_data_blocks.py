"""Split standardized data into blocks.

Each cell in a dataset grid will be classified into a bucket
based on the bucket the cell center falls into. All the cells
corresponding to one bucket will be stored together in one
file. This group of cells is called a block. A dataset may
have multiple blocks. 
"""
import json
import os
from pathlib import Path
import shutil
import tempfile
from numbers import Real

import numpy as np
import xarray as xr

from storage.manage.space_buckets import (
    bucket_id_from_code,
    map_buckets,
    normalize_lon_to_bucket_grid,
)
from storage.ingest_data.standardize import (
    read_metadata,
    unique_output_path,
    write_metadata,
)

from polaris.config import get_settings


def make_block_record(
    record, bucket_code: int, bucket_id: str, block_summary: dict, path: Path
):
    """Add block-specific spatial and storage fields to a record."""
    return {
        **record,
        "bucket_code": bucket_code,
        "bucket_id": bucket_id,
        "block_summary": block_summary,
        "file_path": str(path),
    }


def _finite_scalar_or_none(value):
    """Convert an Xarray scalar to a JSON-safe Python scalar."""
    scalar = value.compute().item()
    if isinstance(scalar, Real) and not np.isfinite(scalar):
        return None
    return scalar


def block_bounds_and_extrema(
    data: xr.Dataset, mask: xr.DataArray, variable: str
) -> dict:
    """Return the loose lon/lat envelope of the selected cell centers
    and the variable maxima.
    """
    latitude, longitude = xr.broadcast(
        data["latitude"], data["longitude"],
    )
    latitude = latitude.transpose("y", "x")
    longitude = normalize_lon_to_bucket_grid(
        longitude.transpose("y", "x")
    )

    selected_latitude = latitude.where(mask)
    selected_longitude = longitude.where(mask)
    selected_values = data[variable].where(mask)

    bounds = {
        "lat_min": selected_latitude.min().compute().item(),
        "lat_max": selected_latitude.max().compute().item(),
        "lon_min": selected_longitude.min().compute().item(),
        "lon_max": selected_longitude.max().compute().item(),
        "var_min": _finite_scalar_or_none(
            selected_values.min(skipna=True)
        ),
        "var_max": _finite_scalar_or_none(
            selected_values.max(skipna=True)
        ),
    }

    return bounds


def spatially_crop_block(
    data: xr.Dataset, mask: xr.DataArray
) -> xr.Dataset:
    """Crop to a mask's envelope and mask only spatial data variables."""
    y_indices = np.flatnonzero(mask.any(dim="x").values)
    x_indices = np.flatnonzero(mask.any(dim="y").values)
    if not len(y_indices) or not len(x_indices):
        raise ValueError("Cannot create a block from an empty mask")

    y_slice = slice(y_indices[0], y_indices[-1] + 1)
    x_slice = slice(x_indices[0], x_indices[-1] + 1)
    block = data.isel(y=y_slice, x=x_slice).copy()
    block_mask = mask.isel(y=y_slice, x=x_slice)

    for variable_name, variable in block.data_vars.items():
        if {"y", "x"}.issubset(variable.dims):
            block[variable_name] = variable.where(block_mask)

        _preserve_compression(
            source=data[variable_name],
            target=block[variable_name],
        )

    return block


def _preserve_compression(
    source: xr.DataArray, target: xr.DataArray
) -> None:
    """Copy compatible NetCDF compression settings to a cropped variable."""
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

    source_chunks = source.encoding.get("chunksizes")
    if source_chunks is not None and len(source_chunks) == target.ndim:
        target.encoding["chunksizes"] = tuple(
            min(int(chunk_size), target.sizes[dimension])
            for chunk_size, dimension in zip(source_chunks, target.dims)
        )


def _write_netcdf_atomically(block: xr.Dataset, output_path: Path) -> None:
    """Write a complete NetCDF file before exposing its final filename."""
    temporary_path = output_path.with_name(output_path.name + ".partial")
    try:
        block.to_netcdf(temporary_path)
        temporary_path.replace(output_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _append_metadata_atomically(metadata_path: Path, records: list) -> None:
    """Atomically append records without risking a partial metadata update."""
    metadata_path = Path(metadata_path)
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


def _read_bucket_definitions(buckets_path: Path) -> dict:
    """Read and minimally validate the canonical bucket definitions."""
    buckets_path = Path(buckets_path)
    with buckets_path.open(encoding="utf-8") as file:
        buckets = json.load(file)

    if not isinstance(buckets, dict) or not buckets:
        raise ValueError(f"Invalid or empty bucket definitions: {buckets_path}")
    return buckets


def update_bucket_file_counts(out_dir, buckets_path) -> None:
    """Atomically refresh each bucket's derived NetCDF file count."""
    out_dir = Path(out_dir)
    buckets_path = Path(buckets_path)
    buckets = _read_bucket_definitions(buckets_path)

    for bucket_id, bucket in buckets.items():
        if not isinstance(bucket, dict):
            raise ValueError(f"Invalid definition for bucket {bucket_id!r}")

        bucket_directory = out_dir / bucket_id
        bucket["data"] = (
            sum(
                path.is_file()
                for path in bucket_directory.glob("*.nc")
            )
            if bucket_directory.is_dir()
            else 0
        )

    buckets_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=buckets_path.parent,
        prefix=f".{buckets_path.name}.",
        suffix=".partial",
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)

    try:
        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(buckets, file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        temporary_path.replace(buckets_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def make_data_blocks(
    records,
    out_dir,
    metadata_path,
    buckets_path=None,
):
    if buckets_path is None:
        buckets_path = get_settings().buckets_
    buckets_path = Path(buckets_path)
    available_bucket_ids = set(_read_bucket_definitions(buckets_path))

    block_metadata = []
    created_paths = []

    try:
        # For each standardized file
        for record in records:
            file_path = record["file_path"]

            # All blocks retain the standardized dataset metadata
            base_record = {**record}
            base_record.pop("file_path")
            if "coordinates" in base_record:
                base_record["dataset_bounds"] = base_record.pop("coordinates")
            record_variable = record["variable"]

            with xr.open_dataset(file_path) as data:
                bucket_codes_mask = map_buckets(data)

                for raw_bucket_code in np.unique(bucket_codes_mask.values):
                    bucket_code = int(raw_bucket_code)
                    bucket_id = bucket_id_from_code(bucket_code)
                    if bucket_id not in available_bucket_ids:
                        raise ValueError(
                            f"Bucket {bucket_id!r} is missing from {buckets_path}"
                        )
                    mask = bucket_codes_mask == bucket_code

                    block_summary = block_bounds_and_extrema(
                        data=data,
                        mask=mask,
                        variable=record_variable,
                    )
                    block = spatially_crop_block(data, mask)

                    bucket_directory = Path(out_dir, bucket_id)
                    output_path = unique_output_path(
                        directory=bucket_directory,
                        unique_type="random",
                    )
                    _write_netcdf_atomically(block, output_path)
                    created_paths.append(output_path)

                    block_metadata.append(
                        make_block_record(
                            record=base_record,
                            bucket_code=bucket_code,
                            bucket_id=bucket_id,
                            block_summary=block_summary,
                            path=output_path,
                        )
                    )

        _append_metadata_atomically(metadata_path, block_metadata)
    except BaseException:
        for created_path in created_paths:
            created_path.unlink(missing_ok=True)
        raise

    # Counts are derived after block files and metadata are committed.
    try:
        update_bucket_file_counts(out_dir, buckets_path)
    except Exception as error:
        raise RuntimeError(
            "Block files and metadata committed successfully, but bucket file "
            "counts could not be refreshed. Do not rerun ingestion; call "
            "update_bucket_file_counts() after resolving the count error."
        ) from error

if __name__ == "__main__":

    settings = get_settings()
    metadata = settings.standardized_data_
    records = read_metadata(metadata)

    data_dir = settings._data
    metadata_path = settings.metadata_

    make_data_blocks(records, data_dir, metadata_path)
