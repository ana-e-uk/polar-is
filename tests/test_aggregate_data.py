import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from storage.ingest_data.aggregate_data import (
    AGGREGATE_STATISTICS,
    add_aggregate_statistics,
    aggregate_record,
    aggregate_records,
    combined_product_policy,
    infer_native_temporal_resolution,
    product_policy,
    spatially_aggregate,
    temporally_aggregate,
)
from storage.ingest_data.product_partitions import (
    _chunk_encoding,
    write_product_partitions,
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


def test_product_policy_retains_source_and_only_coarser_products():
    assert [
        (product.time_unit, product.coarseness_factor)
        for product in product_policy("1H")
    ] == [
        ("Source", 1),
        ("Day", 1),
        ("Month", 1),
        ("Month", 2),
        ("Year", 1),
        ("Year", 2),
    ]
    assert [
        (product.time_unit, product.coarseness_factor)
        for product in product_policy("3H")
    ] == [
        ("Source", 1),
        ("Day", 1),
        ("Month", 1),
        ("Month", 2),
        ("Year", 1),
        ("Year", 2),
    ]
    assert [
        (product.time_unit, product.coarseness_factor)
        for product in product_policy("1MS")
    ] == [
        ("Source", 1),
        ("Year", 1),
        ("Year", 2),
    ]


def test_product_policy_rejects_weekly_source_data():
    try:
        product_policy("1W")
    except ValueError as error:
        assert "Weekly source data is unsupported" in str(error)
    else:
        raise AssertionError("Weekly source data was accepted")


def test_product_chunks_bound_spatial_reads():
    data = xr.Dataset({
        "value": (
            ("timestamp", "y", "x"),
            np.zeros((2, 256, 512), dtype=np.float32),
        ),
    })

    chunks = _chunk_encoding(data, 256 * 1024)["value"]["chunksizes"]

    assert chunks == (2, 128, 256)
    assert np.prod(chunks) * data["value"].dtype.itemsize <= 256 * 1024


def test_combined_policy_materializes_daily_monthly_and_yearly_products():
    assert [
        (product.time_unit, product.coarseness_factor)
        for product in combined_product_policy()
    ] == [
        ("Day", 1),
        ("Month", 1),
        ("Month", 2),
        ("Year", 1),
        ("Year", 2),
    ]


def test_source_count_uses_maximum_contributors_when_aggregating():
    data = add_aggregate_statistics(_time_dataset(24), "value")
    data["source_count"] = xr.DataArray(
        np.arange(24 * 3 * 3, dtype=np.int16).reshape(24, 3, 3) % 4,
        dims=("timestamp", "y", "x"),
    )
    daily = temporally_aggregate(data, "value", "1H", "1D", "mean")
    coarsened = spatially_aggregate(daily, "value", 2, "mean")

    assert daily["source_count"].dtype == np.int16
    assert daily["source_count"].max().item() == 3
    assert coarsened["source_count"].dtype == np.int16
    assert coarsened["source_count"].max().item() == 3


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


def test_complete_midpoint_timestamps_are_accepted():
    source = _time_dataset(8, "3h").assign_coords(
        timestamp=pd.date_range("2020-01-01T01:30", periods=8, freq="3h")
    )
    complete = temporally_aggregate(source, "value", "3H", "1D", "mean")

    assert complete.sizes["timestamp"] == 1
    assert complete["timestamp"].dt.hour.item() == 0


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


def test_spatial_aggregation_uses_local_positions_without_index_coordinates():
    data = _time_dataset(1)
    result = spatially_aggregate(data, "value", 2, "mean")

    assert all(
        name not in result.coords
        for name in (
            "source_y_index",
            "source_x_index",
            "source_y_start",
            "source_y_stop",
            "source_x_start",
            "source_x_stop",
            "grid_y_index",
            "grid_x_index",
        )
    )
    assert result.attrs["polaris_coarseness_factor"] == 2


def test_spatial_mean_uses_area_weights_and_keeps_statistics():
    data = xr.Dataset(
        {"value": (("timestamp", "y", "x"), [[[0.0, 10.0]]])},
        coords={
            "timestamp": pd.date_range("2020-01-01", periods=1),
            "latitude": (("y", "x"), [[0.0, 60.0]]),
            "longitude": (("y", "x"), [[0.0, 1.0]]),
        },
    )
    result = spatially_aggregate(
        add_aggregate_statistics(data, "value"),
        "value",
        2,
        "mean",
    )

    np.testing.assert_allclose(result["value"], [[[10.0 / 3.0]]])
    np.testing.assert_allclose(result["polaris_weighted_sum"], [[[5.0]]])
    np.testing.assert_allclose(result["polaris_weight_sum"], [[[1.5]]])
    assert result["polaris_weight_sum"].dims == ("timestamp", "y", "x")
    assert result["polaris_min"].item() == 0.0
    assert result["polaris_max"].item() == 10.0


def _settings(tmp_path):
    return SimpleNamespace(
        aggregation_methods={"value": {"temporal": "mean", "spatial": "mean"}},
        grids_dir=tmp_path / "catalogs" / "grids",
        grids_catalog=tmp_path / "catalogs" / "grids.jsonl",
        datasets_catalog=tmp_path / "catalogs" / "datasets.jsonl",
        bucket_lookup_dir=tmp_path / "bucket_lookup",
        products_dir=tmp_path / "products",
        product_index=tmp_path / "metadata.jsonl",
        container_grid={
            "lon_min": 0,
            "lat_min": -90,
            "lon_size": 60,
            "lat_size": 30,
        },
        combined_dataset={"repository": "polaris", "dataset": "combined"},
    )


def test_aggregation_path_uses_reduced_product_policy(tmp_path):
    source = tmp_path / "source.nc"
    source_data = _time_dataset(366, "1D").drop_vars(
        ["latitude", "longitude"]
    ).assign_coords(
        latitude=("y", [0.0, 1.0, 2.0]),
        longitude=("x", [10.0, 11.0, 12.0]),
    )
    source_data.to_netcdf(source)
    record = {
        "dataset": "test",
        "variable": "value",
        "spatial_resolution": 1.0,
        "temporal_resolution": "1D",
        "grid_type": "rectilinear",
        "file_path": str(source),
    }
    settings = _settings(tmp_path)
    calls = []

    def capture(data, record, **kwargs):
        calls.append(
            (
                kwargs["time_unit"],
                kwargs["temporal_resolution"],
                kwargs["coarseness_factor"],
                data.sizes["timestamp"],
            )
        )
        return []

    with patch(
        "storage.ingest_data.aggregate_data.write_product_partitions",
        side_effect=capture,
    ):
        aggregate_record(record, settings=settings)

    assert calls == [
        ("Source", "1D", 1, 366),
        ("Month", "1MS", 1, 12),
        ("Month", "1MS", 2, 12),
        ("Year", "1YS", 1, 1),
        ("Year", "1YS", 2, 1),
    ]


@pytest.mark.parametrize("frequency, resolution", [("1h", "1H"), ("3h", "3H")])
def test_native_subdaily_values_are_retained_as_source(
    tmp_path, frequency, resolution
):
    source = tmp_path / f"source-{resolution}.nc"
    source_data = _time_dataset(8, frequency).drop_vars(
        ["latitude", "longitude"]
    ).assign_coords(
        latitude=("y", [0.0, 1.0, 2.0]),
        longitude=("x", [10.0, 11.0, 12.0]),
    )
    source_data.to_netcdf(source)
    record = {
        "dataset": "test",
        "variable": "value",
        "temporal_resolution": resolution,
        "grid_type": "rectilinear",
        "file_path": str(source),
    }
    source_products = []

    def capture(data, _record, **kwargs):
        if kwargs["time_unit"] == "Source":
            source_products.append(data.load())
        assert kwargs["time_unit"] != "Hour"
        return []

    with patch(
        "storage.ingest_data.aggregate_data.write_product_partitions",
        side_effect=capture,
    ):
        aggregate_record(record, settings=_settings(tmp_path))

    assert len(source_products) == 1
    xr.testing.assert_equal(source_products[0]["value"], source_data["value"])
    xr.testing.assert_equal(
        source_products[0]["timestamp"], source_data["timestamp"]
    )


def test_small_end_to_end_hierarchy_writes_product_partitions(tmp_path):
    source = tmp_path / "source.nc"
    source_data = _time_dataset(31, "1D").drop_vars(
        ["latitude", "longitude"]
    ).assign_coords(
        latitude=("y", [0.0, 1.0, 2.0]),
        longitude=("x", [10.0, 11.0, 12.0]),
    )
    source_data.to_netcdf(source)
    record = {
        "repository": "test",
        "dataset": "test",
        "variable": "value",
        "coordinates": [-90, 90, 0, 360],
        "grid_type": "rectilinear",
        "spatial_resolution": 1.0,
        "temporal_resolution": "1D",
        "file_path": str(source),
    }
    settings = _settings(tmp_path)
    written = aggregate_record(record, settings=settings)

    assert len(written) == 3
    records = [
        json.loads(line)
        for line in settings.product_index.read_text().splitlines()
    ]
    assert {
        (item["temporal_resolution"], item["coarseness_factor"])
        for item in records
    } == {("Source", 1), ("Month", 1), ("Month", 2)}
    for item in records:
        path = tmp_path / item["relative_path"]
        assert path.is_file()
        with xr.open_dataset(path) as partition:
            assert partition.attrs["grid_id"] == item["grid_id"]
            assert "latitude" not in partition.coords
            assert "longitude" not in partition.coords
            if item["temporal_resolution"] == "Source":
                assert "value" in partition
                assert all(name not in partition for name in AGGREGATE_STATISTICS)
            else:
                assert "value" not in partition
                assert all(name in partition for name in AGGREGATE_STATISTICS)


def test_combined_aggregation_stores_day_instead_of_source(tmp_path):
    source = tmp_path / "combined.nc"
    source_data = _time_dataset(31, "1D").drop_vars(
        ["latitude", "longitude"]
    ).assign_coords(
        latitude=("y", [0.0, 1.0, 2.0]),
        longitude=("x", [10.0, 11.0, 12.0]),
    )
    source_data["source_count"] = xr.ones_like(
        source_data["value"], dtype=np.int16
    )
    source_data.to_netcdf(source)
    record = {
        "repository": "polaris",
        "dataset": "combined",
        "variable": "value",
        "spatial_resolution": 1.0,
        "temporal_resolution": "1D",
        "grid_type": "rectilinear",
        "file_path": str(source),
    }
    settings = _settings(tmp_path)

    written = aggregate_record(record, settings=settings)

    assert {
        (item["temporal_resolution"], item["coarseness_factor"])
        for item in written
    } == {("Day", 1), ("Month", 1), ("Month", 2)}
    day = next(item for item in written if item["temporal_resolution"] == "Day")
    with xr.open_dataset(tmp_path / day["relative_path"]) as stored:
        assert "value" not in stored
        assert set(AGGREGATE_STATISTICS) <= set(stored.data_vars)
        assert stored["source_count"].dtype == np.int16


def test_dataset_catalog_merges_variables_for_one_variant(tmp_path):
    settings = _settings(tmp_path)
    timestamps = pd.date_range("2020-01-01", periods=1)
    base_record = {
        "repository": "test",
        "dataset": "multi",
        "temporal_resolution": "1D",
    }
    for variable in ("first", "second"):
        data = xr.Dataset(
            {variable: (("timestamp", "y", "x"), [[[1.0]]], {"units": "K"})},
            coords={"timestamp": timestamps},
        )
        write_product_partitions(
            data,
            {**base_record, "variable": variable},
            grid_id="0123456789abcdef0123456789abcdef",
            grid_shape=(1, 1),
            time_unit="Source",
            temporal_resolution="1D",
            coarseness_factor=1,
            settings=settings,
        )

    records = [
        json.loads(line)
        for line in settings.datasets_catalog.read_text().splitlines()
    ]
    assert len(records) == 1
    assert set(records[0]["variables"]) == {"first", "second"}


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
