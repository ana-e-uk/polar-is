"""HTTP interface for querying data managed by Polar-is."""

from __future__ import annotations

from dataclasses import asdict
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
        return payload
    if function in {"heatmap", "find-area"}:
        payload = {
            "kind": function,
            "latitudes": [_json_number(value) for value in data["latitude"].values],
            "longitudes": [
                _json_number(((float(value) + 180) % 360) - 180)
                for value in data["longitude"].values
            ],
            "values": _values(data, variable),
        }
        if "matches" in data:
            payload["matches"] = [bool(value) for value in data["matches"].values]
        return payload
    return {
        "kind": "get-data",
        "timestamps": _timestamps(data["timestamp"].values),
        "cell_count": int(data.sizes.get("cell", 0)),
    }


def _serialize_group(group: GroupResult, result: QueryResult) -> dict[str, Any]:
    return {
        "group_id": group.group_id,
        "source": asdict(group.source),
        "units": group.units,
        "warnings": list(group.warnings),
        "coverage": {
            "hit_count": len(group.hit_set),
            "miss_count": len(group.miss_set),
        },
        "download_url": (
            f"/api/results/{result.query_id}/{result.function}/"
            f"{group.group_id}/download"
        ),
        "data": _serialize_plot_data(group, result.function),
    }


def _catalog(settings: Settings) -> dict[str, Any]:
    repositories = []
    for repository_name, dataset_definitions in settings.name_docs.items():
        datasets = []
        for dataset_name, definition in dataset_definitions.items():
            datasets.append(
                {
                    "name": dataset_name,
                    "variables": sorted(set(definition.get("variables", {}).values())),
                    "additional_parameters": definition.get(
                        "additional_parameters", {}
                    ),
                    "temporal_sampling": definition.get("temporal_sampling", []),
                    "grid": definition.get("grid"),
                }
            )
        repositories.append({"name": repository_name, "datasets": datasets})
    return {
        "repositories": repositories,
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
        "groups": [_serialize_group(group, result) for group in result.groups],
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
