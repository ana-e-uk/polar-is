import math
import json
from pathlib import Path

import numpy as np
import xarray as xr

from polaris.config import get_settings

LON_MIN = 0
LAT_MIN = -90
LON_SIZE = 60
LAT_SIZE = 30
N_COLS = 6
N_ROWS = 6

def normalize_lon_0_360(lon):
    return lon % 360


def bucket_for_point(lon, lat):
    lon = normalize_lon_0_360(lon)

    # Handle edge case exactly on the max latitude boundary.
    if lat == 90:
        lat = 89.999999999

    col = math.floor((lon - LON_MIN) / LON_SIZE)
    row = math.floor((lat - LAT_MIN) / LAT_SIZE)

    if not (0 <= row < N_ROWS and 0 <= col < N_COLS):
        raise ValueError(f"Point outside bucket bounds: lon={lon}, lat={lat}")

    return f"r{row}_c{col}"

def map_buckets(ds):
    """Assign every native grid-cell center to one canonical space bucket.

    IN: ``ds`` must contain standardized ``latitude`` and ``longitude``
    coordinates.

    Generates a mapping of bucket codes for each data cell without regridding/
    modifying data values. 
    Currently, bucket codes are from 0-35 and ``code = row * N_COLS + col`` for
    bucket id ``r{row}_c{col}``.

    OUT: integer DataArray - dimensions ``(y, x)``
    """
    if "latitude" not in ds.coords or "longitude" not in ds.coords:
        raise ValueError(
            "ds must contain latitude and longitude coordinates"
        )

    latitude = ds["latitude"]
    longitude = ds["longitude"]

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

    coordinates_are_finite = (
        np.isfinite(latitude).all() & np.isfinite(longitude).all()
    ).compute().item()
    if not coordinates_are_finite:
        raise ValueError(
            "Every native grid cell must have a finite latitude and longitude "
            "center"
        )

    lat_min = latitude.min().compute().item()
    lat_max = latitude.max().compute().item()
    if not (-90 <= lat_min <= lat_max <= 90):
        raise ValueError(
            f"Latitude values must be between -90 and 90; "
            f"found {lat_min} to {lat_max}"
        )

    longitude = longitude % 360
    rows = np.floor((latitude - LAT_MIN) / LAT_SIZE)
    rows = xr.where(latitude == 90, N_ROWS - 1, rows)
    columns = np.floor((longitude - LON_MIN) / LON_SIZE)

    bucket_codes = (rows * N_COLS + columns).astype(np.int8)
    bucket_codes.name = "bucket_code"
    bucket_codes.attrs = {
        "long_name": "canonical space bucket code",
        "valid_min": 0,
        "valid_max": N_ROWS * N_COLS - 1,
        "bucket_code_formula": "r{id // N_COLS}_c{id % N_COLS}",
        "N_COLS": N_COLS,
    }
    return bucket_codes.transpose("y", "x")


def get_space_buckets():
    buckets = {}

    for row in range(N_ROWS):
        for col in range(N_COLS):
            lon_min = LON_MIN + col * LON_SIZE
            lon_max = lon_min + LON_SIZE

            lat_min = LAT_MIN + row * LAT_SIZE
            lat_max = lat_min + LAT_SIZE

            bucket_code = f"r{row}_c{col}"

            buckets[bucket_code] = {
                "id": bucket_code,
                "row": row,
                "col": col,
                "bounds": {
                    "lon_min": lon_min,
                    "lon_max": lon_max,
                    "lat_min": lat_min,
                    "lat_max": lat_max,
                },
                "data": [],
            }

    settings = get_settings()

    with open(Path(settings.buckets_), "w") as f:
        json.dump(buckets, f, indent=2)

if __name__ == "__main__":
    get_space_buckets()
