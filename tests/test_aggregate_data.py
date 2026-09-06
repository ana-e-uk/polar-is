import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import xarray as xr

from polaris.config import ContainerScheme
from storage.ingest_data.aggregate_data import (
    aggregate_record,
    aggregate_records,
    eligible_temporal_resolutions,
    infer_native_temporal_resolution,
    spatially_aggregate,
    temporally_aggregate,
)


def _time_dataset(periods=24, frequency="1h"):
    timestamp = pd.date_range("2020-01-01", periods=periods, freq=frequency)
    values = np.arange(periods * 9, dtype=float).reshape(periods, 3, 3)
    return xr.Dataset(
        {
            "value": (("timestamp", "y", "x"), values),
            "time_flag": ("timestamp", np.arange(periods)),
            "cell_area": (("y", "x"), np.ones((3, 3))),
            "crs": 0,
        },
        coords={
            "timestamp": timestamp,
            "latitude": (("y", "x"), np.tile([0.0, 1.0, 2.0], (3, 1)).T),
            "longitude": (
                ("y", "x"),
                [[179.0, -179.0, -177.0]] * 3,
            ),
        },
    )


def test_temporal_outputs_are_never_finer_than_native():
    configured = ["1H", "3H", "1D", "1MS", "1YS"]
    assert eligible_temporal_resolutions("3H", configured) == [
        "3H",
        "1D",
        "1MS",
        "1YS",
    ]
    assert eligible_temporal_resolutions("1D", configured) == [
        "1D",
        "1MS",
        "1YS",
    ]


def test_native_resolution_is_inferred_from_timestamps():
    data = _time_dataset(4, "3h")
    assert infer_native_temporal_resolution(data["timestamp"], "1D") == "3H"


def test_temporal_aggregation_requires_complete_target_period():
    source = _time_dataset(24).assign_coords(
        expver=("timestamp", ["0001"] * 24)
    )
    complete = temporally_aggregate(source, "value", "1H", "1D", "mean")
    incomplete = temporally_aggregate(
        _time_dataset(23), "value", "1H", "1D", "mean"
    )
    assert complete.sizes["timestamp"] == 1
    assert incomplete.sizes["timestamp"] == 0
    np.testing.assert_allclose(
        complete["value"].values,
        _time_dataset(24)["value"].mean("timestamp").values[None, ...],
    )
    assert complete["time_flag"].item() == 0
    assert complete["expver"].item() == "0001"


def test_native_period_is_retained_without_resampling():
    native = _time_dataset(2, "1D")
    result = temporally_aggregate(native, "value", "1D", "1D", "mean")
    assert result.identical(native)


def test_month_and_year_require_complete_native_coverage():
    january = temporally_aggregate(
        _time_dataset(31, "1D"), "value", "1D", "1MS", "mean"
    )
    partial_january = temporally_aggregate(
        _time_dataset(30, "1D"), "value", "1D", "1MS", "mean"
    )
    leap_year = temporally_aggregate(
        _time_dataset(366, "1D"), "value", "1D", "1YS", "mean"
    )
    partial_leap_year = temporally_aggregate(
        _time_dataset(365, "1D"), "value", "1D", "1YS", "mean"
    )
    assert january.sizes["timestamp"] == 1
    assert partial_january.sizes["timestamp"] == 0
    assert leap_year.sizes["timestamp"] == 1
    assert partial_leap_year.sizes["timestamp"] == 0


def test_spatial_aggregation_pads_edges_and_handles_auxiliaries():
    data = _time_dataset(1)
    data["quality_flag"] = xr.DataArray(
        np.arange(9).reshape(3, 3),
        dims=("y", "x"),
        attrs={"flag_values": np.arange(9)},
    ).chunk({"y": 2, "x": 2})
    data["spatial_label"] = xr.DataArray(
        np.array(
            [["a", "b", "c"], ["d", "e", "f"], ["g", "h", "i"]]
        ),
        dims=("y", "x"),
    )
    data["value"].encoding.update(
        {"zlib": True, "complevel": 3, "chunksizes": (1, 2, 2)}
    )
    result = spatially_aggregate(data, "value", 2, "mean")
    assert result.sizes["y"] == 2
    assert result.sizes["x"] == 2
    assert result["crs"].item() == 0
    np.testing.assert_allclose(
        result["cell_area"].values,
        [[4.0, 2.0], [2.0, 1.0]],
    )
    np.testing.assert_array_equal(
        result["quality_flag"].values,
        [[0, 2], [6, 8]],
    )
    np.testing.assert_array_equal(
        result["spatial_label"].values,
        [["a", "c"], ["g", "i"]],
    )
    longitude = float(result["longitude"].isel(y=0, x=0))
    assert abs(abs(longitude) - 180.0) < 1e-6
    assert float(result["value"].isel(timestamp=0, y=1, x=1)) == 8.0
    assert result["value"].encoding["zlib"] is True
    assert result["value"].encoding["complevel"] == 3


def _settings(tmp_path, targets=("1H", "3H")):
    schemes = {}
    for factor in (1, 2, 4):
        name = f"capacity_{factor}"
        schemes[name] = ContainerScheme(
            name,
            factor,
            tmp_path / name,
            tmp_path / name / "metadata.jsonl",
            tmp_path / f"{name}.json",
        )
    return SimpleNamespace(
        aggregation_methods={"value": {"temporal": "mean", "spatial": "mean"}},
        temporal_aggregation_resolutions=targets,
        container_schemes=schemes,
        container_grid={
            "lon_min": 0,
            "lat_min": -90,
            "lon_size": 60,
            "lat_size": 30,
        },
    )


def test_every_capacity_time_combination_uses_write_blocks(tmp_path):
    source = tmp_path / "source.nc"
    _time_dataset(6).to_netcdf(source)
    record = {
        "dataset": "test",
        "variable": "value",
        "spatial_resolution": 1.0,
        "temporal_resolution": "1H",
        "file_path": str(source),
    }
    settings = _settings(tmp_path)
    calls = []

    def capture(data, record, scheme, **kwargs):
        calls.append(
            (
                scheme.name,
                kwargs["product_metadata"]["temporal_resolution"],
                kwargs["product_metadata"]["spatial_coarsening_factor"],
                data.sizes["timestamp"],
            )
        )
        return []

    with patch(
        "storage.ingest_data.aggregate_data.write_blocks",
        side_effect=capture,
    ):
        aggregate_record(record, settings=settings)

    assert calls == [
        ("capacity_1", "1H", 1, 6),
        ("capacity_2", "1H", 2, 6),
        ("capacity_4", "1H", 4, 6),
        ("capacity_1", "3H", 1, 2),
        ("capacity_2", "3H", 2, 2),
        ("capacity_4", "3H", 4, 2),
    ]


def test_small_end_to_end_hierarchy_writes_each_capacity_and_time(tmp_path):
    source = tmp_path / "source.nc"
    source_data = _time_dataset(6).assign_coords(
        longitude=(("y", "x"), np.full((3, 3), 10.0))
    )
    source_data.to_netcdf(source)
    record = {
        "repository": "test",
        "dataset": "test",
        "variable": "value",
        "coordinates": [-90, 90, 0, 360],
        "grid_type": "curvilinear",
        "spatial_resolution": 1.0,
        "temporal_resolution": "1H",
        "file_path": str(source),
    }
    settings = _settings(tmp_path)
    settings.container_grid.update({"lon_size": 180, "lat_size": 90})

    written = aggregate_record(record, settings=settings)

    assert len(written) == 6
    for factor, scheme in zip((1, 2, 4), settings.container_schemes.values()):
        records = [json.loads(line) for line in scheme.metadata.read_text().splitlines()]
        assert {item["temporal_resolution"] for item in records} == {"1H", "3H"}
        assert {item["spatial_coarsening_factor"] for item in records} == {factor}
        assert all(item["container"] == scheme.name for item in records)
        assert all(Path(item["file_path"]).is_file() for item in records)
        assert all(item["block_summary"]["var_min"] is not None for item in records)


def test_source_cleanup_occurs_only_after_all_records_succeed(tmp_path):
    first = tmp_path / "first.nc"
    second = tmp_path / "second.nc"
    first.touch()
    second.touch()
    records = [{"file_path": str(first)}, {"file_path": str(second)}]
    settings = _settings(tmp_path)

    with patch(
        "storage.ingest_data.aggregate_data.aggregate_record",
        side_effect=[[], RuntimeError("failure")],
    ):
        try:
            aggregate_records(records, settings=settings, delete_sources=True)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Simulated aggregation failure did not fail")
    assert first.exists() and second.exists()

    with patch(
        "storage.ingest_data.aggregate_data.aggregate_record",
        return_value=[],
    ):
        aggregate_records(records, settings=settings, delete_sources=True)
    assert not first.exists() and not second.exists()
