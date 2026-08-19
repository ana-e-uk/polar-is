"""Check data blocks are correct.

Checks:
    - Expected bucket directories are initialized and used.
    - Verify block is stored in correct bucket directory.
    - Confirm (y, x) values are all within correct bucket
    - Values outside bucket mask are NaN
"""
from pathlib import Path
import sys

import xarray as xr


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from polaris.config import get_settings
from storage.ingest_data.standardize import read_metadata
from storage.manage.space_buckets import (
    LAT_MIN,
    LAT_SIZE,
    LON_MIN,
    LON_SIZE,
    N_COLS,
    bucket_id_from_code,
    map_buckets,
)


def _block_records():
    metadata_path = get_settings().metadata_
    assert metadata_path.is_file(), f"Missing block metadata: {metadata_path}"

    records = read_metadata(metadata_path)
    assert records, f"No block records found in {metadata_path}"
    return records


def _canonical_bounds(bucket_code):
    row, column = divmod(bucket_code, N_COLS)
    return {
        "lat_min": LAT_MIN + row * LAT_SIZE,
        "lat_max": LAT_MIN + (row + 1) * LAT_SIZE,
        "lon_min": LON_MIN + column * LON_SIZE,
        "lon_max": LON_MIN + (column + 1) * LON_SIZE,
    }


def _spatial_data_variables(dataset):
    return {
        name: variable
        for name, variable in dataset.data_vars.items()
        if {"y", "x"}.issubset(variable.dims)
    }

def dirs_and_blocks_exist():
    """Check expected bucket directories exist and contain their blocks."""
    records = _block_records()
    data_directory = get_settings()._data
    expected_directories = {record["bucket_id"] for record in records}
    actual_directories = {
        path.name for path in data_directory.iterdir() if path.is_dir()
    }

    assert actual_directories == expected_directories, (
        f"Expected bucket directories {sorted(expected_directories)}, "
        f"found {sorted(actual_directories)}"
    )

    for record in records:
        block_path = Path(record["file_path"])
        assert block_path.parent.is_dir(), (
            f"Missing bucket directory: {block_path.parent}"
        )
        assert block_path.is_file(), f"Missing block file: {block_path}"

def verify_block_bucket():
    """Check block bucket_id matches the sub-directory the block is in."""
    for record in _block_records():
        bucket_code = record["bucket_code"]
        expected_id = bucket_id_from_code(bucket_code)
        block_path = Path(record["file_path"])

        assert record["bucket_id"] == expected_id, (
            f"Code {bucket_code} maps to {expected_id}, not "
            f"{record['bucket_id']}"
        )
        assert block_path.parent.name == expected_id, (
            f"Block {block_path} is stored under the wrong bucket directory"
        )

def cells_within_bucket():
    """Check every cell containing block data belongs to its bucket."""
    for record in _block_records():
        block_path = Path(record["file_path"])
        expected_code = record["bucket_code"]
        canonical_bounds = _canonical_bounds(expected_code)

        with xr.open_dataset(block_path) as block:
            bucket_codes = map_buckets(block)
            variable_name = record["variable"]
            assert variable_name in block.data_vars, (
                f"{block_path} does not contain {variable_name!r}"
            )

            variable = block[variable_name]
            non_spatial_dims = [
                dimension
                for dimension in variable.dims
                if dimension not in {"y", "x"}
            ]
            cells_with_data = variable.notnull()
            if non_spatial_dims:
                cells_with_data = cells_with_data.any(dim=non_spatial_dims)

            assert cells_with_data.any().compute().item(), (
                f"Block {block_path} contains no valid data"
            )
            wrong_bucket = cells_with_data & (bucket_codes != expected_code)
            assert not wrong_bucket.any().compute().item(), (
                f"Block {block_path} contains valid cells assigned to another bucket"
            )

        summary = record["block_summary"]
        for minimum_name in ("lat_min", "lon_min"):
            assert summary[minimum_name] >= canonical_bounds[minimum_name]
        for maximum_name in ("lat_max", "lon_max"):
            assert summary[maximum_name] <= canonical_bounds[maximum_name]

def mask_works():
    """Confirm values outside bucket mask are NaN."""
    for record in _block_records():
        block_path = Path(record["file_path"])
        expected_code = record["bucket_code"]

        with xr.open_dataset(block_path) as block:
            bucket_codes = map_buckets(block)
            outside_bucket = bucket_codes != expected_code
            spatial_variables = _spatial_data_variables(block)
            assert spatial_variables, (
                f"Block {block_path} has no spatial data variables"
            )

            for variable_name, variable in spatial_variables.items():
                outside_values = variable.where(outside_bucket)
                assert outside_values.isnull().all().compute().item(), (
                    f"{variable_name!r} in {block_path} has non-NaN values "
                    "outside its bucket mask"
                )


def main():
    checks = (
        dirs_and_blocks_exist,
        verify_block_bucket,
        cells_within_bucket,
        mask_works,
    )
    for check in checks:
        check()
        print(f"PASS: {check.__name__}")


if __name__ == "__main__":
    main()
