from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import xarray as xr

from storage.ingest_data.combine_data import (
    build_combined_records,
    combine_daily_arrays,
    daily_mean_with_coverage,
    regrid_daily_to_target,
    xesmf_grid,
)
from storage.grid_topology import add_rectilinear_bounds


def _field(timestamps, value, *, missing=()):
    values = np.full((len(timestamps), 2, 2), value, dtype=float)
    for time_index, y, x in missing:
        values[time_index, y, x] = np.nan
    return xr.DataArray(
        values,
        dims=("timestamp", "y", "x"),
        coords={"timestamp": timestamps},
        attrs={"units": "K"},
    )


def _rectilinear_dataset(timestamps, value, *, missing=()):
    data = _field(timestamps, value, missing=missing).to_dataset(
        name="sea_surface_temperature"
    )
    data = data.assign_coords(
        latitude=("y", [0.0, 0.25], {"standard_name": "latitude"}),
        longitude=("x", [0.0, 0.25], {"standard_name": "longitude"}),
    )
    return add_rectilinear_bounds(data)


def test_three_hour_daily_coverage_is_checked_per_cell():
    timestamps = pd.date_range("2020-01-01", periods=8, freq="3h")
    source = _field(
        timestamps,
        5.0,
        missing=[(0, 0, 0), (1, 0, 0), (0, 1, 1), (1, 1, 1), (2, 1, 1)],
    )

    daily = daily_mean_with_coverage(source, "3H", 0.75)

    assert daily.sizes["timestamp"] == 1
    assert daily.sel(y=0, x=0).item() == 5.0  # 6 of 8 samples
    assert np.isnan(daily.sel(y=1, x=1).item())  # only 5 of 8 samples
    assert daily.attrs["polaris_daily_required_samples"] == 6


def test_equal_weight_combination_uses_every_available_value():
    first = xr.DataArray(
        [[[2.0]], [[4.0]]],
        dims=("timestamp", "y", "x"),
        coords={"timestamp": pd.date_range("2020-01-01", periods=2)},
    )
    second = xr.DataArray(
        [[[6.0]], [[np.nan]]],
        dims=("timestamp", "y", "x"),
        coords={"timestamp": pd.date_range("2020-01-01", periods=2)},
    )

    combined, source_count = combine_daily_arrays([first, second], [1.0, 1.0])

    np.testing.assert_allclose(combined.values[:, 0, 0], [4.0, 4.0])
    np.testing.assert_array_equal(source_count.values[:, 0, 0], [2, 1])


def test_rectilinear_grid_asset_retains_bounds_and_cell_area():
    data = _rectilinear_dataset(pd.date_range("2020-01-01", periods=1), 1.0)

    grid = xesmf_grid(data)

    assert grid["lat_b"].shape == (3,)
    assert grid["lon_b"].shape == (3,)
    assert grid["cell_area"].dims == ("y", "x")
    assert bool((grid["cell_area"] > 0).all())
    assert grid["cell_area"].attrs["units"] == "m2"
    assert bool((grid["domain_mask"] == 1).all())


def test_regrid_operator_and_grid_assets_are_reused(tmp_path, monkeypatch):
    data = _rectilinear_dataset(pd.date_range("2020-01-01", periods=1), 1.0)
    calls = []

    class FakeRegridder:
        def __init__(self, source, target, method, filename, reuse_weights=False, **kwargs):
            calls.append(reuse_weights)
            if not reuse_weights:
                Path(filename).write_text("weights")

        def __call__(self, values, **kwargs):
            return values.assign_coords(
                crs=xr.DataArray(
                    0,
                    attrs={"grid_mapping_name": "lambert_conformal_conic"},
                ),
                source_only=xr.DataArray("discard me"),
            )

    fake_xesmf = SimpleNamespace(Regridder=FakeRegridder, __version__="test")
    monkeypatch.setattr(
        "storage.ingest_data.combine_data._load_xesmf", lambda: fake_xesmf
    )

    for _ in range(2):
        result = regrid_daily_to_target(
            data["sea_surface_temperature"],
            data,
            data,
            tmp_path,
            "bilinear",
        )
        assert result.shape == data["sea_surface_temperature"].shape
        assert "crs" not in result.coords
        assert "source_only" not in result.coords

    assert calls == [False, True]
    assert not (tmp_path / "grids").exists()
    assert len(list((tmp_path / "weights").glob("*.nc"))) == 1
    assert len(list((tmp_path / "weights").glob("*.json"))) == 1


def test_build_combined_daily_record_for_existing_era5_grid(tmp_path):
    era_path = tmp_path / "era.nc"
    whoi_path = tmp_path / "whoi.nc"
    era = _rectilinear_dataset(
        pd.date_range("2020-01-01", periods=24, freq="1h"), 2.0
    )
    whoi = _rectilinear_dataset(
        pd.date_range("2020-01-01", periods=8, freq="3h"),
        4.0,
        missing=[(0, 1, 1), (1, 1, 1), (2, 1, 1)],
    )
    era.to_netcdf(era_path)
    whoi.to_netcdf(whoi_path)
    records = [
        {
            "repository": "copernicusclimatedatastore",
            "dataset": "era5_single_level",
            "variable": "sea_surface_temperature",
            "spatial_resolution": 0.25,
            "temporal_resolution": "1H",
            "coordinates": [0, 0.25, 0, 0.25],
            "file_path": str(era_path),
        },
        {
            "repository": "noaancei",
            "dataset": "whoi_cdr",
            "variable": "sea_surface_temperature",
            "spatial_resolution": 0.25,
            "temporal_resolution": "3H",
            "coordinates": [0, 0.25, 0, 0.25],
            "file_path": str(whoi_path),
        },
    ]
    settings = SimpleNamespace(
        _standardized=tmp_path / "standardized",
        grids_dir=tmp_path / "catalogs" / "grids",
        grids_catalog=tmp_path / "catalogs" / "grids.jsonl",
        combined_dataset={
            "enabled": True,
            "repository": "polaris",
            "dataset": "combined",
            "display_name": "Combined — weighted mean of available datasets",
            "target_repository": "copernicusclimatedatastore",
            "target_dataset": "era5_single_level",
            "temporal_resolution": "1D",
            "minimum_daily_coverage": 0.75,
            "regridding_method": "bilinear",
            "cache_dir": tmp_path / "cache",
            "variables": ["sea_surface_temperature"],
            "default_weight": 1.0,
            "weights": {},
        },
    )

    def identity_regrid(values, source, target, cache_dir, method):
        return values.assign_coords(
            latitude=target["latitude"], longitude=target["longitude"]
        )

    output_records = build_combined_records(
        records, settings=settings, regrid=identity_regrid
    )

    assert len(output_records) == 1
    record = output_records[0]
    assert record["repository"] == "polaris"
    assert record["dataset"] == "combined"
    assert record["temporal_resolution"] == "1D"
    with xr.open_dataset(record["file_path"]) as combined:
        np.testing.assert_allclose(
            combined["sea_surface_temperature"].isel(timestamp=0, y=0, x=0),
            3.0,
        )
        assert combined["source_count"].isel(timestamp=0, y=0, x=0).item() == 2
        # WHOI has only five valid samples in this cell, so ERA5 remains alone.
        assert combined["sea_surface_temperature"].isel(
            timestamp=0, y=1, x=1
        ).item() == 2.0
        assert combined["source_count"].isel(timestamp=0, y=1, x=1).item() == 1
        assert combined["cell_area"].attrs["units"] == "m2"
