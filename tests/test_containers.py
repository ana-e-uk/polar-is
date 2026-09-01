import json

import numpy as np
import xarray as xr

from polaris.config import ContainerScheme
from storage.manage.space_containers import (
    container_definitions,
    container_grid,
    container_id_from_code,
    ensure_container_scheme,
    map_containers,
)


BASE_GRID = {
    "lon_min": 0,
    "lat_min": -90,
    "lon_size": 60,
    "lat_size": 30,
}


def _grid(factor=1):
    return container_grid(
        f"capacity_{factor}",
        factor,
        **BASE_GRID,
    )


def test_container_id_from_code_is_capacity_local():
    assert container_id_from_code(0, _grid()) == "r0_c0"
    assert container_id_from_code(np.int8(35), _grid()) == "r5_c5"
    assert container_id_from_code(8, _grid(2)) == "r2_c2"
    for invalid_code in (-1, 9):
        try:
            container_id_from_code(invalid_code, _grid(2))
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid container code accepted: {invalid_code}")


def test_coarse_definitions_use_ceiling_division_and_clip_edges():
    grid = container_grid(
        "capacity_2",
        2,
        lon_min=0,
        lat_min=-90,
        lon_size=72,
        lat_size=45,
    )
    definitions = container_definitions(grid)
    assert (grid.n_rows, grid.n_cols) == (2, 3)
    assert len(definitions) == 6
    assert definitions["r1_c2"]["bounds"] == {
        "lon_min": 288.0,
        "lon_max": 360.0,
        "lat_min": 0.0,
        "lat_max": 90.0,
    }


def test_map_rectilinear_cell_centers_for_two_capacities():
    dataset = xr.Dataset(
        coords={
            "latitude": ("y", [-90.0, -60.0, 0.0, 90.0]),
            "longitude": ("x", [-60.0, 0.0, 59.9, 60.0, 360.0]),
        }
    )
    fine = map_containers(dataset, _grid())
    coarse = map_containers(dataset, _grid(2))
    assert fine.dims == ("y", "x")
    np.testing.assert_array_equal(
        fine.values,
        [
            [5, 0, 0, 1, 0],
            [11, 6, 6, 7, 6],
            [23, 18, 18, 19, 18],
            [35, 30, 30, 31, 30],
        ],
    )
    np.testing.assert_array_equal(
        coarse.values,
        [[2, 0, 0, 0, 0], [2, 0, 0, 0, 0], [5, 3, 3, 3, 3], [8, 6, 6, 6, 6]],
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
    np.testing.assert_array_equal(
        map_containers(dataset, _grid()).values,
        [[6, 13, 20], [27, 34, 35]],
    )


def test_map_containers_rejects_invalid_latitude():
    dataset = xr.Dataset(
        coords={"latitude": ("y", [-91.0]), "longitude": ("x", [0.0])}
    )
    try:
        map_containers(dataset, _grid())
    except ValueError as error:
        assert "between -90 and 90" in str(error)
    else:
        raise AssertionError("Invalid latitude was accepted")


def test_ensure_container_scheme_creates_all_directories(tmp_path):
    scheme = ContainerScheme(
        "capacity_4",
        4,
        tmp_path / "data",
        tmp_path / "metadata.jsonl",
        tmp_path / "definitions.json",
    )
    grid = ensure_container_scheme(scheme, BASE_GRID)
    definitions = json.loads(scheme.definitions.read_text())
    assert len(definitions) == grid.n_rows * grid.n_cols
    assert {path.name for path in scheme.data_dir.iterdir()} == set(definitions)
