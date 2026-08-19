import json

import numpy as np
import xarray as xr

from storage.ingest_data.standardize import (
    get_standard_var_name,
    standardize,
)


def test_standardizes_configured_variable_name():
    dataset = xr.Dataset({"sst": ("x", [1.0, 2.0])})
    record = {
        "repository": "copernicusclimatedatastore",
        "dataset": "era5_single_level",
        "variable": "sst",
    }

    standardized, variable_name = get_standard_var_name(dataset, record)

    assert variable_name == "sea_surface_temperature"
    assert "sea_surface_temperature" in standardized.data_vars
    assert "sst" not in standardized.variables


def test_standard_variable_name_can_already_match():
    dataset = xr.Dataset(
        {"sea_surface_temperature": ("x", [1.0, 2.0])}
    )
    record = {
        "repository": "noaancei",
        "dataset": "whoi_cdr",
        "variable": "sea_surface_temperature",
    }

    standardized, variable_name = get_standard_var_name(dataset, record)

    assert standardized.identical(dataset)
    assert variable_name == "sea_surface_temperature"


def test_standardize_renames_variable_and_preserves_compression(tmp_path):
    source_paths = []
    for timestamp in (0, 1):
        source_path = tmp_path / f"source-{timestamp}.nc"
        dataset = xr.Dataset(
            data_vars={
                "sst": (
                    ("valid_time", "latitude", "longitude"),
                    np.full((1, 2, 2), timestamp, dtype=np.float32),
                )
            },
            coords={
                "valid_time": (
                    "valid_time",
                    [timestamp],
                    {"standard_name": "time"},
                ),
                "latitude": (
                    "latitude",
                    [-10.0, 10.0],
                    {"standard_name": "latitude", "units": "degrees_north"},
                ),
                "longitude": (
                    "longitude",
                    [10.0, 20.0],
                    {"standard_name": "longitude", "units": "degrees_east"},
                ),
            },
        )
        dataset.to_netcdf(
            source_path,
            encoding={
                "sst": {
                    "zlib": True,
                    "complevel": 3,
                    "chunksizes": (1, 2, 2),
                }
            },
        )
        source_paths.append(str(source_path))

    output_directory = tmp_path / "standardized"
    metadata_path = output_directory / "metadata.jsonl"
    standardize(
        [
            {
                "repository": "copernicusclimatedatastore",
                "dataset": "era5_single_level",
                "variable": "sst",
                "file_paths": source_paths,
            }
        ],
        output_directory,
        metadata_path,
    )

    record = json.loads(metadata_path.read_text())
    assert record["variable"] == "sea_surface_temperature"
    with xr.open_dataset(record["file_path"]) as standardized:
        assert "sea_surface_temperature" in standardized.data_vars
        encoding = standardized["sea_surface_temperature"].encoding
        assert encoding["zlib"] is True
        assert encoding["complevel"] == 3
