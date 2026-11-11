import numpy as np
import xarray as xr

from storage.manage.space_containers import (
    container_definitions,
    container_for_point,
    container_grid,
    container_id_from_code,
    map_containers,
)


def _grid():
    return container_grid(
        "buckets", 1, lon_min=0, lat_min=-90, lon_size=60, lat_size=30
    )


def test_base_bucket_grid_and_definitions_cover_the_globe():
    grid = _grid()
    assert (grid.n_rows, grid.n_cols) == (6, 6)
    definitions = container_definitions(grid)
    assert len(definitions) == 36
    assert definitions["r0_c0"]["bounds"] == {
        "lon_min": 0.0, "lon_max": 60.0, "lat_min": -90.0, "lat_max": -60.0
    }
    assert definitions["r5_c5"]["bounds"] == {
        "lon_min": 300.0, "lon_max": 360.0, "lat_min": 60.0, "lat_max": 90.0
    }


def test_bucket_ids_and_longitude_wrapping_are_stable():
    grid = _grid()
    assert container_id_from_code(0, grid) == "r0_c0"
    assert container_id_from_code(35, grid) == "r5_c5"
    assert container_for_point(-10, 0, grid) == "r3_c5"
    assert container_for_point(360, 90, grid) == "r5_c0"


def test_native_grid_centers_map_to_base_buckets():
    data = xr.Dataset(
        coords={
            "latitude": ("y", [-75.0, 15.0]),
            "longitude": ("x", [-10.0, 10.0]),
        }
    )
    np.testing.assert_array_equal(
        map_containers(data, _grid()),
        [[5, 0], [23, 18]],
    )


def test_invalid_base_bucket_geometry_is_rejected():
    try:
        container_grid(
            "buckets", 1, lon_min=0, lat_min=-90, lon_size=70, lat_size=30
        )
    except ValueError as error:
        assert "must divide 360" in str(error)
    else:
        raise AssertionError("Invalid bucket width was accepted")
