"""HTTP interface for querying data managed by Polar-is."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import os
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from polaris.config import PROJECT_ROOT, Settings, get_settings
from polaris.services.job_service import (
    JobAccessDenied,
    JobNotFound,
    JobQueueFull,
    job_service,
)
from polaris.services.cleanup import cleanup_stale_outputs
from polaris.services.result_serializer import (
    grid_mapping as _grid_mapping,
)
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


class JobRequest(BaseModel):
    """One asynchronous query and its desired artifacts."""

    model_config = ConfigDict(extra="forbid")

    query: QueryRequest
    outputs: list[str] = Field(min_length=1)


@dataclass(frozen=True)
class ApiIdentity:
    owner: str
    enforce_owner_limit: bool


def access_mode() -> str:
    raw_mode = os.getenv("POLARIS_ACCESS_MODE")
    if raw_mode is None or not raw_mode.strip():
        raise RuntimeError(
            "POLARIS_ACCESS_MODE must be set to 'anonymous' or 'token'"
        )
    mode = raw_mode.strip().lower()
    if mode not in {"anonymous", "token"}:
        raise RuntimeError(
            "POLARIS_ACCESS_MODE must be either 'anonymous' or 'token'"
        )
    return mode


def configured_tokens(*, required: bool) -> dict[str, str]:
    raw_tokens = os.getenv("POLARIS_API_TOKENS", "")
    if not raw_tokens:
        if required:
            raise RuntimeError(
                "POLARIS_ACCESS_MODE=token requires POLARIS_API_TOKENS"
            )
        return {}
    try:
        tokens = json.loads(raw_tokens)
    except json.JSONDecodeError as error:
        raise RuntimeError("POLARIS_API_TOKENS is not valid JSON") from error
    if not isinstance(tokens, dict) or not tokens:
        raise RuntimeError("POLARIS_API_TOKENS must be a non-empty JSON object")
    if not all(
        isinstance(token, str)
        and token
        and isinstance(owner, str)
        and owner
        for token, owner in tokens.items()
    ):
        raise RuntimeError(
            "POLARIS_API_TOKENS must map non-empty token strings to owner names"
        )
    return tokens


def validate_access_configuration() -> str:
    mode = access_mode()
    if mode == "token":
        configured_tokens(required=True)
    return mode


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_access_configuration()
    cleanup_stale_outputs(honor_active_markers=False)
    yield


def api_settings() -> Settings:
    """Dependency boundary used by tests and future deployments."""
    return get_settings()


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
    """Summarize dataset envelopes from the shared catalogs and index."""
    if not settings.product_index.is_file() or not settings.datasets_catalog.is_file():
        return []

    def read_jsonl(path):
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    datasets = {
        record["dataset_variant_id"]: record
        for record in read_jsonl(settings.datasets_catalog)
    }
    grid_bounds: dict[str, dict[str, float]] = {}
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for record in read_jsonl(settings.product_index):
        dataset = datasets.get(record["dataset_variant_id"])
        if dataset is None:
            continue
        grid_id = record["grid_id"]
        if grid_id not in grid_bounds:
            grid_path = settings.grids_dir / f"{grid_id}.nc"
            if not grid_path.is_file():
                continue
            import xarray as xr

            with xr.open_dataset(grid_path) as grid:
                latitude = grid["latitude"].values
                longitude = grid["longitude"].values % 360
                grid_bounds[grid_id] = {
                    "west": float(longitude.min()),
                    "east": float(longitude.max()),
                    "south": float(latitude.min()),
                    "north": float(latitude.max()),
                }
        bounds = grid_bounds[grid_id]
        parameters = dataset.get("additional_parameters") or {}
        variable_metadata = dataset.get("variables", {}).get(record["variable"], {})
        source_resolution = variable_metadata.get("source_temporal_resolution")
        definition = settings.name_docs.get(dataset["repository"], {}).get(
            dataset["dataset"], {}
        )
        spatial_resolution = (definition.get("grid") or {}).get("resolution")
        if isinstance(spatial_resolution, list) and len(spatial_resolution) == 1:
            spatial_resolution = spatial_resolution[0]
        key = (
            dataset["repository"],
            dataset["dataset"],
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
                "region": dict(bounds),
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
        if spatial_resolution is not None:
            row["spatial_resolutions"].add(spatial_resolution)
        if source_resolution is not None:
            row["temporal_resolutions"].add(source_resolution)

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
    available_products: dict[tuple[str, str], set[tuple[str, str, int]]] = {}
    if settings.datasets_catalog.is_file() and settings.product_index.is_file():
        dataset_variants = {
            record["dataset_variant_id"]: record
            for record in (
                json.loads(line)
                for line in settings.datasets_catalog.read_text(
                    encoding="utf-8"
                ).splitlines()
                if line.strip()
            )
        }
        for line in settings.product_index.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            product = json.loads(line)
            dataset = dataset_variants.get(product["dataset_variant_id"])
            if dataset is None:
                continue
            key = (dataset["repository"], dataset["dataset"])
            available_products.setdefault(key, set()).add(
                (
                    product["variable"],
                    product["temporal_resolution"],
                    int(product["coarseness_factor"]),
                )
            )
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
                    "available_products": [
                        {
                            "variable": variable,
                            "time_unit": time_unit,
                            "coarseness_factor": factor,
                        }
                        for variable, time_unit, factor in sorted(
                            available_products.get(
                                (repository_name, dataset_name), set()
                            )
                        )
                    ],
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
        "coarseness_factors": sorted(settings.supported_coarseness_factors),
        "time_units": list(TIME_UNITS),
        "functions": list(settings.supported_query_functions),
        "aggregation_methods": list(settings.function_aggregation_methods),
    }


app = FastAPI(
    title="Polar-is API",
    description="Query the spatio-temporal data managed by Polar-is.",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

_bearer = HTTPBearer(auto_error=False)


def api_identity(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ApiIdentity:
    """Return an anonymous conference identity or a configured token owner."""
    if access_mode() == "anonymous":
        return ApiIdentity("anonymous", enforce_owner_limit=False)
    try:
        tokens = configured_tokens(required=True)
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    if credentials is None or credentials.credentials not in tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid Polar-is access token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return ApiIdentity(tokens[credentials.credentials], enforce_owner_limit=True)


@app.get("/api/catalog")
def get_catalog(settings: Settings = Depends(api_settings)) -> dict[str, Any]:
    return _catalog(settings)


@app.get("/api/availability")
def get_availability(
    settings: Settings = Depends(api_settings),
) -> dict[str, Any]:
    return {"rows": _availability(settings)}


@app.post("/api/v1/jobs", status_code=status.HTTP_202_ACCEPTED)
def create_job(
    request: JobRequest,
    identity: ApiIdentity = Depends(api_identity),
    settings: Settings = Depends(api_settings),
) -> dict[str, Any]:
    """Validate and enqueue one prototype query job."""
    try:
        job = job_service.submit(
            request.query.model_dump(),
            request.outputs,
            identity.owner,
            settings,
            enforce_owner_limit=identity.enforce_owner_limit,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except JobQueueFull as error:
        raise HTTPException(
            status_code=429,
            detail=str(error),
            headers={"Retry-After": "5"},
        ) from error
    return job_service.response(job)


def _owned_job(job_id: str, owner: str):
    try:
        return job_service.get(job_id, owner)
    except JobAccessDenied as error:
        raise HTTPException(status_code=403, detail="Job access denied") from error
    except JobNotFound as error:
        raise HTTPException(status_code=404, detail="Job not found") from error


@app.get("/api/v1/jobs/{job_id}")
def get_job(
    job_id: str,
    identity: ApiIdentity = Depends(api_identity),
) -> dict[str, Any]:
    return job_service.response(_owned_job(job_id, identity.owner))


@app.delete("/api/v1/jobs/{job_id}")
def cancel_job(
    job_id: str,
    identity: ApiIdentity = Depends(api_identity),
) -> dict[str, Any]:
    _owned_job(job_id, identity.owner)
    return job_service.response(job_service.cancel(job_id, identity.owner))


@app.get("/api/v1/jobs/{job_id}/outputs/{group_id}/{kind}")
def download_job_output(
    job_id: str,
    group_id: str,
    kind: str,
    identity: ApiIdentity = Depends(api_identity),
) -> FileResponse:
    _owned_job(job_id, identity.owner)
    try:
        artifact = job_service.artifact(job_id, group_id, kind, identity.owner)
    except JobNotFound as error:
        raise HTTPException(status_code=404, detail="Job output not found") from error
    if not artifact.path.is_file():
        raise HTTPException(status_code=404, detail="Job output not found")
    return FileResponse(
        artifact.path,
        media_type=artifact.media_type,
        filename=artifact.filename,
    )


@app.get("/api/v1/status")
def get_service_status() -> dict[str, Any]:
    return {"access_mode": access_mode(), **job_service.status()}


frontend_dist = PROJECT_ROOT / "api" / "interface" / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
