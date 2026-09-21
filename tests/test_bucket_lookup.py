from types import SimpleNamespace

import xarray as xr

from storage.bucket_lookup import (
    bucket_windows,
    ensure_bucket_lookup,
    read_bucket_lookup,
)
from storage.catalog import GridCatalogRecord


GRID_ID = "0123456789abcdef0123456789abcdef"
BUCKETS = {
    "lon_min": 0,
    "lat_min": -90,
    "lon_size": 60,
    "lat_size": 30,
}


def _grid():
    return xr.Dataset(
        coords={
            "latitude": ("y", [-75.0, -45.0, -15.0]),
            "longitude": ("x", [10.0, 70.0, 130.0]),
        }
    )


def test_rectilinear_bucket_windows_use_global_grid_positions():
    records = bucket_windows(_grid(), GRID_ID, BUCKETS)

    assert [record.bucket_id for record in records] == [
        "r0_c0",
        "r0_c1",
        "r0_c2",
        "r1_c0",
        "r1_c1",
        "r1_c2",
        "r2_c0",
        "r2_c1",
        "r2_c2",
    ]
    assert records[4].grid_y_start == 1
    assert records[4].grid_y_stop == 2
    assert records[4].grid_x_start == 1
    assert records[4].grid_x_stop == 2


def test_bucket_lookup_is_written_once_per_grid(tmp_path):
    settings = SimpleNamespace(
        bucket_lookup_dir=tmp_path / "bucket_lookup",
        container_grid=BUCKETS,
    )
    record = GridCatalogRecord(
        grid_id=GRID_ID,
        grid_type="rectilinear",
        shape_y=3,
        shape_x=3,
        relative_path=f"catalogs/grids/{GRID_ID}.nc",
    )

    first = ensure_bucket_lookup(record, _grid(), settings=settings)
    original = first.read_text()
    second = ensure_bucket_lookup(record, _grid(), settings=settings)

    assert first == second
    assert second.read_text() == original
    assert len(read_bucket_lookup(first)) == 9
