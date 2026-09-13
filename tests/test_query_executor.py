from dataclasses import replace
import json

import numpy as np
import pandas as pd
import xarray as xr

from polaris.config import ContainerScheme, get_settings
from storage.ingest_data.aggregate_data import add_aggregate_statistics
from storage.ingest_data.make_data_blocks import block_path
from storage.query_data.executor import execute_query


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


def _write_block(scheme, block_id, bucket_id, longitude, values, weight):
    data = xr.Dataset(
        {
            "sea_surface_temperature": (
                ("timestamp", "y", "x"),
                np.asarray(values, dtype=float).reshape(2, 1, 1),
                {"units": "K"},
            ),
            "cell_area": (("y", "x"), [[weight]]),
        },
        coords={
            "timestamp": pd.date_range("2020-01-01", periods=2, freq="1D"),
            "latitude": (("y", "x"), [[10.0]]),
            "longitude": (("y", "x"), [[longitude]]),
        },
    )
    data = add_aggregate_statistics(data, "sea_surface_temperature")
    path = block_path(scheme, bucket_id, block_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data.to_netcdf(path)
    return {
        "repository": "noaancei",
        "dataset": "emsst",
        "variable": "sea_surface_temperature",
        "additional_parameters": {},
        "bucket_id": bucket_id,
        "block_id": block_id,
        "coarseness_factor": 1,
        "temporal_resolution": "1D",
        "native_temporal_resolution": "1D",
        "native_spatial_resolution": 0.25,
        "product_type": "native",
        "time_start": "2020-01-01T00:00:00",
        "time_end": "2020-01-02T00:00:00",
        "block_summary": {
            "lon_min": longitude,
            "lon_max": longitude,
            "lat_min": 10.0,
            "lat_max": 10.0,
        },
    }


def _settings(tmp_path):
    scheme = ContainerScheme(
        name="capacity_1",
        factor=1,
        data_dir=tmp_path / "capacity_1",
        metadata=tmp_path / "capacity_1" / "metadata.jsonl",
        definitions=tmp_path / "capacity_1.json",
    )
    records = [
        _write_block(scheme, "west", "r3_c0", 10.0, [0.0, 2.0], 1.0),
        _write_block(scheme, "east", "r3_c1", 70.0, [10.0, 14.0], 3.0),
    ]
    scheme.metadata.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n"
    )
    return replace(
        get_settings(),
        container_schemes={"capacity_1": scheme},
        coarseness_to_spatial_level={1: scheme},
        _query_results=tmp_path / "results",
    )


def test_executor_writes_get_data_with_coordinates_and_source(tmp_path):
    result = execute_query(_query("get-data"), _settings(tmp_path))

    assert len(result.groups) == 1
    group = result.groups[0]
    assert group.file_path.is_file()
    assert group.data.sizes == {"timestamp": 2, "cell": 2}
    assert set(group.data.coords) >= {
        "timestamp",
        "latitude",
        "longitude",
        "bucket_id",
        "cell_id",
    }
    assert group.units == "K"
    assert group.source.repository == "noaancei"
    assert group.source.dataset == "emsst"
    assert group.source.block_ids == ("west", "east")
    assert group.miss_set == frozenset()


def test_executor_combines_spatial_blocks_with_interleaved_cell_ids(tmp_path):
    settings = _settings(tmp_path)
    scheme = settings.coarseness_to_spatial_level[1]
    middle = _write_block(
        scheme,
        "middle",
        "r3_c0",
        30.0,
        [5.0, 6.0],
        2.0,
    )
    with scheme.metadata.open("a") as metadata:
        metadata.write(json.dumps(middle) + "\n")

    data = execute_query(_query("get-data"), settings).groups[0].data

    assert data.sizes == {"timestamp": 2, "cell": 3}
    assert set(data["longitude"].values) == {10.0, 30.0, 70.0}


def test_executor_computes_all_four_derived_functions(tmp_path):
    settings = _settings(tmp_path)

    timeseries = execute_query(_query("timeseries"), settings).groups[0].data
    np.testing.assert_allclose(
        timeseries["sea_surface_temperature"],
        [7.5, 11.0],
    )

    heatmap = execute_query(_query("heatmap"), settings).groups[0].data
    values_by_longitude = {
        float(longitude): float(value)
        for longitude, value in zip(
            heatmap["longitude"].values,
            heatmap["sea_surface_temperature"].values,
        )
    }
    assert values_by_longitude == {10.0: 1.0, 70.0: 12.0}

    find_time = execute_query(
        _query("find-time", predicate="gt", filter_value=8), settings
    ).groups[0].data
    np.testing.assert_array_equal(find_time["matches"], [False, True])

    find_area = execute_query(
        _query("find-area", predicate="ge", filter_value=5), settings
    ).groups[0].data
    matches_by_longitude = {
        float(longitude): bool(match)
        for longitude, match in zip(
            find_area["longitude"].values,
            find_area["matches"].values,
        )
    }
    assert matches_by_longitude == {10.0: False, 70.0: True}
