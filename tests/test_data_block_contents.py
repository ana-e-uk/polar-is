"""Check data blocks are correct.

Checks:
    - Expected container directories are initialized and used.
    - Verify each block is stored in its correct container directory.
    - Confirm (y, x) values are all within the correct container.
    - Values outside the container mask are NaN.
"""
from pathlib import Path
import sys

import xarray as xr


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from polaris.config import get_settings
from storage.ingest_data.standardize import read_metadata
from storage.ingest_data.make_data_blocks import read_container_definitions
from storage.manage.space_containers import (
    container_id_from_code,
    grid_for_scheme,
    map_containers,
)


SCHEME = get_settings().container_schemes["capacity_1"]
GRID = grid_for_scheme(SCHEME)


def _block_records():
    metadata_path = SCHEME.metadata
    assert metadata_path.is_file(), f"Missing block metadata: {metadata_path}"

    records = read_metadata(metadata_path)
    assert records, f"No block records found in {metadata_path}"
    return records


def _canonical_bounds(container_code):
    row, column = divmod(container_code, GRID.n_cols)
    return {
        "lat_min": GRID.lat_min + row * GRID.lat_size,
        "lat_max": min(GRID.lat_min + (row + 1) * GRID.lat_size, GRID.lat_max),
        "lon_min": GRID.lon_min + column * GRID.lon_size,
        "lon_max": min(GRID.lon_min + (column + 1) * GRID.lon_size, GRID.lon_max),
    }


def _spatial_data_variables(dataset):
    return {
        name: variable
        for name, variable in dataset.data_vars.items()
        if {"y", "x"}.issubset(variable.dims)
    }

def dirs_and_blocks_exist():
    """Check expected container directories exist and contain their blocks."""
    records = _block_records()
    data_directory = SCHEME.data_dir
    expected_directories = set(read_container_definitions(SCHEME.definitions))
    actual_directories = {
        path.name for path in data_directory.iterdir() if path.is_dir()
    }

    assert actual_directories == expected_directories, (
        f"Expected container directories {sorted(expected_directories)}, "
        f"found {sorted(actual_directories)}"
    )

    for record in records:
        block_path = Path(record["file_path"])
        assert block_path.parent.is_dir(), (
            f"Missing container directory: {block_path.parent}"
        )
        assert block_path.is_file(), f"Missing block file: {block_path}"

def verify_block_container():
    """Check container_id matches the sub-directory containing the block."""
    for record in _block_records():
        container_code = record["container_code"]
        expected_id = container_id_from_code(container_code, GRID)
        block_path = Path(record["file_path"])

        assert record["container_id"] == expected_id, (
            f"Code {container_code} maps to {expected_id}, not "
            f"{record['container_id']}"
        )
        assert block_path.parent.name == expected_id, (
            f"Block {block_path} is stored under the wrong container directory"
        )

def cells_within_container():
    """Check every cell containing block data belongs to its container."""
    for record in _block_records():
        block_path = Path(record["file_path"])
        expected_code = record["container_code"]
        canonical_bounds = _canonical_bounds(expected_code)

        with xr.open_dataset(block_path) as block:
            container_codes = map_containers(block, GRID)
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
            wrong_container = cells_with_data & (container_codes != expected_code)
            assert not wrong_container.any().compute().item(), (
                f"Block {block_path} contains valid cells assigned to another container"
            )

        summary = record["block_summary"]
        for minimum_name in ("lat_min", "lon_min"):
            assert summary[minimum_name] >= canonical_bounds[minimum_name]
        for maximum_name in ("lat_max", "lon_max"):
            assert summary[maximum_name] <= canonical_bounds[maximum_name]

def mask_works():
    """Confirm values outside the container mask are NaN."""
    for record in _block_records():
        block_path = Path(record["file_path"])
        expected_code = record["container_code"]

        with xr.open_dataset(block_path) as block:
            container_codes = map_containers(block, GRID)
            outside_container = container_codes != expected_code
            spatial_variables = _spatial_data_variables(block)
            assert spatial_variables, (
                f"Block {block_path} has no spatial data variables"
            )

            for variable_name, variable in spatial_variables.items():
                outside_values = variable.where(outside_container)
                assert outside_values.isnull().all().compute().item(), (
                    f"{variable_name!r} in {block_path} has non-NaN values "
                    "outside its container mask"
                )


def main():
    checks = (
        dirs_and_blocks_exist,
        verify_block_container,
        cells_within_container,
        mask_works,
    )
    for check in checks:
        check()
        print(f"PASS: {check.__name__}")


if __name__ == "__main__":
    main()
