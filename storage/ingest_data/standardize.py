"""
standardize.py

IN: 
CSV with columns
    file_paths
    repository
    dataset
    variable - the variable name in the NetCDF file
    spatial_resolution
    temporal_resolution
    start_year
    start_month
    end_year
    end_month
    region
    coordinates
    additional_params - includes region if region is not "COORDS"

OUT: 
Consolidated files with standardized units, coordinates, dimension names
CSV with same columns as IN
"""
import pandas as pd
import numpy as np
import xarray as xr
import json
import datetime
import random
import string
from uuid import uuid4
from pathlib import Path
from typing import Any

from polaris.config import get_settings
from storage.grid_topology import add_grid_topology

# TODO: assert the scientific variable name exists in the list of variables in
# the dataset dictionary in config.


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
        coordinate_rename[roles["y"]] = "projection_y"
        coordinate_rename[roles["x"]] = "projection_x"

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

def unique_output_path(
    directory: Path,
    unique_type="uuid",
    extension="nc",
    max_attempts=10,
):

    directory.mkdir(parents=True, exist_ok=True)

    for _ in range(max_attempts):

        if unique_type == "uuid":
            fn = f"{uuid4().hex}.{extension}"
        
        elif unique_type == "time":
            time_stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            fn = f"{time_stamp}.{extension}"
    
        elif unique_type == "random":
            rand_str = "".join(random.choices(string.ascii_letters + string.digits, k=4))
            now = datetime.datetime.now()
            ts = f"{now.day:02d}{now.microsecond:06d}"
            fn = f"{ts}_{rand_str}.{extension}"

        else:
            raise ValueError(
                f"Unsupported unique path type: {unique_type!r}"
            )

        path = directory / fn
        if not path.exists():
            return path
    
    raise ValueError(
        f"Could not generate a unique output path after {max_attempts} attempts."
    )

def get_standard_var_name(
    ds: xr.Dataset, record: dict[str, Any]
) -> tuple[xr.Dataset, str]:
    """Rename a dataset's scientific variable to its configured standard name."""
    settings = get_settings()
    name_in_dataset = record["variable"]

    try:
        standard_var_name = settings.name_docs[record["repository"]][
            record["dataset"]
        ]["variables"][name_in_dataset]
    except KeyError as error:
        raise ValueError(
            "No standard variable mapping for "
            f"{record['repository']}/{record['dataset']}/{name_in_dataset}"
        ) from error

    if name_in_dataset not in ds.data_vars:
        raise ValueError(
            f"Dataset variable {name_in_dataset!r} was not found; "
            f"available data variables: {list(ds.data_vars)}"
        )

    if name_in_dataset != standard_var_name:
        if standard_var_name in ds.variables:
            raise ValueError(
                f"Cannot rename {name_in_dataset!r} to {standard_var_name!r}: "
                "the standard name already exists in the dataset"
            )
        ds = ds.rename_vars({name_in_dataset: standard_var_name})

    return ds, standard_var_name


def remove_singleton_source_coordinates(ds: xr.Dataset) -> xr.Dataset:
    """Move technical singleton coordinates to provenance attributes."""
    result = ds
    retained = {
        "timestamp",
        "latitude",
        "longitude",
        "projection_y",
        "projection_x",
        "crs",
    }
    for name in tuple(result.coords):
        coordinate = result[name]
        if name in retained or coordinate.size != 1:
            continue
        value = coordinate.values.reshape(-1)[0]
        if isinstance(value, np.generic):
            value = value.item()
        result.attrs[f"polaris_source_coordinate_{name}"] = value
        if coordinate.dims and all(result.sizes[dim] == 1 for dim in coordinate.dims):
            result = result.squeeze(coordinate.dims, drop=True)
        elif name in result.coords:
            result = result.drop_vars(name)
    return result

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

            # Standardize variable name
            data, standard_var_name = get_standard_var_name(
                ds=data,
                record=record,
            )

            # Attach reusable grid geometry after rectilinear sorting.
            data, grid_info["grid_type"] = add_grid_topology(
                data,
                standard_var_name,
                grid_info["grid_type"],
            )
            data = remove_singleton_source_coordinates(data)

            # Save info of new file
            output_path = unique_output_path(directory=tmp_dir, unique_type="time")
            data.to_netcdf(output_path)

        standardized_record = {
            **record,
            "file_path": str(output_path),
            "grid_type": grid_info["grid_type"],
        }
        standardized_record.pop("file_paths")
        standardized_record["variable"] = standard_var_name
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
    data_to_add.write_text("", encoding="utf-8")
