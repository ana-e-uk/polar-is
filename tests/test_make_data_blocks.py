import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import xarray as xr

from polaris.config import ContainerScheme
from storage.ingest_data.make_data_blocks import (
    block_bounds_and_extrema,
    make_data_blocks,
    update_container_file_counts,
)
from storage.manage.space_containers import ensure_container_scheme


BASE_GRID = {
    "lon_min": 0,
    "lat_min": -90,
    "lon_size": 60,
    "lat_size": 30,
}


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
            "timestamp": pd.date_range("2020-01-01", periods=2, freq="1h"),
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
        "spatial_resolution": 1.0,
        "temporal_resolution": "1H",
        "file_path": str(source_path),
    }


def _scheme(tmp_path, factor=1):
    scheme = ContainerScheme(
        f"capacity_{factor}",
        factor,
        tmp_path / f"capacity_{factor}",
        tmp_path / f"capacity_{factor}" / "metadata.jsonl",
        tmp_path / f"capacity_{factor}.json",
    )
    grid = ensure_container_scheme(scheme, BASE_GRID)
    return scheme, grid


def _read_json_lines(path: Path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_block_bounds_and_extrema_with_rectilinear_coordinates(tmp_path):
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
        },
    )
    mask = xr.DataArray(
        [[False, True, False], [True, True, False], [False, False, False]],
        dims=("y", "x"),
    )
    _, grid = _scheme(tmp_path)
    assert block_bounds_and_extrema(dataset, mask, "value", grid) == {
        "lat_min": -20.0,
        "lat_max": 10.0,
        "lon_min": 10.0,
        "lon_max": 70.0,
        "var_min": 86.0,
        "var_max": 100.0,
    }


def test_make_data_blocks_uses_new_schema_and_preserves_variables(tmp_path):
    source_path = tmp_path / "source.nc"
    _source_dataset().to_netcdf(source_path)
    scheme, _ = _scheme(tmp_path)
    make_data_blocks([_record(source_path)], scheme)

    records = _read_json_lines(scheme.metadata)
    assert {record["container_id"] for record in records} == {"r3_c0", "r3_c1"}
    for record in records:
        assert record["metadata_schema_version"] == 2
        assert record["container"] == "capacity_1"
        assert isinstance(record["container_code"], int)
        assert "bucket_id" not in record and "bucket_code" not in record
        assert record["dataset_bounds"] == [0.0, 80.0, 0.0, 20.0]
        assert record["spatial_coarsening_factor"] == 1
        assert record["native_temporal_resolution"] == "1H"
        assert record["product_type"] == "native"
        assert len(record["block_id"]) == 32
        expected_longitude = 10.0 if record["container_id"] == "r3_c0" else 70.0
        expected_extrema = (
            (86.0, 100.0)
            if record["container_id"] == "r3_c0"
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
        assert block_path.parent.name == record["container_id"]
        with xr.open_dataset(block_path) as block:
            assert block["time_only"].dims == ("timestamp",)
            assert block["scalar"].dims == ()
            assert block["value"].isnull().any().item()

    definitions = json.loads(scheme.definitions.read_text())
    assert definitions["r3_c0"]["data"] == 1
    assert definitions["r3_c1"]["data"] == 1


def test_make_data_blocks_is_idempotent(tmp_path):
    source_path = tmp_path / "source.nc"
    _source_dataset().to_netcdf(source_path)
    scheme, _ = _scheme(tmp_path)
    first = make_data_blocks([_record(source_path)], scheme)
    second = make_data_blocks([_record(source_path)], scheme)
    assert len(first) == 2
    assert second == []
    assert len(list(scheme.data_dir.rglob("*.nc"))) == 2
    assert len(_read_json_lines(scheme.metadata)) == 2


def test_all_missing_extrema_are_none(tmp_path):
    dataset = _source_dataset()
    dataset["value"] = xr.full_like(dataset["value"], np.nan)
    mask = xr.DataArray(
        [[True, False, True], [False, True, False]], dims=("y", "x")
    )
    _, grid = _scheme(tmp_path)
    summary = block_bounds_and_extrema(dataset, mask, "value", grid)
    assert summary["var_min"] is None
    assert summary["var_max"] is None
    json.dumps(summary, allow_nan=False)


def test_make_data_blocks_preserves_source_compression(tmp_path):
    source_path = tmp_path / "source.nc"
    _source_dataset().to_netcdf(
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
    scheme, _ = _scheme(tmp_path)
    make_data_blocks([_record(source_path)], scheme)
    for record in _read_json_lines(scheme.metadata):
        with xr.open_dataset(record["file_path"]) as block:
            encoding = block["value"].encoding
            assert encoding["zlib"] is True
            assert encoding["complevel"] == 4
            assert encoding["shuffle"] is True


def test_write_failure_rolls_back_files_and_metadata(tmp_path):
    source_path = tmp_path / "source.nc"
    _source_dataset().to_netcdf(source_path)
    scheme, _ = _scheme(tmp_path)
    original_metadata = '{"existing": true}\n'
    scheme.metadata.write_text(original_metadata)

    from storage.ingest_data import make_data_blocks as module

    original_write = module._write_netcdf_atomically
    calls = 0

    def fail_second(block, output_path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated failure")
        return original_write(block, output_path)

    with patch.object(module, "_write_netcdf_atomically", side_effect=fail_second):
        try:
            make_data_blocks([_record(source_path)], scheme)
        except RuntimeError as error:
            assert "simulated failure" in str(error)
        else:
            raise AssertionError("Simulated write failure did not fail")
    assert scheme.metadata.read_text() == original_metadata
    assert not list(scheme.data_dir.rglob("*.nc"))
    assert not list(scheme.data_dir.rglob("*.partial"))


def test_update_container_file_counts_recomputes_from_disk(tmp_path):
    scheme, _ = _scheme(tmp_path)
    first = scheme.data_dir / "r3_c0"
    (first / "first.nc").touch()
    (first / "second.nc").touch()
    (first / "not-a-block.txt").touch()
    definitions = json.loads(scheme.definitions.read_text())
    definitions["r3_c0"]["data"] = 999
    scheme.definitions.write_text(json.dumps(definitions))
    update_container_file_counts(scheme)
    updated = json.loads(scheme.definitions.read_text())
    assert updated["r3_c0"]["data"] == 2
    assert updated["r3_c1"]["data"] == 0
