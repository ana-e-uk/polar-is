"""Grid topology helpers shared by ingestion and query execution."""

from __future__ import annotations

import numpy as np
from pyproj import CRS, Transformer
import xarray as xr


INDEX_COORDINATES = (
    "source_y_index",
    "source_x_index",
    "source_y_start",
    "source_y_stop",
    "source_x_start",
    "source_x_stop",
    "grid_y_index",
    "grid_x_index",
)


def _index_attrs(axis: str, role: str) -> dict[str, str]:
    return {
        "long_name": f"{role} {axis}-axis grid index",
        "axis": axis.upper(),
    }


def assign_native_grid_indices(data: xr.Dataset) -> xr.Dataset:
    """Attach stable, zero-based source indices before spatial block splitting."""
    result = data.assign_coords(
        source_y_index=("y", np.arange(data.sizes["y"], dtype=np.int64)),
        source_x_index=("x", np.arange(data.sizes["x"], dtype=np.int64)),
        source_y_start=("y", np.arange(data.sizes["y"], dtype=np.int64)),
        source_y_stop=("y", np.arange(1, data.sizes["y"] + 1, dtype=np.int64)),
        source_x_start=("x", np.arange(data.sizes["x"], dtype=np.int64)),
        source_x_stop=("x", np.arange(1, data.sizes["x"] + 1, dtype=np.int64)),
        grid_y_index=("y", np.arange(data.sizes["y"], dtype=np.int64)),
        grid_x_index=("x", np.arange(data.sizes["x"], dtype=np.int64)),
    )
    for name in INDEX_COORDINATES:
        axis = "y" if "_y_" in name else "x"
        role = "source" if name.startswith("source_") else "requested"
        result[name].attrs = _index_attrs(axis, role)
    result.attrs["polaris_coarseness_factor"] = 1
    return result


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
    """Attach the topology required to flatten a standardized native grid."""
    result = assign_native_grid_indices(data)
    result = add_carra_projection(result, variable)
    if "projection_x" in result.coords and "projection_y" in result.coords:
        grid_type = "projected"
    elif grid_type == "rectilinear":
        result = add_rectilinear_bounds(result)
        result.attrs["polaris_grid_type"] = "rectilinear"
    else:
        result.attrs["polaris_grid_type"] = grid_type
    return result, grid_type


def transformer_from_grid_mapping(data: xr.Dataset) -> Transformer | None:
    """Return a projected-to-geographic transformer from a CF mapping."""
    if "crs" not in data.coords and "crs" not in data.variables:
        return None
    attrs = dict(data["crs"].attrs)
    if "grid_mapping_name" not in attrs:
        return None
    crs = CRS.from_cf(attrs)
    return Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
