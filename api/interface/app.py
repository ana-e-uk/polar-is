"""HTTP interface for querying data managed by Polar-is."""

from __future__ import annotations

from dataclasses import asdict
import json
import math
import re
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import numpy as np
from pydantic import BaseModel, ConfigDict, Field
import xarray as xr

from polaris.config import PROJECT_ROOT, Settings, get_settings
from storage.query_data.executor import GroupResult, QueryResult, execute_query
from storage.query_data.query_data import TIME_UNITS


class RegionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    west: float
    east: float
    south: float
    north: float


class QueryRequest(BaseModel):
    """Browser-facing form of a Polar-is query."""

    model_config = ConfigDict(extra="forbid")

    variable: str
    region: RegionRequest
    time_start: str
    time_end: str
    coarseness_factor: int
    time_unit: str
    function: str
    aggregation_method: str
    repository: str | None = None
    dataset: str | None = None
    additional_parameters: dict[str, Any] = Field(default_factory=dict)
    predicate: str | None = None
    filter_value: float | None = None


def api_settings() -> Settings:
    """Dependency boundary used by tests and future deployments."""
    return get_settings()


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


def _grid_mapping(data: xr.Dataset, variable: str) -> dict[str, Any] | None:
    """Return the compact CF projection definition needed by the browser."""
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
    """Keep each polygon continuous while using familiar displayed longitudes."""
    rows = []
    for center, corners in zip(data["longitude"].values, data["corner_longitude"].values):
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


def _serialize_plot_data(group: GroupResult, function: str) -> dict[str, Any]:
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
            "longitudes": [_display_longitude(value) for value in data["longitude"].values],
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


def _serialize_group(
    group: GroupResult,
    result: QueryResult,
    settings: Settings,
) -> dict[str, Any]:
    dataset_definition = settings.name_docs.get(group.source.repository, {}).get(
        group.source.dataset, {}
    )
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
        "grid_mapping": _grid_mapping(group.data, group.source.variable),
        "coarseness_factor": int(group.data.attrs["coarseness_factor"]),
        "download_url": (
            f"/api/results/{result.query_id}/{result.function}/"
            f"{group.group_id}/download"
        ),
        "data": _serialize_plot_data(group, result.function),
    }


def _display_bounds(west: float, east: float) -> tuple[float, float]:
    """Convert one storage-longitude envelope to a readable UI envelope."""
    if east - west >= 359:
        return -180.0, 180.0
    if west >= 180:
        return west - 360, east - 360
    if east <= 180:
        return west, east
    return -180.0, 180.0


def _availability(settings: Settings) -> list[dict[str, Any]]:
    """Summarize native-data envelopes without opening any NetCDF blocks."""
    spatial_level = settings.coarseness_to_spatial_level.get(1)
    if spatial_level is None or not spatial_level.metadata.is_file():
        return []

    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    with spatial_level.metadata.open() as metadata:
        for line in metadata:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("product_type") != "native":
                continue
            summary = record.get("block_summary") or {}
            try:
                bounds = {
                    "west": float(summary["lon_min"]),
                    "east": float(summary["lon_max"]),
                    "south": float(summary["lat_min"]),
                    "north": float(summary["lat_max"]),
                }
            except (KeyError, TypeError, ValueError):
                continue
            parameters = record.get("additional_parameters") or {}
            key = (
                record["repository"],
                record["dataset"],
                record["variable"],
                json.dumps(parameters, sort_keys=True, separators=(",", ":")),
            )
            row = grouped.setdefault(
                key,
                {
                    "repository": key[0],
                    "dataset": key[1],
                    "variable": key[2],
                    "additional_parameters": parameters,
                    "region": bounds,
                    "time_start": record["time_start"],
                    "time_end": record["time_end"],
                    "spatial_resolutions": set(),
                    "temporal_resolutions": set(),
                },
            )
            row["region"]["west"] = min(row["region"]["west"], bounds["west"])
            row["region"]["east"] = max(row["region"]["east"], bounds["east"])
            row["region"]["south"] = min(row["region"]["south"], bounds["south"])
            row["region"]["north"] = max(row["region"]["north"], bounds["north"])
            row["time_start"] = min(row["time_start"], record["time_start"])
            row["time_end"] = max(row["time_end"], record["time_end"])
            row["spatial_resolutions"].add(record.get("native_spatial_resolution"))
            row["temporal_resolutions"].add(record.get("native_temporal_resolution"))

    rows = []
    for row in grouped.values():
        west, east = _display_bounds(row["region"]["west"], row["region"]["east"])
        row["region"]["west"] = round(west, 3)
        row["region"]["east"] = round(east, 3)
        row["region"]["south"] = round(row["region"]["south"], 3)
        row["region"]["north"] = round(row["region"]["north"], 3)
        row["spatial_resolutions"] = sorted(
            value for value in row["spatial_resolutions"] if value is not None
        )
        row["temporal_resolutions"] = sorted(
            value for value in row["temporal_resolutions"] if value is not None
        )
        rows.append(row)
    return sorted(
        rows,
        key=lambda row: (
            row["repository"],
            row["dataset"],
            row["variable"],
            json.dumps(row["additional_parameters"], sort_keys=True),
        ),
    )


def _catalog(settings: Settings) -> dict[str, Any]:
    repository_titles = settings.frontend_titles.get("repository", {})
    repositories = []
    for repository_name, dataset_definitions in settings.name_docs.items():
        datasets = []
        for dataset_name, definition in dataset_definitions.items():
            datasets.append(
                {
                    "name": dataset_name,
                    "display_name": definition.get("display_name"),
                    "variables": sorted(set(definition.get("variables", {}).values())),
                    "additional_parameters": definition.get(
                        "additional_parameters", {}
                    ),
                    "temporal_sampling": definition.get("temporal_sampling", []),
                    "grid": definition.get("grid"),
                }
            )
        repositories.append(
            {
                "name": repository_name,
                "display_name": repository_titles.get(repository_name),
                "datasets": datasets,
            }
        )
    return {
        "repositories": repositories,
        "frontend_titles": settings.frontend_titles,
        "coarseness_factors": sorted(settings.coarseness_to_spatial_level),
        "time_units": list(TIME_UNITS),
        "functions": list(settings.supported_query_functions),
        "aggregation_methods": list(settings.function_aggregation_methods),
    }


app = FastAPI(
    title="Polar-is API",
    description="Query the spatio-temporal data managed by Polar-is.",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/api/catalog")
def get_catalog(settings: Settings = Depends(api_settings)) -> dict[str, Any]:
    return _catalog(settings)


@app.get("/api/availability")
def get_availability(
    settings: Settings = Depends(api_settings),
) -> dict[str, Any]:
    return {"rows": _availability(settings)}


@app.post("/api/queries")
def post_query(
    request: QueryRequest,
    settings: Settings = Depends(api_settings),
) -> dict[str, Any]:
    try:
        result = execute_query(request.model_dump(), settings)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "query_id": result.query_id,
        "function": result.function,
        "warnings": list(result.warnings),
        "unmatched_miss_count": len(result.unmatched_miss_set),
        "groups": [
            _serialize_group(group, result, settings) for group in result.groups
        ],
    }


_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


@app.get("/api/results/{query_id}/{function}/{group_id}/download")
def download_result(
    query_id: str,
    function: str,
    group_id: str,
    settings: Settings = Depends(api_settings),
) -> FileResponse:
    if (
        not _ID_PATTERN.fullmatch(query_id)
        or not _ID_PATTERN.fullmatch(group_id)
        or function not in settings.supported_query_functions
    ):
        raise HTTPException(status_code=404, detail="Result not found")
    path = settings._query_results / query_id / function / f"{group_id}.nc"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Result not found")
    return FileResponse(
        path,
        media_type="application/x-netcdf",
        filename=f"polar-is-{query_id}-{group_id}.nc",
    )


frontend_dist = PROJECT_ROOT / "api" / "interface" / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
