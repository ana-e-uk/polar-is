"""
standardize.py

IN: 
CSV with columns
    file_paths
    repository
    dataset
    variable
    spatial_resolution
    temporal_resolution
    start_year
    start_month
    end_year
    end_month
    region
    coordinates
    additional_params

OUT: 
Consolidated files with standardized units, coordinates, dimension names
CSV with same columns as IN
"""
import pandas as pd
import xarray as xr
import json
from uuid import uuid4
from pathlib import Path
from typing import Any

from polaris.config import get_settings

# TODO: For future projected datasets that do not have auxiliary lat/lon, keep:
# - native x, y coordinate values
# - x, y units
# - CF grid_mapping variable
# - data variable's reference to that grid mapping
# - CRS as WKT


def open_files(file_paths: list[str]) -> xr.Dataset:
    """Open and combine NetCDF files.

    Files are combined using their coordinates by concatenating
    adjacent time ranges. The data remain lazy until a later operation
    requires them to be read.
    """
    return xr.open_mfdataset(
        file_paths,
        combine="by_coords",
        parallel=False,
        data_vars="all",
    )

def _coord_role(name, coord):
    name_lower = name.lower()
    standard_name = coord.attrs.get("standard_name", "").lower()
    axis = coord.attrs.get("axis", "").upper()
    units = coord.attrs.get("units", "").lower()
    calendar = coord.attrs.get("calendar", "").lower()

    if standard_name == "latitude" or units in {
        "degrees_north", "degree_north"
    }:
        return "latitude"
    
    if standard_name == "longitude" or units in {
        "degrees_east", "degree_east"
    }:
        return "longitude"

    if standard_name == "projection_y_coordinate" or axis == "Y":
        return "y"

    if standard_name == "projection_x_coordinate" or axis == "X":
        return "x"

    if standard_name == "time" or axis == "T" or calendar or name_lower in {
        "time", 
        "timestamp", 
        "datetime", 
        "valid_time", 
        "forecast_time", 
        "forecast_reference_time",
    }:
        return "time"

    # Last-resort name-based guesses
    if name_lower in {"lat", "latitude"}:
        return "latitude"

    if name_lower in {"lon", "longitude", "long"}:
        return "longitude"

    if name_lower in {"x"}:
        return "x"

    if name_lower in {"y"}:
        return "y"

    return None

def inspect_grid(ds: xr.Dataset) -> tuple[xr.Dataset, dict]:
    roles = {}

    for name, coord in ds.coords.items():
        role = _coord_role(name, coord)

        if role is not None:
            if role in roles:
                raise ValueError(
                    f"Multiple coordinates detected for role {role}: "
                    f"{roles[role]!r} and {name!r}"
                )
            roles[role] = name

    dimension_candidates = {
        "time": {"time", 
                 "timestamp", 
                 "datetime", 
                 "valid_time", 
                 "forecast_time", 
                 "forecast_reference_time"},
        "y": {"y"},
        "x":{"x"},
    }

    for dim_name in ds.dims:
        name_lower = dim_name.lower()

        for role, candidates in dimension_candidates.items():
            if role not in roles and name_lower in candidates:
                roles[role] = dim_name

    if "time" not in roles:
        raise ValueError("Could not identify the time dimension")

    time_name = roles["time"]

    if time_name in ds.coords:
        time_coord = ds[time_name]  # NOTE: Is this necessary?

        if time_coord.ndim != 1:
            raise ValueError("The time coordinate must be one-dimensional")

        time_dim = time_coord.dims[0]
    else:
        time_dim = time_name

    has_lat_lon = "latitude" in roles and "longitude" in roles
    has_xy = "x" in roles and "y" in roles

    has_projection_metadata = False

    if has_xy:
        x_standard_name = ds[roles["x"]].attrs.get(
            "standard_name", ""
        ).lower()

        y_standard_name = ds[roles["y"]].attrs.get(
            "standard_name", ""
        ).lower()

        has_projection_metadata = (
            x_standard_name == "projection_x_coordinate"
            or y_standard_name == "projection_y_coordinate"
            or any(
                "grid_mapping" in variable.attrs
                for variable in ds.data_vars.values()
            )
        )

    if has_xy and has_projection_metadata:
        x_name = roles["x"]
        y_name = roles["y"]

        x_coord = ds[x_name]
        y_coord = ds[y_name]

        if x_coord.ndim != 1 or y_coord.ndim != 1:
            raise ValueError(
                "Projected x and y coordinates must be one-dimensional"
            )
        
        grid_type = "projected"
        y_dim = y_coord.dims[0]
        x_dim = x_coord.dims[0]

    elif has_lat_lon:
        latitude_name = roles["latitude"]
        longitude_name = roles["longitude"]

        latitude = ds[latitude_name]
        longitude = ds[longitude_name]

        if latitude.ndim == 1 and longitude.ndim == 1:
            grid_type = "rectilinear"
            y_dim = latitude.dims[0]
            x_dim = longitude.dims[0]

        elif (
            latitude.ndim == 2
            and longitude.ndim == 2
            and latitude.dims == longitude.dims
        ):
            grid_type = "curvilinear"
            y_dim, x_dim = latitude.dims

        else:
            raise ValueError(
                "Unsupported latitude/longitude coordinate structure"
            )

    else:
        raise ValueError(
            "Could not identify latitude/longitude or projected x/y"
            f"coordinates. Coordinates found: {list(ds.coords)}"
        )

    if len({time_dim, y_dim, x_dim}) != 3:
        raise ValueError(
            "Time, y, and x must be three distinct dimensions"
        )

    # Rename dimensions
    dimension_rename = {
        time_dim: "timestamp",
        y_dim: "y",
        x_dim: "x",
    }

    dimension_rename = {
        old: new
        for old, new in dimension_rename.items()
        if old != new
    }

    ds = ds.rename_dims(dimension_rename)

    # Rename coordinate variables
    coordinate_rename = {}

    if time_name in ds.variables:
        coordinate_rename[time_name] = "timestamp"

    if has_lat_lon:
        coordinate_rename[roles["latitude"]] = "latitude"
        coordinate_rename[roles["longitude"]] = "longitude"

    if grid_type == "projected":
        coordinate_rename[roles["y"]] = "y"
        coordinate_rename[roles["x"]] = "x"

    coordinate_rename = {
        old: new
        for old, new in coordinate_rename.items()
        if old != new
    }

    ds = ds.rename_vars(coordinate_rename)

    grid_info = {"grid_type": grid_type}

    return ds, grid_info

def validate_lat_lon(ds):
    ds = ds.assign_coords(
        longitude=ds["longitude"] % 360
    )

    lon = ds["longitude"]
    if lon.ndim == 1 and lon.to_index().has_duplicates:
        raise ValueError(
            "Longitude conversion produced duplicate coordinates"
        )
    
    lat = ds["latitude"]

    lat_min = lat.min().compute().item()
    lat_max = lat.max().compute().item()

    if lat_min < -90 or lat_max > 90:
        raise ValueError(
            f"Latitude values must be between -90 and 90; "
            f"found {lat_min} to {lat_max}"
        )
    
    return ds

def sort_lat_lon(ds, lat_name="latitude", lon_name="longitude"):
    ds = validate_lat_lon(ds)

    lat= ds[lat_name]
    if lat.ndim == 1 and lat[0] > lat[-1]:
        ds = ds.sortby(lat_name)

    lon = ds[lon_name]
    if lon.ndim == 1:
        ds = ds.sortby(lon_name)
    
    return ds

def unique_output_path(tmp_dir):
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return tmp_dir / f"standardized_{uuid4().hex}.nc"

def read_metadata(path: Path) -> list[dict[str, Any]]:
    """Read all metadata records."""

    with path.open("r", encoding="utf-8") as file:
        return [
            json.loads(line)
            for line in file
            if line.strip()
        ]

def write_metadata(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as file:
        for record in records:
            json.dump(record, file)
            file.write("\n")

def standardize(records, tmp_dir, metadata_output) -> None:

    standardized_metadata = []
    source_paths = set()

    for record in records:
        file_paths = record["file_paths"]
        source_paths.update(file_paths)

        # Read in all files in list
        with open_files(file_paths) as data:

            # Determine grid type, standardize coord names
            data, grid_info = inspect_grid(data)

            # Sort longitude/latitude values
            if grid_info["grid_type"] == "rectilinear":
                data = sort_lat_lon(data)
            elif grid_info["grid_type"] == "curvilinear":
                data = validate_lat_lon(data)

            # Save info of new file
            output_path = unique_output_path(tmp_dir)
            data.to_netcdf(output_path)

        standardized_record = {
            **record,
            "file_path": str(output_path),
            "grid_type": grid_info["grid_type"],
        }
        standardized_record.pop("file_paths")
        standardized_metadata.append(standardized_record)


    write_metadata(metadata_output, standardized_metadata)

    # Delete source files once consolidated and standardized data is saved.
    for path in source_paths:
        Path(path).unlink()

if __name__ == "__main__":

    settings = get_settings()

    data_to_add = settings.downloaded_data_
    records = read_metadata(data_to_add)

    tmp_dir = settings._standardized
    metadata_output = settings.standardized_data_

    standardize(records, tmp_dir, metadata_output)