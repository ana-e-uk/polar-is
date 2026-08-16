import numpy as np
import xarray as xr

from storage.manage.space_buckets import map_buckets


def test_map_rectilinear_cell_centers():
    dataset = xr.Dataset(
        coords={
            "latitude": ("y", [-90.0, -60.0, 0.0, 90.0]),
            "longitude": ("x", [-60.0, 0.0, 59.9, 60.0, 360.0]),
        }
    )

    result = map_buckets(dataset)

    assert result.dims == ("y", "x")
    np.testing.assert_array_equal(
        result.values,
        [
            [5, 0, 0, 1, 0],
            [11, 6, 6, 7, 6],
            [23, 18, 18, 19, 18],
            [35, 30, 30, 31, 30],
        ],
    )


def test_map_curvilinear_cell_centers():
    dataset = xr.Dataset(
        coords={
            "latitude": (
                ("y", "x"),
                [[-45.0, -15.0, 15.0], [45.0, 75.0, 89.0]],
            ),
            "longitude": (
                ("y", "x"),
                [[10.0, 70.0, 130.0], [190.0, 250.0, 310.0]],
            ),
        }
    )

    result = map_buckets(dataset)

    np.testing.assert_array_equal(
        result.values,
        [[6, 13, 20], [27, 34, 35]],
    )


def test_map_buckets_rejects_invalid_latitude():
    dataset = xr.Dataset(
        coords={
            "latitude": ("y", [-91.0]),
            "longitude": ("x", [0.0]),
        }
    )

    try:
        map_buckets(dataset)
    except ValueError as error:
        assert "between -90 and 90" in str(error)
    else:
        raise AssertionError("Invalid latitude was accepted")
