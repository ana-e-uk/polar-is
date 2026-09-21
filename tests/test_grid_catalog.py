from types import SimpleNamespace

import numpy as np
import pandas as pd
import xarray as xr

from storage.grid_topology import (
    add_grid_topology,
    canonical_grid,
    canonical_grid_id,
    ensure_grid_catalog,
)


def _rectilinear_grid(longitudes=(20.0, 24.0, 28.0)):
    data = xr.Dataset(
        {"value": (("timestamp", "y", "x"), np.zeros((1, 2, 3)))},
        coords={
            "timestamp": pd.date_range("2020-01-01", periods=1),
            "latitude": ("y", [10.0, 12.0]),
            "longitude": ("x", np.asarray(longitudes)),
        },
    )
    return add_grid_topology(data, "value", "rectilinear")[0]


def _projected_grid():
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
            "latitude": ("y", [70.135, 70.15]),
            "longitude": ("x", [340.592, 340.61, 340.63]),
        },
    )
    latitude, longitude = xr.broadcast(data["latitude"], data["longitude"])
    data = data.assign_coords(latitude=latitude, longitude=longitude)
    return add_grid_topology(data, "value", "curvilinear")[0]


def _settings(tmp_path):
    return SimpleNamespace(
        grids_dir=tmp_path / "catalogs" / "grids",
        grids_catalog=tmp_path / "catalogs" / "grids.jsonl",
    )


def test_identical_grid_geometry_has_one_stable_grid_id():
    first = canonical_grid(_rectilinear_grid())
    second = canonical_grid(_rectilinear_grid())
    different = canonical_grid(_rectilinear_grid((20.0, 24.0, 29.0)))

    assert canonical_grid_id(first) == canonical_grid_id(second)
    assert canonical_grid_id(first) != canonical_grid_id(different)


def test_descriptive_coordinate_attributes_do_not_split_grid_identity():
    first = canonical_grid(_rectilinear_grid())
    second = first.copy(deep=True)
    second["latitude"].attrs["long_name"] = "latitude from another provider"
    second["longitude"].attrs["source"] = "provider-specific label"
    second["cell_area"].attrs["long_name"] = "area of grid cell"

    assert canonical_grid_id(first) == canonical_grid_id(second)


def test_projection_attributes_are_part_of_grid_identity():
    first = canonical_grid(_projected_grid())
    second = first.copy(deep=True)
    second["crs"].attrs["longitude_of_central_meridian"] += 1

    assert canonical_grid_id(first) != canonical_grid_id(second)


def test_identical_grid_is_written_once(tmp_path):
    settings = _settings(tmp_path)

    first = ensure_grid_catalog(_rectilinear_grid(), settings=settings)
    second = ensure_grid_catalog(_rectilinear_grid(), settings=settings)

    assert first == second
    assert len(settings.grids_catalog.read_text().splitlines()) == 1
    assert len(list(settings.grids_dir.glob("*.nc"))) == 1


def test_projected_grid_survives_catalog_round_trip(tmp_path):
    settings = _settings(tmp_path)
    source = _projected_grid()
    record = ensure_grid_catalog(source, settings=settings)

    with xr.open_dataset(settings.grids_dir / f"{record.grid_id}.nc") as stored:
        np.testing.assert_allclose(stored["projection_x"], source["projection_x"])
        np.testing.assert_allclose(stored["projection_y"], source["projection_y"])
        np.testing.assert_allclose(stored["latitude"], source["latitude"])
        np.testing.assert_allclose(stored["longitude"], source["longitude"])
        assert stored["crs"].attrs["grid_mapping_name"] == (
            "lambert_conformal_conic"
        )
        assert stored["cell_area"].attrs["units"] == "m2"
