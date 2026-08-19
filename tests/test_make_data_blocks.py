import json
from pathlib import Path

import numpy as np
import xarray as xr

from storage.ingest_data.make_data_blocks import (
    bounding_rectangle,
    make_data_blocks,
)


def _source_dataset():
    return xr.Dataset(
        data_vars={
            "value": (
                ("timestamp", "y", "x"),
                np.arange(12, dtype=np.float32).reshape(2, 2, 3),
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
        "coordinates": [0.0, 80.0, 0.0, 20.0],
        "grid_type": "curvilinear",
        "file_path": str(source_path),
    }


def _read_json_lines(path: Path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_bounding_rectangle_with_rectilinear_coordinates():
    dataset = xr.Dataset(
        coords={
            "latitude": ("y", [-20.0, 10.0, 40.0]),
            "longitude": ("x", [10.0, 70.0, 130.0]),
        }
    )
    mask = xr.DataArray(
        [[False, True, False], [True, True, False], [False, False, False]],
        dims=("y", "x"),
    )

    assert bounding_rectangle(dataset, mask) == {
        "lat_min": -20.0,
        "lat_max": 10.0,
        "lon_min": 10.0,
        "lon_max": 70.0,
    }


def test_make_data_blocks_preserves_non_spatial_variables(tmp_path):
    source_path = tmp_path / "source.nc"
    _source_dataset().to_netcdf(source_path)
    output_directory = tmp_path / "blocks"
    metadata_path = tmp_path / "metadata.jsonl"

    make_data_blocks(
        [_record(source_path)], output_directory, metadata_path
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
        assert set(record["block_bounds"]) == {
            "lat_min",
            "lat_max",
            "lon_min",
            "lon_max",
        }
        assert isinstance(record["file_path"], str)

        expected_longitude = (
            10.0 if record["bucket_id"] == "r3_c0" else 70.0
        )
        assert record["block_bounds"] == {
            "lat_min": 10.0,
            "lat_max": 10.0,
            "lon_min": expected_longitude,
            "lon_max": expected_longitude,
        }

        block_path = Path(record["file_path"])
        assert block_path.parent.name == record["bucket_id"]
        with xr.open_dataset(block_path) as block:
            assert block["time_only"].dims == ("timestamp",)
            assert block["scalar"].dims == ()
            assert block["value"].dims == ("timestamp", "y", "x")
            assert block["static_spatial"].dims == ("y", "x")
            assert block["value"].isnull().any().item()


def test_make_data_blocks_rolls_back_after_failure(tmp_path):
    source_path = tmp_path / "source.nc"
    _source_dataset().to_netcdf(source_path)
    output_directory = tmp_path / "blocks"
    metadata_path = tmp_path / "metadata.jsonl"
    original_metadata = '{"existing": true}\n'
    metadata_path.write_text(original_metadata)
    records = [
        _record(source_path),
        _record(tmp_path / "missing.nc"),
    ]

    try:
        make_data_blocks(records, output_directory, metadata_path)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("Missing input file did not fail")

    assert metadata_path.read_text() == original_metadata
    assert not list(output_directory.rglob("*.nc"))
    assert not list(output_directory.rglob("*.partial"))
