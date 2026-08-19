import json
from pathlib import Path

import numpy as np
import xarray as xr

from storage.ingest_data.make_data_blocks import (
    block_bounds_and_extrema,
    make_data_blocks,
    update_bucket_file_counts,
)


def _source_dataset():
    return xr.Dataset(
        data_vars={
            "value": (
                ("timestamp", "y", "x"),
                [
                    [[87.443, 99.20, 90.011], [88.11, 86.0, 97.512]],
                    [[100.0, 94.87, 91.523], [92.0, 93.0, 95.0]],
                ],
            ),
            "static_spatial": (
                ("y", "x"),
                np.arange(6, dtype=np.float32).reshape(2, 3),
            ),
            "time_only": ("timestamp", [100, 200]),
            "scalar": 42,
        },
        coords={
            "timestamp": [0, 1],
            "latitude": (
                ("y", "x"),
                [[10.0, 10.0, 10.0], [10.0, 10.0, 10.0]],
            ),
            "longitude": (
                ("y", "x"),
                [[10.0, 70.0, 10.0], [70.0, 10.0, 70.0]],
            ),
        },
    )


def _record(source_path: Path):
    return {
        "dataset": "test-data",
        "variable": "value",
        "coordinates": [0.0, 80.0, 0.0, 20.0],
        "grid_type": "curvilinear",
        "file_path": str(source_path),
    }


def _read_json_lines(path: Path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def _bucket_definitions(path: Path):
    buckets = {
        "r3_c0": {"id": "r3_c0", "data": 0},
        "r3_c1": {"id": "r3_c1", "data": 0},
    }
    path.write_text(json.dumps(buckets))
    return path


def test_block_bounds_and_extrema_with_rectilinear_coordinates():
    dataset = xr.Dataset(
        data_vars={
            "value": (
                ("y", "x"),
                [[0.0, 86.0, 0.0], [100.0, 90.0, 0.0], [0.0, 0.0, 0.0]],
            )
        },
        coords={
            "latitude": ("y", [-20.0, 10.0, 40.0]),
            "longitude": ("x", [10.0, 70.0, 130.0]),
        }
    )
    mask = xr.DataArray(
        [[False, True, False], [True, True, False], [False, False, False]],
        dims=("y", "x"),
    )

    assert block_bounds_and_extrema(dataset, mask, "value") == {
        "lat_min": -20.0,
        "lat_max": 10.0,
        "lon_min": 10.0,
        "lon_max": 70.0,
        "var_min": 86.0,
        "var_max": 100.0,
    }


def test_make_data_blocks_preserves_non_spatial_variables(tmp_path):
    source_path = tmp_path / "source.nc"
    _source_dataset().to_netcdf(source_path)
    output_directory = tmp_path / "blocks"
    metadata_path = tmp_path / "metadata.jsonl"
    buckets_path = _bucket_definitions(tmp_path / "buckets.json")

    make_data_blocks(
        [_record(source_path)],
        output_directory,
        metadata_path,
        buckets_path,
    )

    records = _read_json_lines(metadata_path)
    assert {record["bucket_id"] for record in records} == {
        "r3_c0",
        "r3_c1",
    }
    for record in records:
        assert isinstance(record["bucket_code"], int)
        assert record["dataset_bounds"] == [0.0, 80.0, 0.0, 20.0]
        assert "coordinates" not in record
        assert "bounds" not in record
        assert set(record["block_summary"]) == {
            "lat_min",
            "lat_max",
            "lon_min",
            "lon_max",
            "var_min",
            "var_max",
        }
        assert isinstance(record["file_path"], str)

        expected_longitude = (
            10.0 if record["bucket_id"] == "r3_c0" else 70.0
        )
        expected_extrema = (
            (86.0, 100.0)
            if record["bucket_id"] == "r3_c0"
            else (88.11, 99.20)
        )
        assert record["block_summary"] == {
            "lat_min": 10.0,
            "lat_max": 10.0,
            "lon_min": expected_longitude,
            "lon_max": expected_longitude,
            "var_min": expected_extrema[0],
            "var_max": expected_extrema[1],
        }

        block_path = Path(record["file_path"])
        assert block_path.parent.name == record["bucket_id"]
        with xr.open_dataset(block_path) as block:
            assert block["time_only"].dims == ("timestamp",)
            assert block["scalar"].dims == ()
            assert block["value"].dims == ("timestamp", "y", "x")
            assert block["static_spatial"].dims == ("y", "x")
            assert block["value"].isnull().any().item()

    buckets = json.loads(buckets_path.read_text())
    assert buckets["r3_c0"]["data"] == 1
    assert buckets["r3_c1"]["data"] == 1


def test_all_missing_extrema_are_none():
    dataset = _source_dataset()
    dataset["value"] = xr.full_like(dataset["value"], np.nan)
    mask = xr.DataArray(
        [[True, False, True], [False, True, False]],
        dims=("y", "x"),
    )

    summary = block_bounds_and_extrema(dataset, mask, "value")

    assert summary["var_min"] is None
    assert summary["var_max"] is None
    json.dumps(summary, allow_nan=False)


def test_make_data_blocks_preserves_source_compression(tmp_path):
    source_path = tmp_path / "compressed-source.nc"
    dataset = _source_dataset()
    dataset.to_netcdf(
        source_path,
        encoding={
            "value": {
                "zlib": True,
                "complevel": 4,
                "shuffle": True,
                "chunksizes": (1, 2, 2),
            }
        },
    )
    output_directory = tmp_path / "blocks"
    metadata_path = tmp_path / "metadata.jsonl"
    buckets_path = _bucket_definitions(tmp_path / "buckets.json")

    make_data_blocks(
        [_record(source_path)],
        output_directory,
        metadata_path,
        buckets_path,
    )

    for record in _read_json_lines(metadata_path):
        with xr.open_dataset(record["file_path"]) as block:
            encoding = block["value"].encoding
            assert encoding["zlib"] is True
            assert encoding["complevel"] == 4
            assert encoding["shuffle"] is True
            assert all(
                chunk_size <= block.sizes[dimension]
                for chunk_size, dimension in zip(
                    encoding["chunksizes"], block["value"].dims
                )
            )


def test_make_data_blocks_rolls_back_after_failure(tmp_path):
    source_path = tmp_path / "source.nc"
    _source_dataset().to_netcdf(source_path)
    output_directory = tmp_path / "blocks"
    metadata_path = tmp_path / "metadata.jsonl"
    buckets_path = _bucket_definitions(tmp_path / "buckets.json")
    original_buckets = buckets_path.read_text()
    original_metadata = '{"existing": true}\n'
    metadata_path.write_text(original_metadata)
    records = [
        _record(source_path),
        _record(tmp_path / "missing.nc"),
    ]

    try:
        make_data_blocks(
            records,
            output_directory,
            metadata_path,
            buckets_path,
        )
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("Missing input file did not fail")

    assert metadata_path.read_text() == original_metadata
    assert buckets_path.read_text() == original_buckets
    assert not list(output_directory.rglob("*.nc"))
    assert not list(output_directory.rglob("*.partial"))


def test_update_bucket_file_counts_recomputes_from_disk(tmp_path):
    output_directory = tmp_path / "blocks"
    first_bucket = output_directory / "r3_c0"
    first_bucket.mkdir(parents=True)
    (first_bucket / "first.nc").touch()
    (first_bucket / "second.nc").touch()
    (first_bucket / "not-a-block.txt").touch()
    buckets_path = _bucket_definitions(tmp_path / "buckets.json")
    buckets = json.loads(buckets_path.read_text())
    buckets["r3_c0"]["data"] = 999
    buckets["r3_c1"]["data"] = 999
    buckets_path.write_text(json.dumps(buckets))

    update_bucket_file_counts(output_directory, buckets_path)

    updated = json.loads(buckets_path.read_text())
    assert updated["r3_c0"]["data"] == 2
    assert updated["r3_c1"]["data"] == 0
    assert not list(tmp_path.glob("*.partial"))
