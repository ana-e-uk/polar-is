"""Grid topology helpers shared by ingestion and query execution."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

import numpy as np
from pyproj import CRS, Transformer
import xarray as xr

from polaris.config import get_settings
from storage.catalog import GridCatalogRecord


_EARTH_RADIUS_METRES = 6_371_008.8


def _axis_bounds(values: xr.DataArray) -> xr.DataArray:
    """Infer contiguous bounds for a monotonic one-dimensional center axis."""
    centers = np.asarray(values.values, dtype=float)
    if centers.ndim != 1:
        raise ValueError(f"{values.name} must be one-dimensional")
    if centers.size == 1:
        width = 1.0
        edges = np.asarray([centers[0] - width / 2, centers[0] + width / 2])
    else:
        midpoints = (centers[:-1] + centers[1:]) / 2
        edges = np.concatenate(
            ([centers[0] - (midpoints[0] - centers[0])],
             midpoints,
             [centers[-1] + (centers[-1] - midpoints[-1])])
        )
    return xr.DataArray(
        np.column_stack((edges[:-1], edges[1:])),
        dims=(values.dims[0], "bounds"),
        coords={"bounds": [0, 1]},
    )


def add_rectilinear_bounds(data: xr.Dataset) -> xr.Dataset:
    """Add compact CF-style bounds for a rectilinear geographic grid."""
    result = data.copy()
    result["latitude_bounds"] = _axis_bounds(result["latitude"])
    result["longitude_bounds"] = _axis_bounds(result["longitude"])
    result["latitude_bounds"].attrs = {"units": "degrees_north"}
    result["longitude_bounds"].attrs = {"units": "degrees_east"}
    result["latitude"].attrs = {**result["latitude"].attrs, "bounds": "latitude_bounds"}
    result["longitude"].attrs = {
        **result["longitude"].attrs,
        "bounds": "longitude_bounds",
    }
    return result


def carra_cf_grid_mapping(variable: xr.DataArray) -> dict[str, object] | None:
    """Translate CARRA's GRIB Lambert metadata into a CF grid mapping."""
    attrs = variable.attrs
    if str(attrs.get("GRIB_gridType", "")).lower() != "lambert":
        return None
    required = (
        "GRIB_Latin1InDegrees",
        "GRIB_Latin2InDegrees",
        "GRIB_LoVInDegrees",
        "GRIB_LaDInDegrees",
        "GRIB_DxInMetres",
        "GRIB_DyInMetres",
    )
    if any(name not in attrs for name in required):
        raise ValueError("CARRA Lambert grid is missing required GRIB projection metadata")
    return {
        "grid_mapping_name": "lambert_conformal_conic",
        "standard_parallel": np.asarray(
            [attrs["GRIB_Latin1InDegrees"], attrs["GRIB_Latin2InDegrees"]],
            dtype=float,
        ),
        "longitude_of_central_meridian": float(attrs["GRIB_LoVInDegrees"]),
        "latitude_of_projection_origin": float(attrs["GRIB_LaDInDegrees"]),
        "false_easting": 0.0,
        "false_northing": 0.0,
        # GRIB shape-of-earth 6, used by this CARRA product.
        "earth_radius": 6_371_229.0,
    }


def add_carra_projection(data: xr.Dataset, variable: str) -> xr.Dataset:
    """Create regular projected coordinates and a CF CRS for CARRA."""
    mapping = carra_cf_grid_mapping(data[variable])
    if mapping is None:
        return data

    attrs = data[variable].attrs
    crs = CRS.from_cf(mapping)
    forward = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    longitude0 = float(attrs["GRIB_longitudeOfFirstGridPointInDegrees"])
    latitude0 = float(attrs["GRIB_latitudeOfFirstGridPointInDegrees"])
    x_origin, y_origin = forward.transform(longitude0, latitude0)
    x_step = float(attrs["GRIB_DxInMetres"])
    y_step = float(attrs["GRIB_DyInMetres"])
    if bool(attrs.get("GRIB_iScansNegatively", 0)):
        x_step *= -1
    if not bool(attrs.get("GRIB_jScansPositively", 0)):
        y_step *= -1

    result = data.assign_coords(
        projection_x=(
            "x",
            x_origin + np.arange(data.sizes["x"], dtype=float) * x_step,
            {"standard_name": "projection_x_coordinate", "units": "m", "axis": "X"},
        ),
        projection_y=(
            "y",
            y_origin + np.arange(data.sizes["y"], dtype=float) * y_step,
            {"standard_name": "projection_y_coordinate", "units": "m", "axis": "Y"},
        ),
    )
    crs_attrs = {
        **mapping,
        "crs_wkt": crs.to_wkt(),
        "spatial_ref": crs.to_wkt(),
        "polaris_projection_x_origin": float(x_origin),
        "polaris_projection_y_origin": float(y_origin),
        "polaris_projection_x_step": float(x_step),
        "polaris_projection_y_step": float(y_step),
    }
    result = result.assign_coords(crs=xr.DataArray(np.int8(0), attrs=crs_attrs))
    result[variable].attrs = {**result[variable].attrs, "grid_mapping": "crs"}
    result.attrs["polaris_grid_type"] = "projected"
    return result


def add_grid_topology(
    data: xr.Dataset,
    variable: str,
    grid_type: str,
) -> tuple[xr.Dataset, str]:
    """Attach reusable bounds or projection geometry to a source grid."""
    result = add_carra_projection(data, variable)
    if "projection_x" in result.coords and "projection_y" in result.coords:
        grid_type = "projected"
    elif grid_type == "rectilinear":
        result = add_rectilinear_bounds(result)
        result.attrs["polaris_grid_type"] = "rectilinear"
    else:
        result.attrs["polaris_grid_type"] = grid_type
    return result, grid_type


def _axis_edges(data: xr.Dataset, coordinate: str) -> np.ndarray:
    bounds_name = data[coordinate].attrs.get("bounds")
    if bounds_name in data:
        bounds = np.asarray(data[bounds_name].values, dtype=np.float64)
        return np.concatenate((bounds[:, 0], bounds[-1:, 1]))
    centers = np.asarray(data[coordinate].values, dtype=np.float64)
    if centers.size == 1:
        return np.asarray([centers[0] - 0.5, centers[0] + 0.5])
    midpoints = (centers[:-1] + centers[1:]) / 2
    return np.concatenate(
        (
            [centers[0] - (midpoints[0] - centers[0])],
            midpoints,
            [centers[-1] + (centers[-1] - midpoints[-1])],
        )
    )


def grid_cell_area(data: xr.Dataset) -> xr.DataArray:
    """Calculate reusable cell areas for a canonical standardized grid."""
    if data["latitude"].ndim == 1 and data["longitude"].ndim == 1:
        latitude_edges = np.clip(_axis_edges(data, "latitude"), -90, 90)
        longitude_edges = _axis_edges(data, "longitude")
        latitude_factor = np.abs(
            np.sin(np.deg2rad(latitude_edges[1:]))
            - np.sin(np.deg2rad(latitude_edges[:-1]))
        )
        longitude_width = np.abs(np.deg2rad(np.diff(longitude_edges)))
        area = (
            (_EARTH_RADIUS_METRES**2)
            * latitude_factor[:, None]
            * longitude_width
        )
        return xr.DataArray(
            area,
            dims=("y", "x"),
            attrs={"standard_name": "cell_area", "units": "m2"},
        )
    if "projection_x" in data.coords and "projection_y" in data.coords:
        x_edges = _axis_edges(data, "projection_x")
        y_edges = _axis_edges(data, "projection_y")
        area = (
            np.abs(np.diff(y_edges))[:, None]
            * np.abs(np.diff(x_edges))[None, :]
        )
        return xr.DataArray(
            area,
            dims=("y", "x"),
            attrs={
                "standard_name": "cell_area",
                "long_name": "projected grid-cell area",
                "units": "m2",
            },
        )
    latitude, _ = xr.broadcast(data["latitude"], data["longitude"])
    result = np.cos(np.deg2rad(latitude)).clip(min=0).transpose("y", "x")
    result.attrs = {
        "long_name": "relative grid-cell area",
        "units": "relative",
    }
    return result


def canonical_grid(data: xr.Dataset, grid_type: str | None = None) -> xr.Dataset:
    """Extract static geometry from one complete standardized source grid."""
    if grid_type is None:
        grid_type = str(data.attrs.get("polaris_grid_type", ""))
    if "projection_x" in data.coords and "projection_y" in data.coords:
        grid_type = "projected"
    elif data["latitude"].ndim == 1 and data["longitude"].ndim == 1:
        grid_type = "rectilinear"
    if grid_type not in {"rectilinear", "projected"}:
        raise ValueError(f"Unsupported canonical grid type: {grid_type!r}")

    coordinates = {}
    for name in ("latitude", "longitude", "projection_y", "projection_x", "crs"):
        if name in data:
            coordinates[name] = data[name]
    result = xr.Dataset(coords=coordinates, attrs={"grid_type": grid_type})
    for name in ("latitude_bounds", "longitude_bounds"):
        if name in data:
            result[name] = data[name]
    result["cell_area"] = grid_cell_area(data)
    return result


def _json_value(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return str(value)


def canonical_grid_id(grid: xr.Dataset) -> str:
    """Return a stable 128-bit identifier for complete grid geometry.

    Coordinate labels and other descriptive attributes do not make a new
    grid. Projection attributes do, because they define the coordinate
    system in which projected axes are interpreted.
    """
    digest = hashlib.blake2b(digest_size=16)
    digest.update(str(grid.attrs.get("grid_type", "")).encode())
    digest.update(str((grid.sizes.get("y"), grid.sizes.get("x"))).encode())
    for name in sorted(grid.variables):
        variable = grid[name]
        values = np.ascontiguousarray(variable.values)
        digest.update(name.encode())
        digest.update(str(variable.dims).encode())
        digest.update(str(values.dtype).encode())
        digest.update(str(values.shape).encode())
        digest.update(values.tobytes())
        if name == "crs":
            digest.update(
                json.dumps(
                    variable.attrs,
                    sort_keys=True,
                    default=_json_value,
                    separators=(",", ":"),
                ).encode()
            )
    return digest.hexdigest()


def _append_grid_record(path: Path, record: GridCatalogRecord) -> None:
    existing = []
    if path.exists():
        existing = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    if any(item.get("grid_id") == record.grid_id for item in existing):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".partial",
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with temporary.open("w", encoding="utf-8") as file:
            for item in [*existing, record.to_dict()]:
                json.dump(item, file, sort_keys=True)
                file.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_grid_catalog(
    data: xr.Dataset,
    grid_type: str | None = None,
    *,
    settings=None,
) -> GridCatalogRecord:
    """Write or reuse one canonical grid asset and its catalog record."""
    settings = settings or get_settings()
    grid = canonical_grid(data, grid_type)
    grid_id = canonical_grid_id(grid)
    relative_path = f"catalogs/grids/{grid_id}.nc"
    path = settings.grids_dir / f"{grid_id}.nc"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.partial")
        try:
            grid.to_netcdf(temporary)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    record = GridCatalogRecord(
        grid_id=grid_id,
        grid_type=str(grid.attrs["grid_type"]),
        shape_y=int(grid.sizes["y"]),
        shape_x=int(grid.sizes["x"]),
        relative_path=relative_path,
    )
    _append_grid_record(settings.grids_catalog, record)
    return record


def transformer_from_grid_mapping(data: xr.Dataset) -> Transformer | None:
    """Return a projected-to-geographic transformer from a CF mapping."""
    if "crs" not in data.coords and "crs" not in data.variables:
        return None
    attrs = dict(data["crs"].attrs)
    if "grid_mapping_name" not in attrs:
        return None
    crs = CRS.from_cf(attrs)
    return Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
