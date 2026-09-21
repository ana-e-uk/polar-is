import json

import numpy as np
import pandas as pd
import xarray as xr

from storage.ingest_data.standardize import (
    get_standard_var_name,
    remove_singleton_source_coordinates,
    standardize,
)
from storage.grid_topology import add_grid_topology


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


def test_singleton_source_coordinate_becomes_provenance_attribute():
    data = xr.Dataset(
        {"value": (("number", "timestamp", "y", "x"), np.ones((1, 1, 1, 1)))},
        coords={
            "number": [0],
            "timestamp": pd.date_range("2020-01-01", periods=1),
            "latitude": ("y", [10.0]),
            "longitude": ("x", [20.0]),
        },
    )

    result = remove_singleton_source_coordinates(data)

    assert "number" not in result.coords
    assert "number" not in result.dims
    assert result.attrs["polaris_source_coordinate_number"] == 0


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


def test_native_grid_adds_rectilinear_bounds_without_per_cell_indices():
    data = xr.Dataset(
        {"value": (("timestamp", "y", "x"), np.zeros((1, 2, 3)))},
        coords={
            "timestamp": pd.date_range("2020-01-01", periods=1),
            "latitude": ("y", [10.0, 12.0]),
            "longitude": ("x", [20.0, 24.0, 28.0]),
        },
    )
    result, grid_type = add_grid_topology(data, "value", "rectilinear")

    assert grid_type == "rectilinear"
    assert "source_y_index" not in result.coords
    assert "source_x_index" not in result.coords
    assert "grid_y_index" not in result.coords
    assert "grid_x_index" not in result.coords
    np.testing.assert_allclose(result["latitude_bounds"], [[9, 11], [11, 13]])
    np.testing.assert_allclose(
        result["longitude_bounds"], [[18, 22], [22, 26], [26, 30]]
    )
    assert "y" not in result.coords
    assert "x" not in result.coords


def test_carra_topology_creates_projected_coordinates_and_cf_mapping():
    attrs = {
        "GRIB_gridType": "lambert",
        "GRIB_Latin1InDegrees": 80.0,
        "GRIB_Latin2InDegrees": 80.0,
        "GRIB_LoVInDegrees": 326.0,
        "GRIB_LaDInDegrees": 80.0,
        "GRIB_DxInMetres": 2500.0,
        "GRIB_DyInMetres": 2500.0,
        "GRIB_iScansNegatively": 0,
        "GRIB_jScansPositively": 1,
        "GRIB_latitudeOfFirstGridPointInDegrees": 70.135,
        "GRIB_longitudeOfFirstGridPointInDegrees": 340.592,
    }
    data = xr.Dataset(
        {"value": (("timestamp", "y", "x"), np.zeros((1, 2, 3)), attrs)},
        coords={
            "timestamp": pd.date_range("2020-01-01", periods=1),
            "latitude": (("y", "x"), np.full((2, 3), 70.135)),
            "longitude": (("y", "x"), np.full((2, 3), 340.592)),
        },
    )
    result, grid_type = add_grid_topology(data, "value", "curvilinear")

    assert grid_type == "projected"
    np.testing.assert_allclose(np.diff(result["projection_x"]), 2500.0)
    np.testing.assert_allclose(np.diff(result["projection_y"]), 2500.0)
    assert result["projection_x"].attrs["standard_name"] == "projection_x_coordinate"
    assert result["projection_y"].attrs["standard_name"] == "projection_y_coordinate"
    assert result["crs"].attrs["grid_mapping_name"] == "lambert_conformal_conic"
    assert "crs_wkt" in result["crs"].attrs
    assert result["value"].attrs["grid_mapping"] == "crs"
