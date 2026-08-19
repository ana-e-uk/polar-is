import math
import json
from pathlib import Path

import numpy as np
import xarray as xr

from polaris.config import get_settings

LON_SPAN = 360
LAT_SPAN = 180


def _positive_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"bucket_grid.{name} must be a number")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(
            f"bucket_grid.{name} must be a finite number greater than zero"
        )
    return value


def _partition_count(span, size, name):
    count = span / size
    rounded_count = round(count)
    if not math.isclose(count, rounded_count):
        raise ValueError(
            f"bucket_grid.{name}={size} must divide {span} exactly"
        )
    return int(rounded_count)


_BUCKET_GRID = get_settings().bucket_grid
LON_MIN = _BUCKET_GRID["lon_min"]
LAT_MIN = _BUCKET_GRID["lat_min"]
LON_SIZE = _positive_number(_BUCKET_GRID["lon_size"], "lon_size")
LAT_SIZE = _positive_number(_BUCKET_GRID["lat_size"], "lat_size")

if isinstance(LON_MIN, bool) or not isinstance(LON_MIN, (int, float)):
    raise ValueError("bucket_grid.lon_min must be a number")
if not math.isfinite(LON_MIN):
    raise ValueError("bucket_grid.lon_min must be finite")
if isinstance(LAT_MIN, bool) or not isinstance(LAT_MIN, (int, float)):
    raise ValueError("bucket_grid.lat_min must be a number")
if LAT_MIN != -90:
    raise ValueError("bucket_grid.lat_min must be -90 to cover the whole Earth")

N_COLS = _partition_count(LON_SPAN, LON_SIZE, "lon_size")
N_ROWS = _partition_count(LAT_SPAN, LAT_SIZE, "lat_size")
LON_MAX = LON_MIN + LON_SPAN
LAT_MAX = LAT_MIN + LAT_SPAN
if N_ROWS * N_COLS - 1 > np.iinfo(np.int32).max:
    raise ValueError("Configured bucket grid has too many buckets for int32 codes")


def normalize_lon_to_bucket_grid(lon):
    """Normalize longitude into the configured half-open longitude range."""
    return (lon - LON_MIN) % LON_SPAN + LON_MIN


def bucket_for_point(lon, lat):
    lon = normalize_lon_to_bucket_grid(lon)

    col = math.floor((lon - LON_MIN) / LON_SIZE)
    if lat == LAT_MAX:
        row = N_ROWS - 1
    else:
        row = math.floor((lat - LAT_MIN) / LAT_SIZE)

    if not (0 <= row < N_ROWS and 0 <= col < N_COLS):
        raise ValueError(f"Point outside bucket bounds: lon={lon}, lat={lat}")

    return f"r{row}_c{col}"


def bucket_id_from_code(code):
    """Convert a numeric bucket code to its canonical bucket id string."""
    if not isinstance(code, (int, np.integer)):
        raise TypeError("Bucket code must be an integer")
    if not 0 <= code < N_ROWS * N_COLS:
        raise ValueError(
            f"Bucket code must be between 0 and {N_ROWS * N_COLS - 1}"
        )

    row = int(code) // N_COLS
    col = int(code) % N_COLS
    return f"r{row}_c{col}"


def map_buckets(ds):
    """Assign every native grid-cell center to one canonical space bucket.

    IN: ``ds`` must contain standardized ``latitude`` and ``longitude``
    coordinates.

    Generates a mapping of bucket codes for each data cell without regridding/
    modifying data values. 
    Bucket codes run from zero through the configured number of buckets minus
    one. ``code = row * N_COLS + col`` corresponds to bucket ID
    ``r{row}_c{col}``.

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
    if not (LAT_MIN <= lat_min <= lat_max <= LAT_MAX):
        raise ValueError(
            f"Latitude values must be between {LAT_MIN} and {LAT_MAX}; "
            f"found {lat_min} to {lat_max}"
        )

    longitude = (longitude - LON_MIN) % LON_SPAN + LON_MIN
    rows = np.floor((latitude - LAT_MIN) / LAT_SIZE)
    rows = xr.where(latitude == LAT_MAX, N_ROWS - 1, rows)
    columns = np.floor((longitude - LON_MIN) / LON_SIZE)

    bucket_codes = (rows * N_COLS + columns).astype(np.int32)
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
