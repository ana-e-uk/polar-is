"""Define hierarchical Earth partitions and map native cell centers to them."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import xarray as xr

LON_SPAN = 360.0
LAT_SPAN = 180.0


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"container_grid.{name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"container_grid.{name} must be finite")
    return result


def _positive_number(value: object, name: str) -> float:
    result = _finite_number(value, name)
    if result <= 0:
        raise ValueError(
            f"container_grid.{name} must be greater than zero"
        )
    return result


@dataclass(frozen=True)
class ContainerGrid:
    """Geometry for one capacity in the spatial container hierarchy."""

    container: str
    factor: int
    lon_min: float
    lat_min: float
    base_lon_size: float
    base_lat_size: float
    base_n_cols: int
    base_n_rows: int

    @property
    def lon_max(self) -> float:
        return self.lon_min + LON_SPAN

    @property
    def lat_max(self) -> float:
        return self.lat_min + LAT_SPAN

    @property
    def lon_size(self) -> float:
        return self.base_lon_size * self.factor

    @property
    def lat_size(self) -> float:
        return self.base_lat_size * self.factor

    @property
    def n_cols(self) -> int:
        return math.ceil(self.base_n_cols / self.factor)

    @property
    def n_rows(self) -> int:
        return math.ceil(self.base_n_rows / self.factor)


def container_grid(
    container: str,
    factor: int,
    *,
    lon_min: float,
    lat_min: float,
    lon_size: float,
    lat_size: float,
) -> ContainerGrid:
    """Derive a capacity grid from the authoritative capacity-1 grid."""
    if isinstance(factor, bool) or not isinstance(factor, int) or factor < 1:
        raise ValueError("Container factor must be a positive integer")

    lon_min = _finite_number(lon_min, "lon_min")
    lat_min = _finite_number(lat_min, "lat_min")
    lon_size = _positive_number(lon_size, "lon_size")
    lat_size = _positive_number(lat_size, "lat_size")
    if lat_min != -90:
        raise ValueError("container_grid.lat_min must be -90")

    base_cols = LON_SPAN / lon_size
    base_rows = LAT_SPAN / lat_size
    if not math.isclose(base_cols, round(base_cols)):
        raise ValueError("container_grid.lon_size must divide 360 exactly")
    if not math.isclose(base_rows, round(base_rows)):
        raise ValueError("container_grid.lat_size must divide 180 exactly")

    grid = ContainerGrid(
        container=container,
        factor=factor,
        lon_min=lon_min,
        lat_min=lat_min,
        base_lon_size=lon_size,
        base_lat_size=lat_size,
        base_n_cols=int(round(base_cols)),
        base_n_rows=int(round(base_rows)),
    )
    if grid.n_rows * grid.n_cols - 1 > np.iinfo(np.int32).max:
        raise ValueError("Configured container grid has too many containers")
    return grid


def normalize_longitude(longitude, grid: ContainerGrid):
    """Normalize longitude into a grid's half-open longitude range."""
    return (longitude - grid.lon_min) % LON_SPAN + grid.lon_min


def container_id_from_code(code: int, grid: ContainerGrid) -> str:
    """Convert a capacity-local numeric code to ``r{row}_c{column}``."""
    if not isinstance(code, (int, np.integer)):
        raise TypeError("Container code must be an integer")
    if not 0 <= int(code) < grid.n_rows * grid.n_cols:
        raise ValueError(
            "Container code must be between 0 and "
            f"{grid.n_rows * grid.n_cols - 1} for {grid.container}"
        )
    row, col = divmod(int(code), grid.n_cols)
    return f"r{row}_c{col}"


def container_for_point(
    longitude: float,
    latitude: float,
    grid: ContainerGrid,
) -> str:
    longitude = normalize_longitude(longitude, grid)
    col = math.floor((longitude - grid.lon_min) / grid.lon_size)
    row = (
        grid.n_rows - 1
        if latitude == grid.lat_max
        else math.floor((latitude - grid.lat_min) / grid.lat_size)
    )
    if not (0 <= row < grid.n_rows and 0 <= col < grid.n_cols):
        raise ValueError(
            f"Point outside container bounds: lon={longitude}, lat={latitude}"
        )
    return f"r{row}_c{col}"


def _cell_center_coordinates(
    dataset: xr.Dataset,
) -> tuple[xr.DataArray, xr.DataArray]:
    if "latitude" not in dataset.coords or "longitude" not in dataset.coords:
        raise ValueError("Dataset must contain latitude and longitude coordinates")

    latitude = dataset["latitude"]
    longitude = dataset["longitude"]
    if latitude.ndim == 1 and longitude.ndim == 1:
        if latitude.dims != ("y",) or longitude.dims != ("x",):
            raise ValueError(
                "Rectilinear coordinates must have dimensions latitude(y) "
                "and longitude(x)"
            )
        latitude, longitude = xr.broadcast(latitude, longitude)
    elif latitude.ndim == 2 and longitude.ndim == 2:
        if latitude.dims != longitude.dims or set(latitude.dims) != {"y", "x"}:
            raise ValueError(
                "Curvilinear latitude and longitude must share y and x dimensions"
            )
        latitude = latitude.transpose("y", "x")
        longitude = longitude.transpose("y", "x")
    else:
        raise ValueError(
            "Latitude and longitude must both be one-dimensional or both be "
            "two-dimensional"
        )
    return latitude, longitude


def map_containers(dataset: xr.Dataset, grid: ContainerGrid) -> xr.DataArray:
    """Assign every native ``(y, x)`` cell center to one container."""
    latitude, longitude = _cell_center_coordinates(dataset)
    finite = (np.isfinite(latitude).all() & np.isfinite(longitude).all())
    if not finite.compute().item():
        raise ValueError("Every cell center must have finite latitude/longitude")

    found_lat_min = latitude.min().compute().item()
    found_lat_max = latitude.max().compute().item()
    if not (
        grid.lat_min <= found_lat_min <= found_lat_max <= grid.lat_max
    ):
        raise ValueError(
            f"Latitude values must be between {grid.lat_min:g} and "
            f"{grid.lat_max:g}; found {found_lat_min} to {found_lat_max}"
        )

    longitude = normalize_longitude(longitude, grid)
    rows = np.floor((latitude - grid.lat_min) / grid.lat_size)
    rows = xr.where(latitude == grid.lat_max, grid.n_rows - 1, rows)
    columns = np.floor((longitude - grid.lon_min) / grid.lon_size)
    codes = (rows * grid.n_cols + columns).astype(np.int32)
    codes.name = "container_code"
    codes.attrs = {
        "long_name": f"{grid.container} spatial container code",
        "container": grid.container,
        "valid_min": 0,
        "valid_max": grid.n_rows * grid.n_cols - 1,
        "container_code_formula": "r{id // n_cols}_c{id % n_cols}",
        "n_cols": grid.n_cols,
    }
    return codes.transpose("y", "x")


def container_definitions(grid: ContainerGrid) -> dict[str, dict]:
    """Return definitions, clipping final rows/columns at Earth bounds."""
    definitions = {}
    for row in range(grid.n_rows):
        for col in range(grid.n_cols):
            container_id = f"r{row}_c{col}"
            code = row * grid.n_cols + col
            definitions[container_id] = {
                "id": container_id,
                "code": code,
                "container": grid.container,
                "factor": grid.factor,
                "row": row,
                "col": col,
                "bounds": {
                    "lon_min": grid.lon_min + col * grid.lon_size,
                    "lon_max": min(
                        grid.lon_min + (col + 1) * grid.lon_size,
                        grid.lon_max,
                    ),
                    "lat_min": grid.lat_min + row * grid.lat_size,
                    "lat_max": min(
                        grid.lat_min + (row + 1) * grid.lat_size,
                        grid.lat_max,
                    ),
                },
                "data": 0,
            }
    return definitions
