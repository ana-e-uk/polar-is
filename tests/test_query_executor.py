from dataclasses import replace
import json

import numpy as np
import pandas as pd
import xarray as xr

from polaris.config import get_settings
from storage.query_data.executor import execute_query


GRID_ID = "0123456789abcdef0123456789abcdef"
VARIANT_ID = "fedcba9876543210fedcba9876543210"
PARTITION_ID = "11111111111111111111111111111111"


def _query(function, **changes):
    query = {
        "variable": "sea_surface_temperature",
        "region": {"west": 0, "east": 80, "south": 0, "north": 20},
        "time_start": "2020-01-01",
        "time_end": "2020-01-02",
        "coarseness_factor": 1,
        "time_unit": "Day",
        "function": function,
        "aggregation_method": "mean",
        "repository": "noaancei",
        "dataset": "emsst",
    }
    query.update(changes)
    return query


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records))


def _settings(tmp_path):
    settings = replace(
        get_settings(),
        grids_dir=tmp_path / "catalogs" / "grids",
        grids_catalog=tmp_path / "catalogs" / "grids.jsonl",
        datasets_catalog=tmp_path / "catalogs" / "datasets.jsonl",
        bucket_lookup_dir=tmp_path / "bucket_lookup",
        products_dir=tmp_path / "products",
        product_index=tmp_path / "metadata.jsonl",
        _query_results=tmp_path / "results",
    )
    grid = xr.Dataset(
        {
            "cell_area": (("y", "x"), [[1.0, 3.0]], {"units": "m2"}),
        },
        coords={
            "latitude": ("y", [10.0]),
            "longitude": ("x", [10.0, 70.0]),
        },
        attrs={"grid_type": "rectilinear"},
    )
    settings.grids_dir.mkdir(parents=True)
    grid.to_netcdf(settings.grids_dir / f"{GRID_ID}.nc")
    _write_jsonl(
        settings.datasets_catalog,
        [
            {
                "dataset_variant_id": VARIANT_ID,
                "repository": "noaancei",
                "dataset": "emsst",
                "additional_parameters": {},
                "variables": {
                    "sea_surface_temperature": {
                        "units": "K",
                        "source_temporal_resolution": "1D",
                    }
                },
            }
        ],
    )
    _write_jsonl(
        settings.bucket_lookup_dir / f"{GRID_ID}.jsonl",
        [
            {
                "grid_id": GRID_ID,
                "bucket_id": "r3_c0",
                "grid_y_start": 0,
                "grid_y_stop": 1,
                "grid_x_start": 0,
                "grid_x_stop": 1,
            },
            {
                "grid_id": GRID_ID,
                "bucket_id": "r3_c1",
                "grid_y_start": 0,
                "grid_y_stop": 1,
                "grid_x_start": 1,
                "grid_x_stop": 2,
            },
        ],
    )
    relative_path = "products/example/day.nc"
    product = xr.Dataset(
        {
            "polaris_weighted_sum": (
                ("timestamp", "y", "x"),
                [[[0.0, 30.0]], [[2.0, 42.0]]],
                {"units": "K"},
            ),
            "polaris_weight_sum": (
                ("timestamp", "y", "x"),
                [[[1.0, 3.0]], [[1.0, 3.0]]],
            ),
            "polaris_min": (
                ("timestamp", "y", "x"),
                [[[0.0, 10.0]], [[2.0, 14.0]]],
                {"units": "K"},
            ),
            "polaris_max": (
                ("timestamp", "y", "x"),
                [[[0.0, 10.0]], [[2.0, 14.0]]],
                {"units": "K"},
            ),
        },
        coords={
            "timestamp": pd.date_range("2020-01-01", periods=2, freq="1D")
        },
    )
    product_path = tmp_path / relative_path
    product_path.parent.mkdir(parents=True)
    product.to_netcdf(product_path)
    _write_jsonl(
        settings.product_index,
        [
            {
                "partition_id": PARTITION_ID,
                "dataset_variant_id": VARIANT_ID,
                "variable": "sea_surface_temperature",
                "grid_id": GRID_ID,
                "temporal_resolution": "Day",
                "coarseness_factor": 1,
                "time_start": "2020-01-01T00:00:00",
                "time_end": "2020-01-02T00:00:00",
                "grid_y_start": 0,
                "grid_y_stop": 1,
                "grid_x_start": 0,
                "grid_x_stop": 2,
                "relative_path": relative_path,
            }
        ],
    )
    return settings


def test_executor_writes_structured_get_data_result(tmp_path):
    result = execute_query(_query("get-data"), _settings(tmp_path))

    assert len(result.groups) == 1
    group = result.groups[0]
    assert group.file_path.is_file()
    assert group.data.sizes == {"timestamp": 2, "grid_y": 1, "grid_x": 2}
    assert group.grid_id == GRID_ID
    assert group.grid_window == (0, 1, 0, 2)
    assert set(group.data.coords) >= {
        "timestamp",
        "grid_y",
        "grid_x",
        "latitude",
        "longitude",
    }
    assert group.units == "K"
    assert group.source.partition_ids == (PARTITION_ID,)
    assert group.miss_set == frozenset()


def test_executor_computes_all_four_derived_functions(tmp_path):
    settings = _settings(tmp_path)

    timeseries = execute_query(_query("timeseries"), settings).groups[0].data
    np.testing.assert_allclose(
        timeseries["sea_surface_temperature"],
        [7.5, 11.0],
    )

    heatmap = execute_query(_query("heatmap"), settings).groups[0].data
    np.testing.assert_allclose(
        heatmap["sea_surface_temperature"],
        [[1.0, 12.0]],
    )

    find_time = execute_query(
        _query("find-time", predicate="gt", filter_value=8), settings
    ).groups[0].data
    np.testing.assert_array_equal(find_time["matches"], [False, True])

    find_area = execute_query(
        _query("find-area", predicate="ge", filter_value=5), settings
    ).groups[0].data
    np.testing.assert_array_equal(find_area["matches"], [[False, True]])


def test_executor_refines_bucket_window_and_removes_empty_edges(tmp_path):
    settings = _settings(tmp_path)
    grid = xr.Dataset(
        {"cell_area": (("y", "x"), np.ones((1, 4)), {"units": "m2"})},
        coords={
            "latitude": ("y", [10.0]),
            "longitude": ("x", [10.0, 20.0, 30.0, 70.0]),
        },
        attrs={"grid_type": "rectilinear"},
    )
    grid.to_netcdf(settings.grids_dir / f"{GRID_ID}.nc")
    _write_jsonl(
        settings.bucket_lookup_dir / f"{GRID_ID}.jsonl",
        [
            {
                "grid_id": GRID_ID,
                "bucket_id": "r3_c0",
                "grid_y_start": 0,
                "grid_y_stop": 1,
                "grid_x_start": 0,
                "grid_x_stop": 3,
            },
            {
                "grid_id": GRID_ID,
                "bucket_id": "r3_c1",
                "grid_y_start": 0,
                "grid_y_stop": 1,
                "grid_x_start": 3,
                "grid_x_stop": 4,
            },
        ],
    )
    product_path = tmp_path / "products/example/day.nc"
    product = xr.Dataset(
        {
            "polaris_weighted_sum": (
                ("timestamp", "y", "x"),
                [[[0.0, 2.0, 0.0, 0.0]], [[0.0, 4.0, 0.0, 0.0]]],
                {"units": "K"},
            ),
            "polaris_weight_sum": (
                ("timestamp", "y", "x"),
                [[[0.0, 1.0, 0.0, 0.0]], [[0.0, 1.0, 0.0, 0.0]]],
            ),
            "polaris_min": (
                ("timestamp", "y", "x"),
                [[[np.nan, 2.0, np.nan, np.nan]], [[np.nan, 4.0, np.nan, np.nan]]],
                {"units": "K"},
            ),
            "polaris_max": (
                ("timestamp", "y", "x"),
                [[[np.nan, 2.0, np.nan, np.nan]], [[np.nan, 4.0, np.nan, np.nan]]],
                {"units": "K"},
            ),
        },
        coords={"timestamp": pd.date_range("2020-01-01", periods=2, freq="1D")},
    )
    product.to_netcdf(product_path)
    records = [json.loads(line) for line in settings.product_index.read_text().splitlines()]
    records[0]["grid_x_stop"] = 4
    _write_jsonl(settings.product_index, records)

    result = execute_query(
        _query(
            "heatmap",
            region={"west": 19, "east": 21, "south": 9, "north": 11},
        ),
        settings,
    ).groups[0].data

    assert result.sizes == {"grid_y": 1, "grid_x": 1}
    np.testing.assert_array_equal(result["grid_x"], [1])
    np.testing.assert_allclose(result["longitude"], [20.0])
    np.testing.assert_allclose(result["sea_surface_temperature"], [[3.0]])
