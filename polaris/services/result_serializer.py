"""Serialize query results for browser and API clients."""

from __future__ import annotations

from dataclasses import asdict
import math
from typing import Any, Callable

import numpy as np
import xarray as xr

from polaris.config import Settings
from storage.query_data.executor import GroupResult, QueryResult


def _json_number(value: Any) -> float | None:
    number = float(value)
    return number if math.isfinite(number) else None


def _timestamps(values: Any) -> list[str]:
    return [
        np.datetime_as_string(np.datetime64(value), unit="s")
        for value in np.asarray(values)
    ]


def _values(data: xr.Dataset, variable: str) -> list[float | None]:
    return [_json_number(value) for value in data[variable].values]


def _numeric_coordinate(data: xr.Dataset, name: str) -> list[float | None]:
    return [_json_number(value) for value in data[name].values]


def _integer_coordinate(data: xr.Dataset, name: str) -> list[int]:
    return [int(value) for value in data[name].values]


def grid_mapping(data: xr.Dataset, variable: str) -> dict[str, Any] | None:
    """Return the compact CF projection definition needed by clients."""
    mapping_name = data[variable].attrs.get("grid_mapping")
    if not mapping_name or mapping_name not in data:
        return None
    attributes = data[mapping_name].attrs
    keys = (
        "grid_mapping_name",
        "standard_parallel",
        "longitude_of_central_meridian",
        "latitude_of_projection_origin",
        "false_easting",
        "false_northing",
        "earth_radius",
        "semi_major_axis",
        "inverse_flattening",
    )
    mapping: dict[str, Any] = {}
    for key in keys:
        if key not in attributes:
            continue
        value = attributes[key]
        if isinstance(value, np.ndarray):
            mapping[key] = value.tolist()
        elif isinstance(value, np.generic):
            mapping[key] = value.item()
        else:
            mapping[key] = value
    return mapping or None


def _display_longitude(value: Any) -> float | None:
    number = _json_number(value)
    return None if number is None else ((number + 180) % 360) - 180


def _display_corner_longitudes(data: xr.Dataset) -> list[list[float | None]]:
    """Keep each polygon continuous while using familiar longitudes."""
    rows = []
    for center, corners in zip(
        data["longitude"].values, data["corner_longitude"].values
    ):
        display_center = ((float(center) + 180) % 360) - 180
        row = []
        for corner in corners:
            display_corner = ((float(corner) + 180) % 360) - 180
            while display_corner - display_center > 180:
                display_corner -= 360
            while display_corner - display_center < -180:
                display_corner += 360
            row.append(_json_number(display_corner))
        rows.append(row)
    return rows


def serialize_plot_data(group: GroupResult, function: str) -> dict[str, Any]:
    """Return the plot model for one result group."""
    data = group.data
    variable = group.source.variable
    if function in {"timeseries", "find-time"}:
        payload: dict[str, Any] = {
            "kind": function,
            "timestamps": _timestamps(data["timestamp"].values),
            "values": _values(data, variable),
        }
        if "matches" in data:
            payload["matches"] = [bool(value) for value in data["matches"].values]
            payload["predicate"] = data["matches"].attrs.get("predicate")
            payload["filter_value"] = _json_number(
                data["matches"].attrs.get("filter_value")
            )
        return payload
    if function in {"heatmap", "find-area"}:
        payload = {
            "kind": function,
            "cell_ids": [str(value) for value in data["cell_id"].values],
            "latitudes": [_json_number(value) for value in data["latitude"].values],
            "longitudes": [
                _display_longitude(value) for value in data["longitude"].values
            ],
            "source_y_indices": _integer_coordinate(data, "source_y_index"),
            "source_x_indices": _integer_coordinate(data, "source_x_index"),
            "source_y_starts": _integer_coordinate(data, "source_y_start"),
            "source_y_stops": _integer_coordinate(data, "source_y_stop"),
            "source_x_starts": _integer_coordinate(data, "source_x_start"),
            "source_x_stops": _integer_coordinate(data, "source_x_stop"),
            "grid_y_indices": _integer_coordinate(data, "grid_y_index"),
            "grid_x_indices": _integer_coordinate(data, "grid_x_index"),
            "corner_latitudes": [
                [_json_number(value) for value in row]
                for row in data["corner_latitude"].values
            ],
            "corner_longitudes": _display_corner_longitudes(data),
            "values": _values(data, variable),
        }
        if "projection_x" in data.coords:
            payload["projection_x"] = _numeric_coordinate(data, "projection_x")
        if "projection_y" in data.coords:
            payload["projection_y"] = _numeric_coordinate(data, "projection_y")
        if "matches" in data:
            payload["matches"] = [bool(value) for value in data["matches"].values]
            payload["predicate"] = data["matches"].attrs.get("predicate")
            payload["filter_value"] = _json_number(
                data["matches"].attrs.get("filter_value")
            )
        return payload
    return {
        "kind": "get-data",
        "timestamps": _timestamps(data["timestamp"].values),
        "cell_count": int(data.sizes.get("cell", 0)),
    }


def serialize_group(
    group: GroupResult,
    result: QueryResult,
    settings: Settings,
    download_url: str | Callable[[GroupResult], str],
) -> dict[str, Any]:
    """Serialize one result group with a caller-selected download URL."""
    dataset_definition = settings.name_docs.get(group.source.repository, {}).get(
        group.source.dataset, {}
    )
    resolved_url = download_url(group) if callable(download_url) else download_url
    return {
        "group_id": group.group_id,
        "source": asdict(group.source),
        "units": group.units,
        "warnings": list(group.warnings),
        "coverage": {
            "hit_count": len(group.hit_set),
            "miss_count": len(group.miss_set),
        },
        "grid": dataset_definition.get("grid"),
        "grid_mapping": grid_mapping(group.data, group.source.variable),
        "coarseness_factor": int(group.data.attrs["coarseness_factor"]),
        "download_url": resolved_url,
        "data": serialize_plot_data(group, result.function),
    }


def serialize_result(
    result: QueryResult,
    settings: Settings,
    download_url: Callable[[GroupResult], str],
) -> dict[str, Any]:
    """Serialize a complete query result."""
    return {
        "query_id": result.query_id,
        "function": result.function,
        "warnings": list(result.warnings),
        "unmatched_miss_count": len(result.unmatched_miss_set),
        "groups": [
            serialize_group(group, result, settings, download_url)
            for group in result.groups
        ],
    }
